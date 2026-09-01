"""TikTok OAuth 连接：start（跳 TK 授权页）+ callback（换 token + 凭证/账户原子入库）。

照 fb_oauth 模式：callback 公开端点（TK 跳回无 JWT）→ SuperSessionLocal +
HMAC-signed state 恢复 tenant 上下文。TK 无 PKCE，state 防 CSRF 足够。

TK 差异：auth_code 10 分钟有效、换 token GET、一个 token 带多 advertiser
（/oauth2/advertiser/get/ 全列表，全部入库 accounts.platform='tt'）。

App 配置来源：系统级 tt_apps（超管 POST /tt/apps 配，secret 加密存）；
未配置时环境变量 TT_APP_ID/TT_APP_SECRET 兜底。
"""
import html
import json
import time
import base64
import hmac
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.database import get_db, SuperSessionLocal
from ..core.deps import CurrentUser, require_permission
from ..core.encryption import encrypt
from ..core.tt_client import TtClient, TtApiError, TT_AUTH_PORTAL
from ..core.log_utils import new_trace_id
from ..models.fb import Account
from ..models.tt import TtCredential, AccountTtCredential, TtApp
from ..services.tt_token_refresh import resolve_tt_app, refresh_credential, _fail_credential

router = APIRouter(prefix="/tt", tags=["tt"])
logger = logging.getLogger("toveads.tt_oauth")

STATE_TTL = 600
FRONTEND_URL = settings.frontend_base_url


# ── state 签发/验签（同 fb_oauth：payload.sig，jwt_secret HMAC）──

def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _sign_state(payload: dict) -> str:
    import json as _json
    raw = _json.dumps(payload, separators=(",", ":")).encode()
    sig = hmac.new(settings.jwt_secret.encode(), raw, hashlib.sha256).digest()
    return _b64u(raw) + "." + _b64u(sig)


