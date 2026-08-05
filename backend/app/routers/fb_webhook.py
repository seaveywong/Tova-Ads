"""FB Webhook callback（pages_manage_metadata scope）。

FB 订阅主页事件（leadgen/feed/messages）→ 推送到本端点。
GET /fb/webhook — FB 订阅验证（hub.mode=subscribe + hub.verify_token → hub.challenge）
POST /fb/webhook — FB 推送事件（leadgen → 存 leads 表）

安全：
- GET 用 verify_token 证明端点归属（FB 配置时校验）。
- POST 校验 X-Hub-Signature-256 HMAC-SHA256（payload + FB_APP_SECRET）——防伪造。
  FB_APP_SECRET 未配则跳过（dev/测试），生产应配。
"""
import json, os, hmac, hashlib, logging
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Response
from ..core.database import SuperSessionLocal
from ..models.lead import Lead
from ..models.lead_form_template import LeadFormTemplate

router = APIRouter(prefix="/fb/webhook", tags=["fb-webhook"])
logger = logging.getLogger("toveads.fb_webhook")

VERIFY_TOKEN = os.environ.get("FB_WEBHOOK_VERIFY_TOKEN", "toveads_webhook_verify")
FB_APP_SECRET = os.environ.get("FB_APP_SECRET", "")


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


def _verify_signature(body: bytes, sig_header: str) -> bool:
    """X-Hub-Signature-256 = 'sha256=<hex>'。FB_APP_SECRET 未配 → 跳过（dev）。"""
    if not FB_APP_SECRET:
        return True
    if not sig_header or not sig_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(FB_APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig_header)


@router.get("")
async def fb_webhook_verify(request: Request):
    """FB 订阅验证：FB 发 GET hub.mode=subscribe&hub.verify_token=XXX&hub.challenge=NNN → 返回 challenge。"""
    p = request.query_params
    if p.get("hub.mode") == "subscribe" and p.get("hub.verify_token") == VERIFY_TOKEN:
        return Response(content=p.get("hub.challenge", ""), media_type="text/plain")
    return Response(content="Forbidden", status_code=403)


@router.post("")
async def fb_webhook_receive(request: Request):
    """FB 推送事件。leadgen → 存 leads 表。返回 200（FB 要求快速 200）。

    webhook 只带 leadgen_id/form_id/ad_id/created_time（不带 field_data 答案），
    答案由 /leads/sync（GET /{form_id}/leads）回填——webhook 快速通知，sync 补全数据。
    """
    body_bytes = await request.body()
    if not _verify_signature(body_bytes, request.headers.get("x-hub-signature-256", "")):
        logger.warning("[FB Webhook] 签名校验失败，丢弃")
        return Response(content="Invalid Signature", status_code=403)
    try:
        body = json.loads(body_bytes)
    except Exception:
        return Response(content="Bad JSON", status_code=400)

    db = SuperSessionLocal()
    try:
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
                    # 找不到归属租户的 lead 不存（避免孤儿数据）；FB 端不影响
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
