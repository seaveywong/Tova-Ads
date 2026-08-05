"""FB Webhook callback（pages_manage_metadata scope）。

FB 订阅主页事件（leadgen/feed/messages）→ 推送到本端点。
GET /fb/webhook — FB 订阅验证（hub.mode=subscribe + hub.verify_token → hub.challenge）
POST /fb/webhook — FB 推送事件（leadgen → 存 leads 表）

安全：
- GET 用 verify_token 证明端点归属（FB 配置时校验）。verify_token 存 system_settings，前端系统设置 UI 改。
- POST 校验 X-Hub-Signature-256 HMAC-SHA256：**遍历所有 active App 的 app_secret 逐一比对**
  （payload 不带 app_id，"哪个 secret 验过 = 该 lead 属于那个 App"）。无 active App 或全部不匹配 → 403。
  App Secret 复用 fb_apps 表（前端 App 管理 UI 已配），无需额外 .env。
"""
import json, hmac, hashlib, logging
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Response
from ..core.database import SuperSessionLocal
from ..core.webhook_config import get_webhook_config, get_active_app_secrets
from ..models.lead import Lead
from ..models.lead_form_template import LeadFormTemplate

router = APIRouter(prefix="/fb/webhook", tags=["fb-webhook"])
logger = logging.getLogger("toveads.fb_webhook")


def _verify_signature(body: bytes, sig_header: str, secrets: list[dict]) -> bool:
    """X-Hub-Signature-256 = 'sha256=<hex>'。遍历 active App secret 逐一验签。"""
    if not sig_header or not sig_header.startswith("sha256="):
        return False
    for app in secrets:
        expected = "sha256=" + hmac.new(app["secret"].encode(), body, hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected, sig_header):
            return True
    return False


def _parse_created_time(raw):
    """FB created_time 兼容解析：webhook 推 Unix 时间戳(int)，GET /leads 返 ISO 字符串。→ datetime|None。"""
    if not raw:
        return None
    try:
        if isinstance(raw, (int, float)):
            return datetime.fromtimestamp(raw, tz=timezone.utc)
        s = str(raw).replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        return None


@router.get("")
async def fb_webhook_verify(request: Request):
    """FB 订阅验证：FB 发 GET hub.mode=subscribe&hub.verify_token=XXX&hub.challenge=NNN → 返回 challenge。"""
    p = request.query_params
    if p.get("hub.mode") == "subscribe":
        db = SuperSessionLocal()
        try:
            verify_token = get_webhook_config(db)["verify_token"]
        finally:
            db.close()
        if p.get("hub.verify_token") == verify_token:
            return Response(content=p.get("hub.challenge", ""), media_type="text/plain")
    return Response(content="Forbidden", status_code=403)


@router.post("")
async def fb_webhook_receive(request: Request):
    """FB 推送事件。leadgen → 存 leads 表。返回 200（FB 要求快速 200）。

    HMAC 遍历 active App secret 验签；无 active App 或验不过 → 403。
    webhook 只带 leadgen_id/form_id/ad_id/created_time（不带 field_data 答案），
    答案由 /leads/sync（GET /{form_id}/leads）回填——webhook 快速通知，sync 补全数据。
    """
    body_bytes = await request.body()
    db = SuperSessionLocal()
    try:
        secrets = get_active_app_secrets(db)
        if not secrets:
            logger.warning("[FB Webhook] 无 active App，拒绝（先在前端 App 管理建 App）")
            return Response(content="No App Configured", status_code=403)
        if not _verify_signature(body_bytes, request.headers.get("x-hub-signature-256", ""), secrets):
            logger.warning("[FB Webhook] 签名校验失败，丢弃")
            return Response(content="Invalid Signature", status_code=403)
        try:
            body = json.loads(body_bytes)
        except Exception:
            return Response(content="Bad JSON", status_code=400)

        for entry in body.get("entry", []):
            page_id = entry.get("id")
            for change in entry.get("changes", []):
                if change.get("field") != "leadgen":
                    continue
                value = change.get("value", {})
                lead_id = value.get("leadgen_id") or value.get("id")
                form_id = value.get("form_id")
                ad_id = value.get("ad_id")
                created_time = _parse_created_time(value.get("created_time"))
                if not lead_id:
                    continue
                lid = str(lead_id)
                if db.query(Lead).filter(Lead.lead_id == lid).first():
                    continue
                # form_id → tenant 反查（LeadFormTemplate.fb_form_id）
                tenant_id = None
                if form_id:
                    tpl = db.query(LeadFormTemplate).filter(
                        LeadFormTemplate.fb_form_id == str(form_id)
                    ).first()
                    tenant_id = tpl.tenant_id if tpl else None
                if not tenant_id:
                    logger.info(f"[FB Webhook] lead 无归属租户: lead_id={lid} form={form_id}")
                    continue
                db.add(Lead(
                    tenant_id=tenant_id, page_id=str(page_id) if page_id else None,
                    ad_id=str(ad_id) if ad_id else None,
                    form_id=str(form_id) if form_id else None,
                    lead_id=lid, field_data_json="[]",  # webhook 不带答案，sync 回填
                    created_time=created_time,
                ))
                db.commit()
                logger.info(f"[FB Webhook] lead 存入: lead_id={lid} page={page_id} tenant={tenant_id}")
    except Exception as e:
        logger.exception(f"[FB Webhook] 处理异常: {e}")
    finally:
        db.close()
    return Response(content="EVENT_RECEIVED", status_code=200)