def _verify_state(state: str) -> dict | None:
    import json as _json
    try:
        payload_b64, sig_b64 = state.split(".")
        raw = base64.urlsafe_b64decode(payload_b64 + "==")
        sig = base64.urlsafe_b64decode(sig_b64 + "==")
        expected = hmac.new(settings.jwt_secret.encode(), raw, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload = _json.loads(raw)
        if time.time() - payload.get("ts", 0) > STATE_TTL:
            return None
        return payload
    except Exception:
        return None


def _done_page(ok: bool, msg: str = ""):
    """OAuth 完成页（公开、免登录），样式同 fb_oauth。"""
    if ok:
        logger.info("[TT OAuth callback] 成功")
    else:
        logger.error("[TT OAuth callback] 失败: %s", msg or "(no detail)")
    icon, color = ("✓", "#30d488") if ok else ("✗", "#ff5757")
    title = "授权成功" if ok else "授权失败"
    detail = "TikTok 令牌已导入，可以关闭此页面。" if ok else (msg or "请重试。")
    css = ("body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#0e1117;"
           "font-family:-apple-system,system-ui,sans-serif;color:#e6e6e6}"
           ".c{background:#1a1d24;border:1px solid #2a2d34;border-radius:12px;padding:36px 44px;text-align:center;max-width:420px}"
           ".i{font-size:42px;color:" + color + ";margin-bottom:10px}"
           "h1{font-size:18px;margin:0 0 8px;font-weight:600}"
           ".d{color:#9aa0a6;font-size:14px;line-height:1.6;margin:0 0 18px;word-break:break-word}"
           ".a{color:#0a84ff;font-size:13px;text-decoration:none}.a:hover{text-decoration:underline}")
    return HTMLResponse(
        "<!doctype html><html lang='zh'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>TikTok " + title + "</title><style>" + css + "</style></head><body>"
        "<div class='c'><div class='i'>" + icon + "</div><h1>" + title + "</h1>"
        "<p class='d'>" + html.escape(detail) + "</p>"
        "<a class='a' href='" + FRONTEND_URL + "/#/tokens'>返回令牌管理 →</a></div></body></html>"
    )


def _iso(dt) -> str | None:
    """datetime → ISO Z 串（前端 new Date 直接解析）。"""
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@router.get("/oauth/start")
def tt_oauth_start(app_pk: int = 0,
                   user: CurrentUser = Depends(require_permission("ads.create")),
                   db: Session = Depends(get_db)):
    """生成 TikTok 授权 URL（前端拿到 url 后 window.location 跳转）。
    app_pk=指定 tt_apps 行（从 App 卡片发起，照 FB 模式）；0=第一行（兼容旧入口）。
    scope 不指定 = 授权 App 在开发者后台申请的全部 scope。"""
    sdb = SuperSessionLocal()
    try:
        app_id = ""
        if app_pk:
            row = sdb.query(TtApp).filter(TtApp.id == app_pk).first()
            if not row:
                raise HTTPException(404, "TikTok App 不存在")
            app_id = row.app_id
        if not app_id:
            app_cfg = resolve_tt_app(sdb)
            if not app_cfg:
                raise HTTPException(400, "尚未配置 TikTok App（超管在令牌页 TikTok 分区配置，或设 TT_APP_ID/TT_APP_SECRET）")
            app_id = app_cfg[0]
        state = _sign_state({
            "uid": user.id, "tid": user.tenant_id, "ts": int(time.time()),
            "apk": app_pk or 0,
        })
    finally:
        sdb.close()
    redirect_uri = f"{settings.public_base_url}/tt/oauth/callback"
    params = {
        "app_id": app_id,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return {"url": f"{TT_AUTH_PORTAL}/auth?{urlencode(params)}"}


@router.get("/oauth/callback")
def tt_oauth_callback(request: Request):
    """TK 授权后回调（公开，无 JWT）。验 state → auth_code 换 token → advertiser 入库 → 完成页。
    凭证 + 账户 + 关联行同一事务一次 commit（轮换出的 refresh_token 原子落库）。"""
    p = request.query_params
    if p.get("error"):
        return _done_page(False, p.get("error_description", p.get("error", "denied")))
    auth_code = p.get("auth_code", "") or p.get("code", "")
    state = _verify_state(p.get("state", ""))
    if not auth_code or not state:
        return _done_page(False, "state 无效或过期，请重试")

    tenant_id, uid = state["tid"], state["uid"]
    db = SuperSessionLocal()
    try:
        # 按 state 记录的 app_pk 选 App（从哪个卡片发起就用哪个的 secret 换码）
        apk = int(state.get("apk") or 0)
        if apk:
            row = db.query(TtApp).filter(TtApp.id == apk).first()
            if not row:
                return _done_page(False, "TikTok App 已被删除，请重新从令牌页发起连接")
            from ..core.encryption import decrypt as _dec
            app_id, secret = row.app_id, _dec(row.app_secret_enc)
        else:
            app_cfg = resolve_tt_app(db)
            if not app_cfg:
                return _done_page(False, "TikTok App 未配置")
            app_id, secret = app_cfg

        try:
            tok = TtClient.exchange_auth_code(app_id, secret, auth_code)
        except TtApiError as e:
            return _done_page(False, f"授权码交换失败：{e.friendly}")
        access_token = tok.get("access_token") or ""
        refresh_token = tok.get("refresh_token") or ""
        if not access_token or not refresh_token:
            return _done_page(False, "授权响应缺少 token 字段")

        # advertiser 列表（一个 token 带多 advertiser）
        try:
            adv_list = TtClient.get_authorized_advertisers(access_token, app_id)
        except TtApiError:
            adv_list = []
        adv_ids = [str(a.get("advertiser_id")) for a in adv_list if a.get("advertiser_id")]
        if not adv_ids:
            adv_ids = [str(x) for x in (tok.get("advertiser_ids") or [])]
        name_map = {str(a.get("advertiser_id")): (a.get("name") or "")
                    for a in adv_list}
        if not adv_ids:
            return _done_page(False, "该授权未关联任何广告账户（advertiser 为空）")
        primary = adv_ids[0]

        scope_raw = tok.get("scope")
        if isinstance(scope_raw, str):
            scopes = json.dumps([s.strip() for s in scope_raw.split(",") if s.strip()])
        elif isinstance(scope_raw, list):
            scopes = json.dumps(scope_raw)
        else:
            scopes = None

        now = datetime.now(timezone.utc)
        try:
            access_ttl = int(tok.get("expires_in") or 86400)
        except (TypeError, ValueError):
            access_ttl = 86400
        try:
            refresh_ttl = int(tok.get("refresh_token_expires_in") or 31536000)
        except (TypeError, ValueError):
            refresh_ttl = 31536000

        # 凭证 upsert（tenant + 主 advertiser 去重；重新授权=覆盖更新轮换 token）
        cred = db.query(TtCredential).filter(
            TtCredential.tenant_id == tenant_id,
            TtCredential.advertiser_id == primary,
        ).first()
        if cred:
            cred.alias = name_map.get(primary) or cred.alias
            cred.app_id = app_id
            cred.owner_user_id = cred.owner_user_id or uid
            cred.access_token_enc = encrypt(access_token)
            cred.refresh_token_enc = encrypt(refresh_token)
            cred.expires_at = now + timedelta(seconds=access_ttl)
            cred.refresh_expires_at = now + timedelta(seconds=refresh_ttl)
            cred.token_source = "oauth"
            cred.status = "active"
            cred.scopes = scopes or cred.scopes
            cred.last_refreshed_at = now
            cred.consecutive_fails = 0
        else:
            cred = TtCredential(
                tenant_id=tenant_id, owner_user_id=uid,
                alias=name_map.get(primary) or f"TikTok {primary}",
                app_id=app_id, advertiser_id=primary,
                access_token_enc=encrypt(access_token),
                refresh_token_enc=encrypt(refresh_token),
                expires_at=now + timedelta(seconds=access_ttl),
                refresh_expires_at=now + timedelta(seconds=refresh_ttl),
                token_source="oauth", status="active", scopes=scopes,
                last_refreshed_at=now, consecutive_fails=0,
            )
            db.add(cred)
        db.flush()

        # 账户 upsert（platform='tt'；已存在行只补平台绑定，不动纳管状态/名字）
        for adv_id in adv_ids:
            acc = db.query(Account).filter(
                Account.tenant_id == tenant_id, Account.act_id == adv_id
            ).first()
            if acc:
                # 不翻转已有账户的 platform：FB/TT act_id 空间独立但理论上可撞，
                # 翻转会把 FB 账户的路由切到 TT（红线：不影响 FB）。只补 TT 侧绑定。
                acc.tt_credential_id = cred.id
                if not acc.name or acc.name == adv_id:
                    acc.name = name_map.get(adv_id) or acc.name
            else:
                # 铁律「账户只显式导入才纳管」（同 FB 侧 5de8449）：授权只建行可见可载入，
                # is_managed=False；纳管走显式导入端点
                db.add(Account(
                    tenant_id=tenant_id, act_id=adv_id,
                    name=name_map.get(adv_id) or adv_id,
                    platform="tt", tt_credential_id=cred.id,
                    is_managed=False,
                ))
        db.flush()

        # 多令牌关联行（account_tt_credentials，幂等补齐）
        rows = db.query(Account).filter(
            Account.tenant_id == tenant_id, Account.act_id.in_(adv_ids)
        ).all()
        for acc in rows:
            link = db.query(AccountTtCredential).filter(
                AccountTtCredential.account_id == acc.id,
                AccountTtCredential.tt_credential_id == cred.id,
            ).first()
            if not link:
                db.add(AccountTtCredential(
                    tenant_id=tenant_id, account_id=acc.id,
                    tt_credential_id=cred.id, status="active", priority=0,
                ))
        db.commit()  # 凭证+账户+关联 单事务原子落库
        return _done_page(True)
    except Exception as e:
        db.rollback()
        logger.error("[TT OAuth callback] 异常: %s", repr(e)[:500])
        return _done_page(False, "授权流程异常，请重试；若持续失败请联系管理员查看日志。")
    finally:
        db.close()


@router.get("/credentials")
def list_tt_credentials(user: CurrentUser = Depends(require_permission("ads.read")),
                        db: Session = Depends(get_db)):
    """列出 TikTok 凭证（令牌页 TT 分区；token 本体永不外泄）。"""
    creds = db.query(TtCredential).filter(
        TtCredential.tenant_id == user.tenant_id
    ).order_by(TtCredential.created_at.desc()).all()
    out = []
    for c in creds:
        account_count = db.query(AccountTtCredential).filter(
            AccountTtCredential.tt_credential_id == c.id,
            AccountTtCredential.status == "active",
        ).count()
        scopes = None
        if c.scopes:
            try:
                scopes = json.loads(c.scopes)
            except (ValueError, TypeError):
                scopes = None
        out.append({
            "id": c.id,
            "alias": c.alias,
            "app_id": c.app_id,
            "advertiser_id": c.advertiser_id,
            "status": c.status,
            "token_source": c.token_source or "oauth",
            "consecutive_fails": c.consecutive_fails or 0,
            "expires_at": _iso(c.expires_at),
            "refresh_expires_at": _iso(c.refresh_expires_at),
            "last_refreshed_at": _iso(c.last_refreshed_at),
            "created_at": _iso(c.created_at),
            "scopes": scopes,
            "account_count": account_count,
        })
    return out


class TtAppIn(BaseModel):
    app_id: str
    app_secret: str
    name: str = ""


@router.get("/apps")
def list_tt_apps(user: CurrentUser = Depends(require_permission("ads.read")),
                 db: Session = Depends(get_db)):
    """系统级 TT App 列表（照 /fb/apps 形状：id/name/app_id/is_system；secret 不返回）。
    所有用户可见——从 App 卡片发起连接（FB 同款流）。env 兜底伪行 id=0 不可编辑。"""
    import os
    sdb = SuperSessionLocal()
    try:
        rows = sdb.query(TtApp).filter(
            TtApp.tenant_id.is_(None), TtApp.is_system.is_(True)
        ).order_by(TtApp.id).all()
        out = [{"id": r.id, "name": r.name or r.app_id, "app_id": r.app_id,
                "is_system": True, "source": "db"} for r in rows]
        if not out:
            env_id = (os.environ.get("TT_APP_ID") or "").strip()
            if env_id:
                out = [{"id": 0, "name": env_id, "app_id": env_id,
                        "is_system": True, "source": "env"}]
        return out
    finally:
        sdb.close()


@router.post("/apps")
def upsert_tt_app(body: TtAppIn,
                  user: CurrentUser = Depends(require_permission("ads.create")),
                  db: Session = Depends(get_db)):
    """添加/更新系统级 TT App（超管；按 app_id 去重=更新 secret/name）。"""
    if not getattr(user, "is_superadmin", False):
        raise HTTPException(403, "仅超管可配置 TikTok App")
    if not body.app_id.strip() or not body.app_secret.strip():
        raise HTTPException(400, "app_id 与 app_secret 均不能为空")
    sdb = SuperSessionLocal()
    try:
        app = sdb.query(TtApp).filter(
            TtApp.tenant_id.is_(None), TtApp.is_system.is_(True),
            TtApp.app_id == body.app_id.strip(),
        ).first()
        if app:
            app.app_secret_enc = encrypt(body.app_secret.strip())
            if body.name.strip():
                app.name = body.name.strip()
        else:
            sdb.add(TtApp(
                tenant_id=None, app_id=body.app_id.strip(),
                name=body.name.strip() or body.app_id.strip(),
                app_secret_enc=encrypt(body.app_secret.strip()),
                is_system=True,
            ))
        sdb.commit()
        return {"saved": True, "app_id": body.app_id.strip()}
    finally:
        sdb.close()


@router.delete("/apps/{app_pk}")
def delete_tt_app(app_pk: int,
                  user: CurrentUser = Depends(require_permission("ads.create")),
                  db: Session = Depends(get_db)):
    """删除系统级 TT App（超管）。有 active 凭证引用该 app_id 时拒删（刷新会失效）。"""
    if not getattr(user, "is_superadmin", False):
        raise HTTPException(403, "仅超管可删除 TikTok App")
    sdb = SuperSessionLocal()
    try:
        app = sdb.query(TtApp).filter(TtApp.id == app_pk).first()
        if not app:
            raise HTTPException(404, "TikTok App 不存在")
        from ..models.tt import TtCredential
        used = sdb.query(TtCredential).filter(
            TtCredential.status == "active", TtCredential.app_id == app.app_id
        ).count()
        if used:
            raise HTTPException(400, f"该 App 仍有 {used} 个有效令牌在使用，请先删除对应令牌")
        sdb.delete(app)
        sdb.commit()
        return {"deleted": True, "id": app_pk}
    finally:
        sdb.close()


# ── TT 账户显式纳管（铁律「账户只显式导入才纳管」，OAuth 只建 is_managed=False 行）──
class TtImportIn(BaseModel):
    act_ids: list[str] = []


@router.get("/loadable-accounts")
def tt_loadable_accounts(user: CurrentUser = Depends(require_permission("ads.read")),
                         db: Session = Depends(get_db)):
    """列本租户可导入的 TT 账户（OAuth 授权时已建行、尚未纳管的）。"""
    rows = db.query(Account).filter(
        Account.tenant_id == user.tenant_id,
        Account.platform == "tt",
        Account.is_managed == False,  # noqa: E712
    ).order_by(Account.id.desc()).all()
    return [{"act_id": a.act_id, "name": a.name or a.act_id,
             "tt_credential_id": a.tt_credential_id} for a in rows]


@router.post("/import")
def tt_import(body: TtImportIn, user: CurrentUser = Depends(require_permission("ads.create")),
              db: Session = Depends(get_db)):
    """TT 账户显式纳管（is_managed=True）。只收 OAuth 授权过的账户行——未授权的
    act_id 一律 not_found（不做任何 API 侧隐式拉取）。重复导入=恢复纳管。"""
    from ..core.log_utils import write_log, new_trace_id
    cleaned = []
    for raw in body.act_ids:
        v = str(raw).replace("act_", "").replace("ACT_", "").strip()
        if v:
            cleaned.append(v)
    cleaned = list(dict.fromkeys(cleaned))  # 去重保序
    imported, skipped, not_found = [], 0, []
    for aid in cleaned:
        acc = db.query(Account).filter(
            Account.tenant_id == user.tenant_id,
            Account.act_id == aid,
            Account.platform == "tt",
        ).first()
        if not acc:
            not_found.append(aid)
            continue
        if acc.is_managed:
            skipped += 1
            continue
        acc.is_managed = True
        imported.append(aid)
    if imported:
        write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
                  actor_user_id=user.id, target_type="account", target_id="tt_batch",
                  action_type="import", source="user", result="success",
                  metadata={"platform": "tt", "imported": imported})
    db.commit()
    return {"imported": imported, "skipped_existing": skipped,
            "not_found": not_found, "total": len(cleaned)}


# ── TT 令牌生命周期（照 fb.py rename/delete_credential 模式）──

class TtRenameIn(BaseModel):
    alias: str = ""


@router.post("/credentials/{cred_id}/rename")
def rename_tt_credential(cred_id: int, body: TtRenameIn,
                         user: CurrentUser = Depends(require_permission("ads.create")),
                         db: Session = Depends(get_db)):
    """修改 TikTok 令牌名称。"""
    cred = db.query(TtCredential).filter(
        TtCredential.tenant_id == user.tenant_id,
        TtCredential.id == cred_id,
    ).first()
    if not cred:
        raise HTTPException(404, "TikTok 令牌不存在")
    cred.alias = body.alias.strip() or None
    db.commit()
    return {"id": cred_id, "alias": cred.alias}


@router.delete("/credentials/{cred_id}")
def delete_tt_credential(cred_id: int,
                         user: CurrentUser = Depends(require_permission("ads.create")),
                         db: Session = Depends(get_db)):
    """删除 TikTok 令牌（解绑关联账户 + 删多令牌关联行 + 删凭证行；账户不删）。
    与 FB delete_credential 同构；账户行保留（platform 不变），tt_credential_id 置空。"""
    cred = db.query(TtCredential).filter(
        TtCredential.tenant_id == user.tenant_id,
        TtCredential.id == cred_id,
    ).first()
    if not cred:
        raise HTTPException(404, "TikTok 令牌不存在")
    # 账户主令牌置空（账户不删、纳管状态不变——重新授权后可再绑）
    db.query(Account).filter(
        Account.tenant_id == user.tenant_id,
        Account.tt_credential_id == cred_id,
    ).update({Account.tt_credential_id: None}, synchronize_session="fetch")
    # 删多令牌关联行（FK 阻止删凭证，同 FB "移除令牌不生效" 根因）
    db.query(AccountTtCredential).filter(
        AccountTtCredential.tt_credential_id == cred_id,
    ).delete(synchronize_session="fetch")
    db.delete(cred)
    db.commit()
    return {"deleted": True, "id": cred_id}


@router.post("/credentials/{cred_id}/refresh-now")
def tt_refresh_now(cred_id: int,
                   user: CurrentUser = Depends(require_permission("ads.create")),
                   db: Session = Depends(get_db)):
    """手动触发单凭证刷新（复用 cron 的 refresh_credential：轮换原子写回，不做任何改动）。
    失败走 _fail_credential 同款降级（计数/invalid/expired + 重新授权通知）。"""
    cred = db.query(TtCredential).filter(
        TtCredential.tenant_id == user.tenant_id,
        TtCredential.id == cred_id,
    ).first()
    if not cred:
        raise HTTPException(404, "TikTok 令牌不存在")
    if not cred.refresh_token_enc:
        raise HTTPException(400, "该凭证没有 refresh_token，请重新授权")
    # App 配置是系统级行（tenant_id NULL）——SuperSessionLocal 读（同 tt_oauth_start）。
    # 按凭证自己的 app_id 精确匹配（多 App 用错 secret 刷新必失败；无 app_id 回退第一行）
    sdb = SuperSessionLocal()
    try:
        app_cfg = resolve_tt_app(sdb, (cred.app_id or "").strip())
    finally:
        sdb.close()
    if not app_cfg:
        raise HTTPException(400, "尚未配置 TikTok App（超管在令牌页 TikTok 分区配置，或设 TT_APP_ID/TT_APP_SECRET）")
    app_id, secret = app_cfg
    try:
        refresh_credential(db, cred, app_id, secret)
    except TtApiError as e:
        _fail_credential(db, cred, user.tenant_id, new_trace_id(), e)
        raise HTTPException(502, f"刷新失败：{e.friendly}")
    except Exception as e:
        db.rollback()
        logger.error("[TT refresh-now] 凭证 %s 异常: %s", cred_id, repr(e)[:300])
        raise HTTPException(502, "刷新异常，请稍后重试")
    return {"ok": True, "id": cred.id, "status": cred.status,
            "expires_at": _iso(cred.expires_at),
            "refresh_expires_at": _iso(cred.refresh_expires_at),
            "last_refreshed_at": _iso(cred.last_refreshed_at)}
