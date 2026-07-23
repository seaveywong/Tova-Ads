"""FB OAuth 连接 App：start（跳 FB 授权页）+ callback（换 token + 建凭证）。

callback 是公开端点（FB 跳转回来无 JWT）→ 仿 landing_events 用 SuperSessionLocal
+ HMAC-signed state 恢复 tenant 上下文（state 编码 uid/tid/app_pk/ts/nonce，用 jwt_secret 签）。
"""
import json, hmac, hashlib, base64, secrets, time
from datetime import datetime, timezone
from urllib.parse import urlencode, quote
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from ..core.config import settings
from ..core.database import get_db, SuperSessionLocal
from ..core.deps import CurrentUser, require_permission
from ..core.encryption import encrypt, decrypt
from ..core.fb_client import FbClient, GRAPH_BASE, GRAPH_VERSION
from ..models.fb import FbCredential
from .fb_apps import FbApp

router = APIRouter(prefix="/fb/oauth", tags=["fb-oauth"])

# 申请的 8 个 scope（必须与 FB App Review 提交一致）
OAUTH_SCOPES = "ads_management,ads_read,read_insights,business_management,pages_show_list,pages_manage_ads,pages_read_engagement,pages_manage_metadata"
STATE_TTL = 600  # state 有效期 10 分钟
FRONTEND_URL = "https://tovaads.com"


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _sign_state(payload: dict) -> str:
    """JSON payload + HMAC-SHA256(jwt_secret) → 'payload.sig'（CSRF 防伪 + 携带 tenant 上下文）。"""
    raw = json.dumps(payload, separators=(",", ":")).encode()
    sig = hmac.new(settings.jwt_secret.encode(), raw, hashlib.sha256).digest()
    return _b64u(raw) + "." + _b64u(sig)


def _verify_state(state: str) -> dict | None:
    """验签 + ts 新鲜。失败返 None。"""
    try:
        payload_b64, sig_b64 = state.split(".")
        raw = base64.urlsafe_b64decode(payload_b64 + "==")
        sig = base64.urlsafe_b64decode(sig_b64 + "==")
        expected = hmac.new(settings.jwt_secret.encode(), raw, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(raw)
        if time.time() - payload.get("ts", 0) > STATE_TTL:
            return None
        return payload
    except Exception:
        return None


def _redirect(ok: bool, msg: str = ""):
    status = "ok" if ok else "fail"
    q = f"oauth={status}" + (f"&msg={quote(msg, safe='')}" if msg else "")
    return RedirectResponse(f"{FRONTEND_URL}/#/tokens?{q}", status_code=302)


@router.get("/start")
def oauth_start(app_pk: int, user: CurrentUser = Depends(require_permission("ads.create")),
                db: Session = Depends(get_db)):
    """生成 FB 授权 URL（带 HMAC-signed state）。前端拿到 url 后 window.location 跳转。"""
    app = db.query(FbApp).filter(FbApp.id == app_pk, FbApp.status == "active").first()
    if not app:
        raise HTTPException(404, "App 不存在或已停用")
    state = _sign_state({
        "uid": user.id, "tid": user.tenant_id, "apk": app.id,
        "nonce": secrets.token_urlsafe(8), "ts": int(time.time()),
    })
    redirect_uri = f"{settings.public_base_url}/fb/oauth/callback"
    params = {
        "client_id": app.app_id,
        "redirect_uri": redirect_uri,
        "scope": OAUTH_SCOPES,
        "state": state,
        "response_type": "code",
    }
    url = f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth?{urlencode(params)}"
    return {"url": url}


@router.get("/callback")
def oauth_callback(request: Request):
    """FB 授权后回调（公开，无 JWT）。验 state → 换 code→short→long → 建凭证 → 跳前端。"""
    p = request.query_params
    if p.get("error"):
        return _redirect(False, p.get("error_description", p.get("error", "denied")))
    code, state_str = p.get("code", ""), p.get("state", "")
    state = _verify_state(state_str)
    if not code or not state:
        return _redirect(False, "state 无效或过期，请重试")

    tenant_id, app_pk = state["tid"], state["apk"]
    db = SuperSessionLocal()
    try:
        app = db.query(FbApp).filter(FbApp.id == app_pk, FbApp.status == "active").first()
        if not app:
            return _redirect(False, "App 不存在")
        app_secret = decrypt(app.app_secret_enc)
        redirect_uri = f"{settings.public_base_url}/fb/oauth/callback"

        # code → short-lived token
        r1 = httpx.get(f"{GRAPH_BASE}/oauth/access_token", params={
            "client_id": app.app_id, "redirect_uri": redirect_uri,
            "client_secret": app_secret, "code": code,
        }, timeout=15)
        j1 = r1.json()
        short_tok = j1.get("access_token") if r1.status_code == 200 else None
        if not short_tok:
            return _redirect(False, j1.get("error", {}).get("message", "code 交换失败"))

        # short → long-lived（~60 天）。换不到就退回 short
        r2 = httpx.get(f"{GRAPH_BASE}/oauth/access_token", params={
            "grant_type": "fb_exchange_token", "client_id": app.app_id,
            "client_secret": app_secret, "fb_exchange_token": short_tok,
        }, timeout=15)
        long_tok = r2.json().get("access_token") or short_tok

        # 建凭证（复用 fb.py 逻辑：/me + debug_token + encrypt + 按 tenant+fb_user_id 去重）
        fb = FbClient(long_tok)
        try:
            me = fb.me()
        except Exception:
            return _redirect(False, "令牌无效（/me 失败）")
        perm_snapshot = None
        try:
            debug = fb.debug_token()
            perm_snapshot = json.dumps({
                "scopes": debug.get("data", {}).get("scopes", []),
                "app_id": debug.get("data", {}).get("app_id"),
                "is_valid": debug.get("data", {}).get("is_valid"),
            })
        except Exception:
            pass

        existing = db.query(FbCredential).filter(
            FbCredential.tenant_id == tenant_id, FbCredential.fb_user_id == me.get("id")
        ).first()
        if existing:
            existing.access_token_enc = encrypt(long_tok)
            existing.status = "active"
            existing.token_source = "oauth"
            existing.permission_snapshot = perm_snapshot or existing.permission_snapshot
            existing.consecutive_fails = 0
            existing.last_verified_at = datetime.now(timezone.utc)
        else:
            db.add(FbCredential(
                tenant_id=tenant_id, type="user_token", alias=me.get("name"),
                access_token_enc=encrypt(long_tok), fb_user_id=me.get("id"),
                fb_user_name=me.get("name"), status="active", token_type="operate",
                token_source="oauth", permission_snapshot=perm_snapshot,
                consecutive_fails=0, last_verified_at=datetime.now(timezone.utc),
            ))
        db.commit()
        # SET LOCAL app.tenant_id（SuperSessionLocal bypass RLS 但 reassociate 需要）
        from sqlalchemy import text
        db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        try:
            from ..core.fb_tokens import reassociate_orphan_accounts
            reassociate_orphan_accounts(db, tenant_id)
            db.commit()
        except Exception:
            pass
        return _redirect(True)
    except Exception as e:
        return _redirect(False, str(e)[:80])
    finally:
        db.close()
