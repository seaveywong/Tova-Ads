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
from sqlalchemy.exc import IntegrityError
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
        if hmac.compare_digest(p.get("hub.verify_token", "").encode(), (verify_token or "").encode()):
            return Response(content=p.get("hub.challenge", ""), media_type="text/plain")
    return Response(content="Forbidden", status_code=403)


# 活跃页集合缓存（tenant_id → (ts, {page_id})，TTL 10min）：webhook 页归属闸用——
# 订阅是 page×App 级不随令牌失效，旧主页（令牌已删）事件仍会推来；不在当前活跃令牌
# 页集合的页直接忽略，防旧业务线潜客混入（2026-09-08 用户确认清理旧主页）。
_PAGE_SET_TTL = 600.0
_PAGE_SET_CACHE: dict = {}


def _active_page_ids(db, tenant_id: int) -> set | None:
    """租户当前活跃令牌可管理的页 id 集（None=拉取失败，调用方 fail-open 放行）。

    全量成功才缓存：任一令牌 me/accounts 失败即返 None（曾 per-cred continue 把部分
    集合缓存 10min 当权威 → 缺失页的 lead 被「旧主页」忽略且 200 → FB 不再重推 →
    潜客永久丢失）。状态放宽到 rate_limited（限流冷却是 30min 瞬时态，冷却中令牌的
    页不是旧主页——曾硬过滤 active 把冷却期页全误判）。"""
    import time as _t
    now = _t.time()
    ent = _PAGE_SET_CACHE.get(tenant_id)
    if ent and now - ent[0] < _PAGE_SET_TTL:
        return ent[1]
    from app.core.encryption import decrypt
    from app.core.fb_client import FbClient
    from app.models.fb import FbCredential
    pages: set = set()
    creds = db.query(FbCredential).filter(
        FbCredential.tenant_id == tenant_id,
        FbCredential.status.in_(("active", "rate_limited")),
    ).all()
    if not creds:
        return None   # 无令牌租户 fail-open（不拦）
    for c in creds:
        try:
            fb = FbClient(decrypt(c.access_token_enc))
            for p in fb.get_paged("me/accounts", {"fields": "id"}):
                if p.get("id"):
                    pages.add(str(p["id"]))
        except Exception:
            return None   # 任一失败 → 整体 fail-open（绝不缓存部分集合）
    if pages:
        _PAGE_SET_CACHE[tenant_id] = (now, pages)
    return pages or None


@router.post("")
async def fb_webhook_receive(request: Request):
    """FB 推送事件。leadgen → 存 leads 表。返回 200（FB 要求快速 200）。

    HMAC 遍历 active App secret 验签；无 active App 或验不过 → 403。
    页归属闸：page_id 不在该租户活跃令牌的页集合 → 忽略（旧主页订阅残留防混入；
    集合拉取失败 fail-open——不能把新页潜客挡死）。
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
                # form_id → tenant 反查（LeadFormTemplate.fb_form_id）——必须先于查重：
                # 曾在 tenant_id 赋值前引用它做去重查询 → UnboundLocalError → 500，
                # leadgen 推送全断（2026-09-08 全库审查 P0）
                tenant_id = None
                if form_id:
                    tpl = db.query(LeadFormTemplate).filter(
                        LeadFormTemplate.fb_form_id == str(form_id)
                    ).first()
                    tenant_id = tpl.tenant_id if tpl else None
                if not tenant_id:
                    logger.info(f"[FB Webhook] lead 无归属租户: lead_id={lid} form={form_id}")
                    continue
                if db.query(Lead).filter(Lead.lead_id == lid, Lead.tenant_id == tenant_id).first():
                    continue
                # 页归属闸：不在活跃令牌页集合 → 忽略（拉取失败 None → 放行）
                _known = _active_page_ids(db, tenant_id)
                if _known is not None and page_id and str(page_id) not in _known:
                    logger.info(f"[FB Webhook] 旧主页事件忽略: page={page_id} "
                                f"lead_id={lid} tenant={tenant_id}")
                    continue
                try:
                    db.add(Lead(
                        tenant_id=tenant_id, page_id=str(page_id) if page_id else None,
                        ad_id=str(ad_id) if ad_id else None,
                        form_id=str(form_id) if form_id else None,
                        lead_id=lid, field_data_json="[]",  # webhook 不带答案，sync 回填
                        created_time=created_time,
                    ))
                    db.commit()
                    logger.info(f"[FB Webhook] lead 存入: lead_id={lid} form={form_id} page={page_id} tenant={tenant_id}")
                except IntegrityError:
                    db.rollback()  # lead_id 重复（FB 并发重推），幂等跳过
                    logger.info(f"[FB Webhook] lead 重复跳过: lead_id={lid}")
    except Exception as e:
        logger.exception(f"[FB Webhook] 处理异常: {e}")
        db.rollback()
        return Response(content="EVENT_RECEIVED", status_code=500)  # 让 FB 重推（已 commit 的 lead 被 lead_id 去重跳过，幂等）
    finally:
        db.close()
    return Response(content="EVENT_RECEIVED", status_code=200)
