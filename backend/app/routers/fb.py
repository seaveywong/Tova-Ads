"""FB 集成路由：绑定凭证 / 拉资产 / 导入账户 / 列账户 / 令牌管理。

所有 FB 调用走 fb_client（总则4），凭证加密存（doc 01 D 节）。
"""
import json
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from ..core.database import get_db, get_system_db, SuperSessionLocal
from ..core.deps import CurrentUser, require_permission, require_superadmin
from ..core.i18n import req_locale, L
from ..core.encryption import encrypt, decrypt
from ..core.fb_client import FbClient, FbApiError
from ..core.tt_client import TtApiError
from ..models.fb import FbCredential, Account, AccountFbCredential
from ..schemas.fb import StoreCredentialIn, FbCredentialOut, ImportAccountsIn

router = APIRouter(prefix="/fb", tags=["fb"])

# assets-summary 1h 进程内缓存 {tenant_id: (built_at, data, cred_sig)}
_ASSETS_SUMMARY_CACHE: dict = {}


def _cred_to_dict(c: FbCredential, db: Session = None) -> dict:
    """令牌 → 前端展示 dict（完整字段 + 关联账户数）。
    account_count = 候选池覆盖数（account_fb_credentials，含多令牌轮换场景），不是旧的主令牌数。"""
    account_count = 0
    if db:
        from ..models.fb import AccountFbCredential
        account_count = db.query(AccountFbCredential).filter(
            AccountFbCredential.fb_credential_id == c.id,
            AccountFbCredential.status == "active",
        ).count()
    perm = None
    if c.permission_snapshot:
        try:
            perm = json.loads(c.permission_snapshot)
        except Exception:
            perm = None
    return {
        "id": c.id,
        "alias": c.alias,
        "status": c.status,
        "fb_user_name": c.fb_user_name,
        "fb_user_id": c.fb_user_id,
        "token_type": c.token_type or "user",
        "token_source": c.token_source or "manual",
        "permission_snapshot": perm,
        "consecutive_fails": c.consecutive_fails or 0,
        "last_verified_at": str(c.last_verified_at) if c.last_verified_at else None,
        "account_count": account_count,
    }


@router.post("/credentials", response_model=FbCredentialOut)
def store_credential(
    body: StoreCredentialIn,
    user: CurrentUser = Depends(require_permission("ads.create")),
    db: Session = Depends(get_db),
):
    """存 FB 凭证 → 先用 token 调 FB /me 校验 → debug_token 拉权限 → 加密存库。"""
    fb = FbClient(body.access_token)
    try:
        me = fb.me()
    except FbApiError as e:
        raise HTTPException(400, e.friendly)

    # debug_token 拉权限快照
    perm_snapshot = None
    debug = None
    try:
        debug = fb.debug_token()
        perm_snapshot = json.dumps({
            "scopes": debug.get("data", {}).get("scopes", []),
            "app_id": debug.get("data", {}).get("app_id"),
            "is_valid": debug.get("data", {}).get("is_valid"),
            "expires_at": debug.get("data", {}).get("data_access_expires_at"),
        })
    except Exception:
        pass  # debug_token 失败不阻断存储

    # 长效令牌交换（手动粘贴常是 ~1-2h 短效，导入即死）。对齐 OAuth 流程：
    # 用 debug_token 的 app_id 找我们库里的 App secret 才能换；换失败存原值不阻断。
    stored_token = body.access_token
    try:
        _app_id = str((debug or {}).get("data", {}).get("app_id") or "")
        if _app_id:
            from ..models.fb_app import FbApp
            _app = db.query(FbApp).filter(
                FbApp.app_id == _app_id, FbApp.status == "active").first()
            if _app and _app.app_secret_enc:
                import httpx
                from ..core.fb_client import GRAPH_BASE
                r = httpx.get(f"{GRAPH_BASE}/oauth/access_token", params={
                    "grant_type": "fb_exchange_token",
                    "client_id": _app_id,
                    "client_secret": decrypt(_app.app_secret_enc),
                    "fb_exchange_token": body.access_token,
                }, timeout=30)
                _nt = (r.json() or {}).get("access_token")
                if _nt:
                    stored_token = _nt
    except Exception:
        pass  # 交换失败（无 secret / 网络错）存原值

    # 去重：同 tenant + 同 fb_user_id + 同 source → 更新，不重复建
    existing = db.query(FbCredential).filter(
        FbCredential.tenant_id == user.tenant_id,
        FbCredential.fb_user_id == me.get("id"),
    ).first()

    if existing:
        existing.access_token_enc = encrypt(stored_token)
        existing.alias = body.alias or existing.alias
        existing.status = "active"
        # 请求显式带了 token_type 才覆盖；未传保留旧值（schema 默认 "user" 会把 manage 静默降级）
        _tt_set = getattr(body, "_token_type_set", False)
        existing.token_type = ((body.token_type if _tt_set and body.token_type else None) or existing.token_type or "user")
        existing.token_source = body.token_source
        existing.permission_snapshot = perm_snapshot or existing.permission_snapshot
        existing.consecutive_fails = 0
        existing.last_verified_at = datetime.now(timezone.utc)
        db.commit()
        result = FbCredentialOut(id=existing.id, type=existing.type, status=existing.status,
                                 alias=existing.alias, fb_user_name=existing.fb_user_name)
    else:
        cred = FbCredential(
            tenant_id=user.tenant_id,
            type=body.type,
            alias=body.alias or None,
            access_token_enc=encrypt(stored_token),
            fb_user_id=me.get("id"),
            fb_user_name=me.get("name"),
            status="active",
            token_type=body.token_type or "user",
            token_source=body.token_source,
            permission_snapshot=perm_snapshot,
            consecutive_fails=0,
            last_verified_at=datetime.now(timezone.utc),
        )
        db.add(cred)
        db.flush()
        result = FbCredentialOut(id=cred.id, type=cred.type, status=cred.status,
                                 alias=cred.alias, fb_user_name=cred.fb_user_name)
        db.commit()

    # token-add/换: 即时重绑孤儿（新 token 可能覆盖既有孤儿账户，不等 2h watchdog）
    try:
        from ..core.fb_tokens import reassociate_orphan_accounts
        reassociate_orphan_accounts(db, user.tenant_id)
    except Exception:
        pass
    return result


class RenameIn(BaseModel):
    alias: str = ""


class AccountGroupIn(BaseModel):
    act_ids: list[str]
    group_label: str = ""

@router.post("/credentials/{cred_id}/rename")
def rename_credential(
    cred_id: int,
    body: RenameIn,
    user: CurrentUser = Depends(require_permission("ads.create")),
    db: Session = Depends(get_db),
):
    """修改令牌名称。"""
    cred = db.query(FbCredential).filter(
        FbCredential.tenant_id == user.tenant_id,
        FbCredential.id == cred_id,
    ).first()
    if not cred:
        raise HTTPException(404, "令牌不存在")
    cred.alias = body.alias.strip() or None
    db.commit()
    return {"id": cred_id, "alias": cred.alias}


@router.get("/credentials")
def list_credentials(user: CurrentUser = Depends(require_permission("ads.read")), db: Session = Depends(get_db)):
    """列出令牌（完整字段 + 关联账户数，供前端令牌管理页面）。"""
    creds = db.query(FbCredential).filter(FbCredential.tenant_id == user.tenant_id).all()
    return [_cred_to_dict(c, db) for c in creds]


@router.delete("/credentials/{cred_id}")
def delete_credential(
    cred_id: int,
    user: CurrentUser = Depends(require_permission("ads.create")),
    db: Session = Depends(get_db),
):
    """删除令牌（解绑关联账户 + 删凭证行）。"""
    cred = db.query(FbCredential).filter(
        FbCredential.tenant_id == user.tenant_id,
        FbCredential.id == cred_id,
    ).first()
    if not cred:
        raise HTTPException(404, "令牌不存在")
    # 解绑关联账户（fb_credential_id 置空，账户不删）
    db.query(Account).filter(
        Account.tenant_id == user.tenant_id,
        Account.fb_credential_id == cred_id,
    ).update({Account.fb_credential_id: None}, synchronize_session="fetch")
    # 删多令牌关联行（否则 FK 阻止删 FbCredential —— 这是"移除令牌不生效"的根因）
    db.query(AccountFbCredential).filter(
        AccountFbCredential.fb_credential_id == cred_id,
    ).delete(synchronize_session="fetch")
    db.delete(cred)
    db.commit()
    # token-delete: 即时重绑孤儿到其他可用 token（不等 2h watchdog）
    try:
        from ..core.fb_tokens import reassociate_orphan_accounts
        reassociate_orphan_accounts(db, user.tenant_id)
    except Exception:
        pass
    return {"deleted": True, "id": cred_id}


@router.post("/credentials/{cred_id}/update-token")
def update_credential_token(
    cred_id: int,
    body: dict,
    user: CurrentUser = Depends(require_permission("ads.create")),
    db: Session = Depends(get_db),
):
    """更新令牌密钥（个人令牌过期后更换）。同 fb_user_id 会覆盖更新。"""
    new_token = (body.get("access_token") or "").strip()
    if not new_token:
        raise HTTPException(400, "access_token 不能为空")
    cred = db.query(FbCredential).filter(
        FbCredential.id == cred_id, FbCredential.tenant_id == user.tenant_id
    ).first()
    if not cred:
        raise HTTPException(404, "凭证不存在")
    # 验证新 token
    fb = FbClient(new_token)
    try:
        me = fb.me()
    except FbApiError as e:
        raise HTTPException(400, f"新令牌无效：{e.friendly}")
    # 拉权限快照
    perm_snapshot = cred.permission_snapshot
    try:
        debug = fb.debug_token()
        scopes = debug.get("data", {}).get("scopes", [])
        perm_snapshot = json.dumps({"scopes": scopes})
    except Exception:
        pass
    # 更新
    cred.access_token_enc = encrypt(new_token)
    cred.status = "active"
    cred.consecutive_fails = 0
    cred.last_verified_at = datetime.now(timezone.utc)
    cred.permission_snapshot = perm_snapshot
    from ..core.log_utils import write_log, new_trace_id
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, target_type="fb_credential", target_id=str(cred_id),
              action_type="update_token", source="user", result="success")
    db.commit()
    return {"ok": True, "fb_user_name": me.get("name", ""), "status": "active"}


@router.post("/credentials/{cred_id}/check")
def check_credential(
    cred_id: int,
    request: Request,
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """手动检测令牌有效性（debug_token + /me）→ 更新 status + permission_snapshot + last_verified_at。"""
    loc = req_locale(request)
    cred = db.query(FbCredential).filter(
        FbCredential.tenant_id == user.tenant_id,
        FbCredential.id == cred_id,
    ).first()
    if not cred:
        raise HTTPException(404, "令牌不存在")

    token = decrypt(cred.access_token_enc)
    fb = FbClient(token)
    result = {"id": cred_id, "was_valid": cred.status == "active", "now_valid": None, "detail": ""}

    try:
        # /me 快速验活
        me = fb.me()
        debug = fb.debug_token()
        is_valid = debug.get("data", {}).get("is_valid", False)
        scopes = debug.get("data", {}).get("scopes", [])
        app_id = debug.get("data", {}).get("app_id")

        cred.permission_snapshot = json.dumps({"scopes": scopes, "app_id": app_id, "is_valid": is_valid})
        cred.last_verified_at = datetime.now(timezone.utc)
        cred.consecutive_fails = 0

        if is_valid:
            cred.status = "active"
            result["now_valid"] = True
            result["detail"] = L(loc, "fb.checkOk", scopes=", ".join(scopes[:3]))
        else:
            cred.status = "expired"
            result["now_valid"] = False
            result["detail"] = L(loc, "fb.checkInvalid")

        db.commit()
    except FbApiError as e:
        cred.consecutive_fails = (cred.consecutive_fails or 0) + 1
        cred.last_verified_at = datetime.now(timezone.utc)
        # 临时错误豁免：未知/generic 可能是 FB 侧瞬时抽风，需连续 3 次才判死（单次不 expired）
        # rate_limited → 30min 冷却；network/unknown/generic → 连续 3 次升级 limited
        if e.category == "rate_limited":
            cred.status = "rate_limited"
            cred.cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=30)
        elif e.category in ("network", "unknown", "generic"):
            if cred.consecutive_fails >= 3:
                cred.status = "limited"
        else:
            cred.status = "expired"  # 明确错误（token 失效/权限/参数）直接判死
        db.commit()
        result["now_valid"] = cred.status == "active"
        result["detail"] = e.friendly
    except Exception as e:
        cred.consecutive_fails = (cred.consecutive_fails or 0) + 1
        cred.last_verified_at = datetime.now(timezone.utc)
        db.commit()
        result["now_valid"] = False
        result["detail"] = str(e)[:100]

    # 令牌失效 → 即时重绑关联账户到其他可用 token（不等 watchdog）
    if cred.status == "expired":
        try:
            from ..core.fb_tokens import reassociate_orphan_accounts
            reassociate_orphan_accounts(db, user.tenant_id)
        except Exception:
            pass
    return result


@router.get("/credentials/{cred_id}/accounts")
def list_credential_accounts(
    cred_id: int,
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """列出该令牌能管的广告账户（FB /me/adaccounts，per-token，展开行用）。"""
    cred = db.query(FbCredential).filter(
        FbCredential.tenant_id == user.tenant_id,
        FbCredential.id == cred_id,
    ).first()
    if not cred:
        raise HTTPException(404, "令牌不存在")

    token = decrypt(cred.access_token_enc)
    fb = FbClient(token)
    try:
        accounts = fb.get_ad_accounts()
    except FbApiError as e:
        raise HTTPException(400, e.friendly)

    return [{"account_id": a.get("account_id", ""), "name": a.get("name", ""),
             "currency": a.get("currency", "USD"), "timezone_name": a.get("timezone_name", "UTC")}
            for a in accounts]


@router.get("/credentials/{cred_id}/pages")
def list_credential_pages(
    cred_id: int,
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """列出该令牌能管理的主页。"""
    cred = db.query(FbCredential).filter(
        FbCredential.tenant_id == user.tenant_id,
        FbCredential.id == cred_id,
    ).first()
    if not cred:
        raise HTTPException(404, "令牌不存在")
    fb = FbClient(decrypt(cred.access_token_enc))
    try:
        pages = fb.get_pages()
    except FbApiError as e:
        raise HTTPException(400, e.friendly)
    return [{"id": p.get("id", ""), "name": p.get("name", ""),
             "category": p.get("category", ""), "fan_count": p.get("fan_count", 0)}
            for p in pages]


@router.get("/pages/{page_id}/posts")
def list_page_posts(
    page_id: str,
    user: CurrentUser = Depends(require_permission("ads.create")),
    db: Session = Depends(get_db),
):
    """列主页已发帖（用 page token 拉 published_posts）。供跟帖 Post Picker 选帖。"""
    from ..core.fb_tokens import iter_tenant_clients
    page_token = ""
    for _cred, fb in iter_tenant_clients(db, user.tenant_id):
        try:
            page_token = fb.get_page_access_token(page_id)
            if page_token:
                break
        except Exception:
            continue
    if not page_token:
        raise HTTPException(400, "拿不到主页 token（令牌不管该主页或缺 pages_manage_posts）")
    pfb = FbClient(page_token)
    try:
        posts = pfb.get_paged(f"{page_id}/published_posts", {
            "fields": "id,message,picture,created_time,permalink_url",
            "limit": 100,  # published_posts FB 上限 100（get_paged 默认 200 会 #100）
        })
    except FbApiError as e:
        raise HTTPException(400, e.friendly)
    out = []
    for p in posts:
        picture = p.get("picture") or ""
        out.append({
            "id": p.get("id", ""),
            "message": (p.get("message") or "")[:200],
            "picture": picture,
            "created_time": p.get("created_time", ""),
            "permalink_url": p.get("permalink_url", ""),
        })
    return {"posts": out}


class ResolvePostIn(BaseModel):
    q: str


def _local_resolve_post(db: Session, tenant_id: int, post_num: str):
    """本地 ads_cache 反查。零 FB 调用，秒回。
    支持：① 帖号后缀匹配 ad.creative.effective_object_story_id；
          ② 广告ID 匹配 ad.id → 取其 creative 的 post（用户常粘广告ID）。
    返 {page_id, post_id, source} 或 None。"""
    from ..models.ads_cache import AdsCache
    for row in db.query(AdsCache).filter(AdsCache.tenant_id == tenant_id).all():
        try:
            ads = json.loads(row.ads_json or "[]")
        except Exception:
            continue
        for ad in ads:
            cr = ad.get("creative")
            sid = ""
            if isinstance(cr, dict):
                sid = cr.get("effective_object_story_id") or ""
                if not sid and isinstance(cr.get("data"), list) and cr["data"]:
                    sid = (cr["data"][0] or {}).get("effective_object_story_id") or ""
            # ① 帖号匹配 effective_object_story_id（整串或末段）
            if sid and (sid == post_num or (sid.split("_")[-1] == post_num if "_" in sid else False)):
                page_id = sid.split("_", 1)[0] if "_" in sid else ""
                return {"page_id": page_id, "post_id": sid, "source": "local"}
            # ② 广告ID 匹配 ad.id → 取其 creative 的 post
            if str(ad.get("id", "")) == post_num and sid:
                return {"page_id": (sid.split("_", 1)[0] if "_" in sid else ""), "post_id": sid, "source": "local"}
    return None


def _content_from_creative(cr: dict) -> dict:
    """从 creative dict 提取 {message, headline, picture, cta_type, link, permalink_url}。
    cr 来自实时 GET /{creative_id}、ads_cache 的 creative 字段、或 FB 兜底的广告响应。模块级（resolve_post 也用）。"""
    spec = cr.get("object_story_spec") or {}
    ld = spec.get("link_data") or {}
    vd = spec.get("video_data") or {}
    cta = (ld.get("call_to_action") or vd.get("call_to_action") or cr.get("call_to_action") or {})
    cta_val = (cta.get("value") or {}) if isinstance(cta, dict) else {}
    msg = (ld.get("message") or vd.get("message") or "")
    headline = (ld.get("name") or vd.get("title") or "")
    picture = (cr.get("thumbnail_url") or vd.get("image_url") or ld.get("picture") or "")
    link = (ld.get("link") or cta_val.get("link") or "")
    return {"message": msg[:500], "headline": headline[:100], "picture": picture,
            "cta_type": (cta.get("type") or "") if isinstance(cta, dict) else "",
            "link": link, "permalink_url": ""}


def _clone_ad_settings(db: Session, tenant_id: int, post_id: str) -> dict:
    """从源广告(帖子所属的 ad)克隆 系列/广告组设置 供跟帖模板预填（"复用此帖铺放"=克隆广告）。
    返 {objective, bid_strategy, optimization_goal, billing_event, destination_type,
        audience_age_min/max/gender/countries/interests, manual_placement, placement_platforms/devices,
        facebook_positions} 或 {}。预算不克隆（币种换算复杂，留手动）。"""
    from ..models.ads_cache import AdsCache
    from ..core.fb_tokens import client_for_account, iter_tenant_clients
    post_suffix = post_id.split("_")[-1] if "_" in post_id else post_id
    src = None  # (act_id, adset_id, campaign_id)
    for row in db.query(AdsCache).filter(AdsCache.tenant_id == tenant_id).all():
        try:
            ads = json.loads(row.ads_json or "[]")
        except Exception:
            continue
        for ad in ads:
            cr = ad.get("creative") or {}
            sid = cr.get("effective_object_story_id") or ""
            if sid and (sid == post_id or (sid.split("_")[-1] == post_suffix if "_" in sid else False)):
                src = (row.act_id, str(ad.get("adset_id", "")), str(ad.get("campaign_id", "")))
                break
        if src:
            break
    if not src or not src[1]:
        return {}
    act_id, adset_id, camp_id = src
    fb = client_for_account(db, tenant_id, act_id, "read")
    if not fb:
        for _c, f in iter_tenant_clients(db, tenant_id):
            fb = f; break
    if not fb:
        return {}
    out = {}
    try:
        a = fb.get(adset_id, {"fields": "targeting,optimization_goal,billing_event,destination_type"})
        tg = a.get("targeting") or {}
        out["optimization_goal"] = a.get("optimization_goal") or ""
        out["billing_event"] = a.get("billing_event") or ""
        dt = a.get("destination_type") or ""
        out["destination_type"] = "" if dt in ("UNDEFINED", "") else dt
        out["audience_age_min"] = tg.get("age_min")
        out["audience_age_max"] = tg.get("age_max")
        g = tg.get("genders") or []
        out["audience_gender"] = g[0] if g else 0
        out["audience_countries"] = ((tg.get("geo_locations") or {}).get("countries") or [])
        ints = []
        for grp in (tg.get("flexible_spec") or []):
            for it in (grp.get("interests") or []):
                ints.append({"id": str(it.get("id", "")), "name": it.get("name", "")})
        for it in (tg.get("interests") or []):
            ints.append({"id": str(it.get("id", "")), "name": it.get("name", "")})
        out["audience_interests"] = ints
        pp = tg.get("publisher_platforms"); dp = tg.get("device_platforms"); fp = tg.get("facebook_positions")
        if pp or dp or fp:
            out["manual_placement"] = True
            out["placement_platforms"] = pp or []
            out["placement_devices"] = dp or []
            out["facebook_positions"] = fp or []
        else:
            out["manual_placement"] = False
    except Exception:
        pass
    try:
        c = fb.get(camp_id, {"fields": "objective,bid_strategy"})
        out["objective"] = c.get("objective") or ""
        out["bid_strategy"] = c.get("bid_strategy") or ""
    except Exception:
        pass
    return out


def _fetch_post_content(db: Session, tenant_id: int, post_id: str) -> dict:
    """取帖子内容(文案/图/链接)供跟帖预览。
    ① page_posts 本地(系统建过的帖，含 message+asset 图)
    ② ads_cache creative.object_story_spec（暗帖——广告帖大多是暗帖，published_posts 读不到；
       但同步广告时拉了 object_story_spec，含 link_data/video_data 的文案+图）
    ③ FB published_posts 边(有机帖，page token——GET /{post_id} 节点对主页帖常权限不足，边才行)。
    都取不到→空 dict（前端显"无法读取"）。统一返 {message, headline, picture, cta_type, link, permalink_url}。"""
    from ..models.page_post import PagePost
    from ..models.launch import Asset
    from ..models.ads_cache import AdsCache
    from ..core.fb_tokens import iter_tenant_clients
    post_suffix = post_id.split("_")[-1] if "_" in post_id else post_id
    # ① 本地 page_posts（系统帖：message + asset 图）。视频帖无图 → 只留 message 继续往下取缩略图。
    pp_msg = ""; pp = db.query(PagePost).filter(
        PagePost.post_id == post_id, PagePost.tenant_id == tenant_id).first()
    if pp:
        pp_msg = pp.message or ""
        if pp.asset_id:
            a = db.query(Asset).filter(Asset.id == pp.asset_id, Asset.tenant_id == tenant_id).first()
            if a and a.type == "image" and a.public_url:
                return {"message": pp_msg, "headline": "", "picture": a.public_url, "cta_type": "", "link": "", "permalink_url": ""}
    # ② ads_cache 定位 creative_id → 实时 GET /{creative_id} 拿真实内容+缩略图（不靠缓存陈旧字段；
    #    缓存常缺 thumbnail_url，实时拉才有图）。暗帖主场景。
    creative_id = ""
    cached = {}
    for row in db.query(AdsCache).filter(AdsCache.tenant_id == tenant_id).all():
        try:
            ads = json.loads(row.ads_json or "[]")
        except Exception:
            continue
        for ad in ads:
            cr = ad.get("creative") or {}
            sid = cr.get("effective_object_story_id") or ""
            if sid and (sid == post_id or (sid.split("_")[-1] == post_suffix if "_" in sid else False)):
                creative_id = cr.get("id") or ""
                # 缓存兜底（实时拉失败时用）
                cached = _content_from_creative(cr) if isinstance(cr.get("object_story_spec"), dict) else {}
                break
        if creative_id:
            break
    if creative_id:
        for _c, fb in iter_tenant_clients(db, tenant_id):
            try:
                live = fb.get(creative_id, {"fields": "object_story_spec,thumbnail_url,call_to_action,title,body"})
            except Exception:
                live = None
            if live and (live.get("thumbnail_url") or isinstance(live.get("object_story_spec"), dict)):
                return _content_from_creative(live)
            break  # 拉失败 → 用缓存兜底
        if cached and (cached.get("message") or cached.get("picture") or cached.get("headline")):
            return cached
    # ③ FB published_posts 边（有机帖：page token 读边）
    page_id = post_id.split("_")[0] if "_" in post_id else ""
    if not page_id:
        return {"message": pp_msg, "headline": "", "picture": "", "cta_type": "", "link": "", "permalink_url": ""} if pp_msg else {}
    for _cred, fb in iter_tenant_clients(db, tenant_id):
        try:
            pt = fb.get_page_access_token(page_id)
        except Exception:
            pt = ""
        if not pt:
            continue
        try:
            posts = FbClient(pt).get_paged(f"{page_id}/published_posts",
                                           {"fields": "id,message,attachments{media{src}},permalink_url", "limit": 100})
        except Exception:
            continue
        for p in posts:
            if str(p.get("id", "")) == str(post_id):
                atts = (p.get("attachments") or {}).get("data", []) if isinstance(p.get("attachments"), dict) else []
                picture = (atts[0].get("media") or {}).get("src", "") if atts and isinstance(atts[0], dict) else ""
                return {"message": (p.get("message") or "")[:500], "headline": "", "picture": picture,
                        "cta_type": "", "link": "", "permalink_url": p.get("permalink_url", "")}
        break  # 该令牌管此主页但 published_posts 里没这条（暗帖/已删）→ 不再试别的令牌
    # 都没图：至少返 page_posts 的 message（若有），比空好
    return {"message": pp_msg, "headline": "", "picture": "", "cta_type": "", "link": "", "permalink_url": ""} if pp_msg else {}


@router.post("/resolve-post")
def resolve_post(body: ResolvePostIn,
                 user: CurrentUser = Depends(require_permission("ads.create")),
                 db: Session = Depends(get_db)):
    """帖子 ID/URL/广告ID → 主页 + 完整 post_id + 内容预览。供跟帖手动输入。
    支持：完整 {page}_{post} / 帖号 / permalink URL / 广告ID。
    统一返回 {page_id, post_id, source, message, headline, picture, cta_type, link, permalink_url}。"""
    import re
    q = (body.q or "").strip()
    if not q:
        raise HTTPException(400, "空")
    page_id = post_id = source = ""
    content = {}
    # 1. 完整 {page}_{post} → 直接拆
    m = re.search(r"(\d+_\d+)", q)
    if m:
        post_id = m.group(1); page_id = post_id.split("_", 1)[0]; source = "full"
    else:
        # 2. 裸 post 号 / URL → 提取帖子号
        # 优先 URL 里的 post 段（/posts/{n}/、fbid=/story_fbid=、permalink/..._{n}），否则取最长数字串
        # （避免把主页 ID 当帖子号——permalink 里页 ID 在前，帖号在后）
        url_m = (re.search(r"/posts/(\d{10,})", q) or re.search(r"[?&](?:fbid|story_fbid)=(\d{10,})", q)
                 or re.search(r"/permalink/\d+_(\d+)", q) or re.search(r"/videos/(\d{10,})", q))
        if url_m:
            post_num = url_m.group(1)
        else:
            runs = re.findall(r"\d{10,}", q)
            if not runs:
                raise HTTPException(400, "无法识别帖子 ID")
            post_num = max(runs, key=len)  # 最长（帖子号通常比页 ID 长）
        hit = _local_resolve_post(db, user.tenant_id, post_num)  # 2a. 本地 ads_cache 反查
        if hit:
            page_id, post_id, source = hit["page_id"], hit["post_id"], hit["source"]
        else:
            # 2b. FB 兜底：遍历令牌 GET /{post_num}（可能是帖号或广告ID）
            from ..core.fb_tokens import iter_tenant_clients
            for _cred, fb in iter_tenant_clients(db, user.tenant_id):
                try:
                    p = fb.get(post_num, {"fields": "id,name,from,message,attachments{media{src}},permalink_url,"
                                                    "creative{id,effective_object_story_id,object_story_spec,thumbnail_url,call_to_action}"})
                except Exception:
                    continue
                # 广告ID → 取 creative 的 post
                cr = p.get("creative") or {}
                if isinstance(cr, dict) and cr.get("effective_object_story_id"):
                    ad_sid = cr["effective_object_story_id"]
                    page_id, post_id, source = (ad_sid.split("_", 1)[0] if "_" in ad_sid else ""), ad_sid, "fb"
                    content = _content_from_creative(cr)
                    break
                # 帖号 → 直读
                full = p.get("id", "")
                frm = p.get("from") or {}
                pid = str(frm.get("id") or ("")) or (full.split("_", 1)[0] if "_" in full else "")
                if full and pid:
                    page_id, post_id, source = pid, full, "fb"
                    atts = (p.get("attachments") or {}).get("data", []) if isinstance(p.get("attachments"), dict) else []
                    picture = (atts[0].get("media") or {}).get("src", "") if atts and isinstance(atts[0], dict) else ""
                    content = {"message": (p.get("message") or "")[:300], "headline": "", "picture": picture,
                               "cta_type": "", "link": "", "permalink_url": p.get("permalink_url", "")}
                    break
            if not post_id:
                raise HTTPException(404, "未找到该帖子（本地缓存无、令牌也无权访问）")
    # full/local → 补内容预览（FB 兜底已带 content）；无权访问则空字段
    if source != "fb":
        content = _fetch_post_content(db, user.tenant_id, post_id)
    # 克隆源广告的系列/广告组设置（受众/版位/目标）——"复用此帖铺放"= 克隆广告
    ad_settings = _clone_ad_settings(db, user.tenant_id, post_id)
    return {"page_id": page_id, "post_id": post_id, "source": source,
            "message": content.get("message", ""), "headline": content.get("headline", ""),
            "picture": content.get("picture", ""), "cta_type": content.get("cta_type", ""),
            "link": content.get("link", ""), "permalink_url": content.get("permalink_url", ""),
            "ad_settings": ad_settings}



@router.get("/credentials/{cred_id}/pixels")
def list_credential_pixels(
    cred_id: int,
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """列出该令牌能管理的像素（遍历广告账户拉）。"""
    cred = db.query(FbCredential).filter(
        FbCredential.tenant_id == user.tenant_id,
        FbCredential.id == cred_id,
    ).first()
    if not cred:
        raise HTTPException(404, "令牌不存在")
    fb = FbClient(decrypt(cred.access_token_enc))
    pixels = []
    seen = set()
    try:
        for acc in fb.get_ad_accounts():
            act_id = acc.get("account_id", "")
            if not act_id:
                continue
            try:
                for p in fb.get_pixels(act_id):
                    pid = p.get("id", "")
                    if pid and pid not in seen:
                        seen.add(pid)
                        pixels.append({"id": pid, "name": p.get("name", ""), "account": act_id})
            except FbApiError:
                continue
    except FbApiError as e:
        raise HTTPException(400, e.friendly)
    return pixels


@router.get("/credentials/assets-summary")
def credentials_assets_summary(
    fresh: bool = False,   # 手动刷新绕过缓存
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """全部令牌的资产计数：账户(DB 已导入) + 主页/BM(FB)。像素不在此列。

    主页/BM 是准静态数据（串行调 FB 每令牌两次，令牌多时展开很慢）——1h 进程内缓存，
    fresh=true 绕过（令牌刷新/重导后自动失效部分：令牌集合 hash 变了也绕过）。
    """
    import time as _t
    creds = db.query(FbCredential).filter(
        FbCredential.tenant_id == user.tenant_id, FbCredential.status == "active"
    ).all()
    # 签名含纳管账户数：unmanage/重新导入后计数变化即失效，不会给最长 1h 的旧计数
    _mgd = db.query(Account).filter(
        Account.tenant_id == user.tenant_id, Account.is_managed == True  # noqa: E712
    ).count()
    _sig = ",".join(str(c.id) for c in creds) + f":{len(creds)}:{_mgd}"
    ent = _ASSETS_SUMMARY_CACHE.get(user.tenant_id)
    _now = _t.time()
    if not fresh and ent and _now - ent[0] < 3600 and ent[2] == _sig:
        return ent[1]
    out: dict = {}
    for c in creds:
        acct_count = db.query(Account).filter(
            Account.tenant_id == c.tenant_id, Account.fb_credential_id == c.id,
            Account.is_managed == True,  # noqa: E712  只数已纳管账户（与抽屉/广告账户页口径一致）
        ).count()
        fb = FbClient(decrypt(c.access_token_enc))
        try:
            pages = fb.get_pages()
            bms = fb.get_businesses()
            out[c.id] = {"accounts": acct_count, "pages": len(pages),
                         "businesses": len(bms)}
        except FbApiError as e:
            out[c.id] = {"accounts": acct_count, "pages": None,
                         "businesses": None, "error": e.friendly}
    _ASSETS_SUMMARY_CACHE[user.tenant_id] = (_now, out, _sig)
    return out


@router.get("/credentials/{cred_id}/assets")
def get_credential_assets(
    cred_id: int,
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """该令牌的资产：已导入广告账户（DB）+ 主页 / BM（FB）。抽屉用。"""
    cred = db.query(FbCredential).filter(
        FbCredential.tenant_id == user.tenant_id,
        FbCredential.id == cred_id,
    ).first()
    if not cred:
        raise HTTPException(404, "令牌不存在")
    from ..services.guard_engine import calc_available_balance, from_minor_units, fmt_spend
    accounts = []
    for a in db.query(Account).filter(
        Account.tenant_id == user.tenant_id, Account.fb_credential_id == cred_id,
        Account.is_managed == True,  # noqa: E712  抽屉只列已纳管账户（与"已导入"口径一致；未导入的不显示）
    ).all():
        avail_usd, kind = calc_available_balance(a.spend_cap, a.amount_spent, a.currency or "USD")
        if kind == "limited":
            cap_n = from_minor_units(a.spend_cap, a.currency) or 0
            spent_n = from_minor_units(a.amount_spent, a.currency) or 0
            balance_label = fmt_spend(cap_n - spent_n, a.currency or "USD")
        else:
            balance_label = "不限额"
        accounts.append({"account_id": a.act_id, "name": a.name, "currency": a.currency,
                         "account_status": a.account_status, "balance_label": balance_label})
    pages: list = []
    businesses: list = []
    error = None
    fb = FbClient(decrypt(cred.access_token_enc))
    try:
        for pg in fb.get_pages():
            pages.append({"id": pg.get("id", ""), "name": pg.get("name", ""),
                          "category": pg.get("category", ""), "fan_count": pg.get("fan_count", 0),
                          "can_post": pg.get("can_post"), "tasks": pg.get("tasks", [])})
        for b in fb.get_businesses():
            businesses.append({"id": b.get("id", ""), "name": b.get("name", ""), "role": ""})
        # /me/businesses 边缘不返回 permitted_tasks（实测恒空，曾因此全员显示"基本"）。
        # 真实角色在 /{bm}/business_users——但其中 id 是 business 作用域 ID（buid），
        # 不等于 token 用户的 FB profile id，不能直接比。正确做法：/me/business_users
        # 返回本人在各 BM 的 buid+role 集合，拿 buid 去各 BM 用户列表里认领。
        # 逐 BM 串行查太贵（大池 100+ BM），batch API 一次 50 个。
        if businesses:
            try:
                my_buids: dict = {}
                for bu in fb.get_paged("me/business_users", {"fields": "id,role"}):
                    if bu.get("id"):
                        my_buids[str(bu["id"])] = bu.get("role") or ""
                if my_buids:
                    urls = [f"{b['id']}/business_users?fields=id,role&limit=200" for b in businesses]
                    for b, users in zip(businesses, fb.batch_get(urls)):
                        me_role = ""
                        for u in (users or {}).get("data", []):
                            uid = str(u.get("id") or "")
                            if uid in my_buids:
                                me_role = u.get("role") or my_buids[uid]
                                break
                        b["role"] = "完全" if me_role == "ADMIN" else "基本"
            except FbApiError:
                for b in businesses:
                    b["role"] = b["role"] or "基本"
    except FbApiError as e:
        error = e.friendly
    return {"accounts": accounts, "pages": pages,
            "businesses": businesses, "error": error}


@router.post("/credentials/{cred_id}/refresh-accounts")
def refresh_credential_accounts(
    cred_id: int,
    user: CurrentUser = Depends(require_permission("ads.create")),
    db: Session = Depends(get_db),
):
    """刷新该令牌【已导入】账户的实时状态/余额。不新增导入（导入走手动选择）。"""
    cred = db.query(FbCredential).filter(
        FbCredential.tenant_id == user.tenant_id,
        FbCredential.id == cred_id,
    ).first()
    if not cred:
        raise HTTPException(404, "令牌不存在")
    fb = FbClient(decrypt(cred.access_token_enc))
    try:
        # 显式带 disable_reason（FbClient.get_ad_accounts 的字段表不含它，且 fb_client
        # 不在本次改动管辖——字段常量与 account_sync cron 共用，避免两处漂移）
        from ..services.account_sync import ADACCOUNT_SYNC_FIELDS
        fb_accounts = fb.get_paged("me/adaccounts", {"fields": ADACCOUNT_SYNC_FIELDS})
    except FbApiError as e:
        raise HTTPException(400, e.friendly)
    fb_map = {a.get("account_id"): a for a in fb_accounts}
    imported_rows = db.query(Account).filter(
        Account.tenant_id == user.tenant_id, Account.fb_credential_id == cred_id,
    ).all()
    updated = 0
    for acc in imported_rows:
        live = fb_map.get(acc.act_id)
        if not live:
            continue
        acc.account_status = live.get("account_status") or acc.account_status
        # 显式判 None 而非 or 兜底：disable_reason=0（恢复正常）是合法值，or 会跳过导致旧原因残留
        _dr = live.get("disable_reason")
        if _dr is not None:
            acc.disable_reason = int(_dr)
        acc.balance = str(live.get("balance", "") or "")
        acc.spend_cap = str(live.get("spend_cap", "") or "")
        acc.amount_spent = str(live.get("amount_spent", "") or "")
        updated += 1
    db.commit()
    return {"updated": updated, "imported_total": len(imported_rows)}


@router.get("/assets")
def get_assets(
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """用已存凭证拉 FB 资产（广告账户 + 主页）。聚合所有 active token（多 token 不漏）。"""
    from ..core.fb_tokens import iter_tenant_clients
    pairs = iter_tenant_clients(db, user.tenant_id)
    if not pairs:
        raise HTTPException(400, "未绑定 FB 凭证")
    accounts, pages = [], []
    seen_act, seen_page = set(), set()
    for _cred, fb in pairs:
        try:
            for a in fb.get_ad_accounts():
                if a.get("account_id") and a["account_id"] not in seen_act:
                    seen_act.add(a["account_id"]); accounts.append(a)
            for p in fb.get_pages():
                if p.get("id") and p["id"] not in seen_page:
                    seen_page.add(p["id"]); pages.append(p)
        except (FbApiError, TtApiError):
            # 混合池含 TT 凭证（iter_tenant_clients）——TT 错误不得炸 FB 聚合
            continue
    return {"ad_accounts": accounts, "pages": pages}


@router.get("/credentials/loadable-accounts")
def loadable_accounts(
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """遍历所有 active token，合并可管理广告账户（去重），每个标注来源令牌 + 可用性 + 是否已导入。

    供「载入账户」勾选用：一个账户可能被多个令牌覆盖（多 FB 用户都管它），
    tokens[] 列出所有覆盖令牌及其当前可用性，前端据此判断"全丢"风险。
    大代理令牌可见 3k+ 账户（轻字段全量 ~30s）——进程内 5 分钟缓存，
    /fb/import 复用同一缓存（勾选导入零 FB 调用，秒回）。
    """
    rows = _get_loadable_rows(db, user.tenant_id)
    imported_ids = {a.act_id for a in db.query(Account).filter(
        Account.tenant_id == user.tenant_id, Account.is_managed == True  # noqa: E712
    ).all()}
    out = []
    for r in rows:
        r["imported"] = r["account_id"] in imported_ids
        out.append(r)
    return out


_LOADABLE_CACHE: dict = {}   # tenant_id -> (ts, rows)；rows 含 tokens[]（无 imported——每次现算）
_LOADABLE_TTL = 300


def _get_loadable_rows(db, tenant_id: int) -> list[dict]:
    """载入列表原始行（FB 拉取 + 合并），带 5 分钟进程内缓存。"""
    import time as _t
    ent = _LOADABLE_CACHE.get(tenant_id)
    if ent and _t.time() - ent[0] < _LOADABLE_TTL:
        return ent[1]
    from ..core.fb_tokens import _is_cred_available
    from concurrent.futures import ThreadPoolExecutor
    creds = db.query(FbCredential).filter(
        FbCredential.tenant_id == tenant_id, FbCredential.status == "active"
    ).all()

    def _pull(c):
        fb = FbClient(decrypt(c.access_token_enc))
        try:
            return c, fb.get_ad_accounts(light=True)
        except (FbApiError, TtApiError):
            return c, None

    merged: dict = {}
    if creds:
        with ThreadPoolExecutor(max_workers=min(4, len(creds))) as ex:
            for c, accounts in ex.map(_pull, creds):
                if not accounts:
                    continue
                avail = _is_cred_available(c)
                for a in accounts:
                    aid = a.get("account_id", "")
                    if not aid or not a.get("name"):
                        continue  # 无 ID 或 FB 未返回 name（管不了/无意义）→ 不进载入列表
                    if aid not in merged:
                        merged[aid] = {
                            "account_id": aid, "name": a.get("name", aid),
                            "currency": a.get("currency", "USD"),
                            "timezone_name": a.get("timezone_name") or "UTC",
                            "account_status": a.get("account_status"),
                            "tokens": [],
                        }
                    merged[aid]["tokens"].append(
                        {"id": c.id, "alias": c.alias or c.fb_user_name, "available": avail})
    rows = list(merged.values())
    _LOADABLE_CACHE[tenant_id] = (_t.time(), rows)
    return rows


def _verify_ids_pointwise(db, tenant_id: int, aids: list[str]) -> dict:
    """逐 ID 点查验证令牌覆盖（1.0 _fetch_single_account 思路 + FB batch 加速）。

    ID 粘贴导入只有几十个目标——为此拉令牌全量账户列表（2000+ 账户 50s+，
    载入弹窗才需要全量）纯属浪费且超时；点查 GET /act_{id} 即
    「该令牌可读 = 可纳管」的权威判定（无权限 FB 返回 error）。
    返回 {aid: row}，row 结构与 _get_loadable_rows 行一致。
    """
    from ..core.fb_tokens import _is_cred_available
    creds = db.query(FbCredential).filter(
        FbCredential.tenant_id == tenant_id, FbCredential.status == "active"
    ).all()
    out: dict = {}
    for c in creds:
        pending = [a for a in aids if a not in out]
        if not pending:
            break
        fb = FbClient(decrypt(c.access_token_enc))
        avail = _is_cred_available(c)
        for i in range(0, len(pending), 50):
            chunk = pending[i:i + 50]
            urls = [f"act_{a}?fields=account_id,name,currency,timezone_name,account_status,disable_reason"
                    for a in chunk]
            try:
                results = fb.batch_get(urls)
            except FbApiError:
                break  # 该令牌整批失败（失效/限流）→ 换下一个令牌
            for aid, meta in zip(chunk, results):
                if meta and "error" not in meta and meta.get("account_id"):
                    out[aid] = {
                        "account_id": aid,
                        "name": meta.get("name") or aid,
                        "currency": meta.get("currency", "USD"),
                        "timezone_name": meta.get("timezone_name") or "UTC",
                        "account_status": meta.get("account_status"),
                        "disable_reason": meta.get("disable_reason"),
                        "tokens": [{"id": c.id, "alias": c.alias or c.fb_user_name,
                                    "available": avail}],
                    }
    return out


def _bg_complete_imported(tenant_id: int, cred_ids: list[int]):
    """导入后补全轻字段拉取时缺的余额/上限/已花费（后台跑，不阻塞响应）。

    轻字段是为了让 3k+ 账户的载入/导入不超时；余额等重计算字段由这里补，
    失败静默（account_sync cron 兜底）。
    """
    db = SuperSessionLocal()
    try:
        for cid in cred_ids:
            cred = db.query(FbCredential).filter(
                FbCredential.tenant_id == tenant_id, FbCredential.id == cid).first()
            if not cred:
                continue
            try:
                # 同 refresh-accounts：显式带 disable_reason（fb_client 字段表不含它）
                from ..services.account_sync import ADACCOUNT_SYNC_FIELDS
                fb_map = {a.get("account_id"): a for a in
                          FbClient(decrypt(cred.access_token_enc)).get_paged(
                              "me/adaccounts", {"fields": ADACCOUNT_SYNC_FIELDS})}
            except FbApiError:
                continue
            for acc in db.query(Account).filter(
                Account.tenant_id == tenant_id, Account.fb_credential_id == cid,
                Account.is_managed == True,  # noqa: E712
            ).all():
                live = fb_map.get(acc.act_id)
                if not live:
                    continue
                acc.account_status = live.get("account_status") or acc.account_status
                _dr = live.get("disable_reason")
                if _dr is not None:   # 0 是合法值（恢复正常），or 兜底会跳过导致旧原因残留
                    acc.disable_reason = int(_dr)
                if live.get("timezone_name"):
                    acc.timezone_name = live["timezone_name"]  # 时区是巡检/加白日期的基准，必须补准
                acc.balance = str(live.get("balance", "") or "")
                acc.spend_cap = str(live.get("spend_cap", "") or "")
                acc.amount_spent = str(live.get("amount_spent", "") or "")
        db.commit()
    finally:
        db.close()


@router.post("/import")
def import_accounts(
    body: ImportAccountsIn,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_permission("ads.create")),
    db: Session = Depends(get_db),
):
    """导入广告账户（手动选择）。输入自动清洗：去 act_ 前缀、去空格、去重；跳过已存在。

    返回 {imported, skipped_existing, not_found, total}：
    - imported: 新导入的 act_id
    - skipped_existing: 已存在（含重绑到新 token）
    - not_found: 无任何 active token 覆盖的 ID

    覆盖判定优先级：载入列表 5 分钟缓存命中（勾选场景零 FB 调用）→
    未命中走 _verify_ids_pointwise 逐 ID 点查（ID 粘贴场景只查几十个，
    不拉 2000+ 账户的全量列表——全量拉取曾致请求超时）。
    余额等重字段由后台任务补（_bg_complete_imported）。
    """
    raw = body.account_ids or []
    cleaned: list[str] = []
    seen = set()
    for aid in raw:
        if aid is None:
            continue
        s = str(aid).strip().replace("act_", "").replace("ACT_", "").strip()
        if s and s not in seen:
            seen.add(s)
            cleaned.append(s)
    if not cleaned:
        return {"imported": [], "count": 0, "skipped_existing": 0,
                "not_found": [], "total": 0}
    import time as _t
    ent = _LOADABLE_CACHE.get(user.tenant_id)
    if ent and _t.time() - ent[0] < _LOADABLE_TTL:
        rows = {r["account_id"]: r for r in ent[1]}
    else:
        rows = _verify_ids_pointwise(db, user.tenant_id, cleaned)
    if not rows:
        creds_exist = db.query(FbCredential.id).filter(
            FbCredential.tenant_id == user.tenant_id,
            FbCredential.status == "active").first()
        if not creds_exist:
            raise HTTPException(400, "未绑定 FB 凭证")
        # 有令牌但点查全部不覆盖 → 明确返回 not_found（不是报错）
        return {"imported": [], "count": 0, "skipped_existing": 0,
                "not_found": sorted(set(cleaned)), "total": len(cleaned)}
    imported: list[str] = []
    skipped_existing = 0
    covered: set = set()
    touched_creds: set = set()
    for aid in cleaned:
        row = rows.get(aid)
        if not row:
            continue  # 无任何 active token 覆盖
        covered.add(aid)
        tokens = row.get("tokens") or []
        if not tokens:
            continue
        cred_id = tokens[0]["id"]
        touched_creds.add(cred_id)
        exists = db.query(Account).filter(
            Account.tenant_id == user.tenant_id,
            Account.act_id == aid,
        ).first()
        if exists:
            if exists.fb_credential_id != cred_id:
                exists.fb_credential_id = cred_id
            exists.is_managed = True  # 重新导入 = 恢复纳管（把软删的拉回活跃管理）
            # 多令牌同账户：加 account_fb_credentials 关联（已有则跳过 → 多 token 共管）
            if not db.query(AccountFbCredential).filter(
                AccountFbCredential.account_id == exists.id,
                AccountFbCredential.fb_credential_id == cred_id,
            ).first():
                db.add(AccountFbCredential(
                    tenant_id=user.tenant_id, account_id=exists.id,
                    fb_credential_id=cred_id, priority=0, status="active",
                ))
            skipped_existing += 1
            continue
        new_acc = Account(
            tenant_id=user.tenant_id,
            fb_credential_id=cred_id,
            act_id=aid,
            name=row.get("name") or "",
            currency=row.get("currency", "USD"),
            timezone_name=row.get("timezone_name", "UTC"),
            owner_user_id=user.id,
            account_status=row.get("account_status", 1),
            disable_reason=(int(row["disable_reason"]) if row.get("disable_reason") is not None else None),
        )
        db.add(new_acc)
        db.flush()  # 拿 new_acc.id 用于关联
        db.add(AccountFbCredential(
            tenant_id=user.tenant_id, account_id=new_acc.id,
            fb_credential_id=cred_id, priority=0, status="active",
        ))
        imported.append(aid)
    db.commit()
    # 载入缓存行不含 imported 标记（每次现算），导入后无需作废——
    # 勾选场景「开弹窗（慢一次）→ 导入（缓存命中秒回）」保持成立
    if imported:
        background_tasks.add_task(_bg_complete_imported, user.tenant_id, sorted(touched_creds))
    not_found = sorted(set(cleaned) - covered)
    return {"imported": imported, "count": len(imported),
            "skipped_existing": skipped_existing,
            "not_found": not_found, "total": len(cleaned)}


@router.get("/accounts")
def list_accounts(
    date_from: str = "",
    date_to: str = "",
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """列本租户已导入广告账户（全字段+可用额度+近3天消耗+绑令牌）。Operator 只看名下。
    只返回纳管中的（is_managed=True），已移除的不显示。"""
    from sqlalchemy import func
    from ..services.guard_engine import calc_available_balance, from_minor_units, to_usd
    from ..models.perf import PerfSnapshot
    from ..core.fb_tokens import _is_cred_available
    query = db.query(Account).filter(
        Account.tenant_id == user.tenant_id, Account.is_managed == True
    )
    if user.role == "operator":
        query = query.filter(Account.owner_user_id == user.id)
    accs = query.order_by(Account.account_status.asc()).all()
    cred_ids = {a.fb_credential_id for a in accs if a.fb_credential_id}
    creds = {c.id: c for c in db.query(FbCredential).filter(FbCredential.id.in_(cred_ids)).all()} if cred_ids else {}
    # 候选池令牌数 + 别名列表（多令牌轮换）
    acc_pks = [a.id for a in accs]
    pool_map = {}
    pool_alias_map = {}
    if acc_pks:
        from ..models.fb import AccountFbCredential
        from sqlalchemy import func as _f
        # 一次 JOIN 拿 account_id + 对应 cred 的 alias
        _rows = db.query(AccountFbCredential.account_id, FbCredential.id, FbCredential.alias).outerjoin(
            FbCredential, FbCredential.id == AccountFbCredential.fb_credential_id
        ).filter(
            AccountFbCredential.account_id.in_(acc_pks),
            AccountFbCredential.status == "active",
        ).all()
        _by_acc = {}
        for r in _rows:
            _alias = r[2] or (str(r[1]) if r[1] else "?")
            _by_acc.setdefault(r[0], []).append(_alias)
        for aid, aliases in _by_acc.items():
            pool_map[aid] = len(aliases)
            pool_alias_map[aid] = " / ".join(aliases)
    act_ids = [a.act_id for a in accs]
    spend_map = {}
    if act_ids:
        since = date_from or (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")
        pq = db.query(PerfSnapshot.act_id, func.sum(PerfSnapshot.spend), func.sum(PerfSnapshot.conversions)).filter(
            PerfSnapshot.tenant_id == user.tenant_id,
            PerfSnapshot.act_id.in_(act_ids),
            PerfSnapshot.snapshot_date >= since,
        )
        if date_to:
            pq = pq.filter(PerfSnapshot.snapshot_date <= date_to)
        rows = pq.group_by(PerfSnapshot.act_id).all()
        spend_map = {r[0]: {"spend": float(r[1] or 0), "conversions": int(r[2] or 0)} for r in rows}
    out = []
    for a in accs:
        cur = a.currency or "USD"
        cred = creds.get(a.fb_credential_id) if a.fb_credential_id else None
        avail_usd, bal_kind = calc_available_balance(a.spend_cap, a.amount_spent, cur)
        bal = from_minor_units(a.balance, cur)
        perf = spend_map.get(a.act_id, {})
        out.append({
            "id": a.id, "act_id": a.act_id, "name": a.name, "currency": cur,
            "platform": a.platform or "fb",
            "timezone": a.timezone_name, "account_status": a.account_status,
            "group_label": a.group_label or "", "disable_reason": a.disable_reason,
            "is_managed": a.is_managed if a.is_managed is not None else True,
            "warmup_state": a.warmup_state or "none",
            "balance": bal, "balance_usd": (round(_tu, 2) if (bal is not None and (_tu := to_usd(bal, cur)) is not None) else None),   # 未知币种 None 不崩
            "spend_cap": from_minor_units(a.spend_cap, cur),
            "amount_spent": from_minor_units(a.amount_spent, cur),
            "available_usd": avail_usd, "balance_kind": bal_kind,
            "owner_user_id": a.owner_user_id, "fb_credential_id": a.fb_credential_id,
            "bound_alias": (cred.alias or cred.fb_user_name) if cred else None,
            "bound_status": cred.status if cred else "unbound",
            "bound_available": _is_cred_available(cred) if cred else False,
            "pool_count": pool_map.get(a.id, 0),
            "pool_aliases": pool_alias_map.get(a.id, ""),
            "recent_spend": perf.get("spend", 0.0), "recent_conversions": perf.get("conversions", 0),
        })
    return out


@router.put("/accounts/group")
def set_account_group(
    body: AccountGroupIn,
    user: CurrentUser = Depends(require_permission("ads.create")),
    db: Session = Depends(get_db),
):
    """批量设置账户分组标签（group_label 空串=清除）。

    纯用户自定义标签（"主投组/测试组"），不关联 FB 任何对象——分组本质是标签，
    保持轻（无分组表/无枚举约束）。tenant 隔离 + operator 只能动名下账户（同列表
    可见性），写 action_logs 留痕（action_type=group_update，FB/TT 混批按平台分行）。
    """
    cleaned = [a.replace("act_", "").replace("ACT_", "").strip() for a in body.act_ids]
    cleaned = [a for a in cleaned if a]
    if not cleaned:
        raise HTTPException(400, "未选择账户")
    if len(cleaned) > 500:
        raise HTTPException(400, "单次最多 500 个账户")
    label = (body.group_label or "").strip()
    if len(label) > 50:
        raise HTTPException(400, "分组名过长（≤50 字符）")
    query = db.query(Account).filter(
        Account.tenant_id == user.tenant_id,
        Account.act_id.in_(cleaned),
        Account.is_managed == True,  # noqa: E712
    )
    if user.role == "operator":
        query = query.filter(Account.owner_user_id == user.id)
    accs = query.all()
    if not accs:
        raise HTTPException(404, "账户不存在或无权限")
    for acc in accs:
        acc.group_label = label or None   # 空串归一为 NULL（无分组），避免空串/NULL 两态并存
    from ..core.log_utils import write_log, new_trace_id
    # 留痕按平台分组各写一行（FB/TT 混批不把 TT 记成 fb；write_log 的 platform 默认 'fb'）
    _tid = new_trace_id()
    _by_plat: dict = {}
    for a in accs:
        _by_plat.setdefault(a.platform or "fb", []).append(a.act_id)
    for _plat, _ids in _by_plat.items():
        write_log(db, tenant_id=user.tenant_id, trace_id=_tid, actor_type="user",
                  actor_user_id=user.id, target_type="account",
                  target_id=_ids[0] if len(_ids) == 1 else f"batch:{len(_ids)}",
                  action_type="group_update", source="user", result="success", platform=_plat,
                  trigger_detail=f"n={len(_ids)} label={label or '(clear)'}",
                  metadata={"act_ids": _ids, "group_label": label or None})
    db.commit()
    return {"updated": len(accs), "group_label": label or None}


@router.get("/accounts/at-risk")
def accounts_at_risk(
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """已导入账户中绑定令牌不可用（失效/限流冷却/未绑定）的风险账户。纯 DB，实时。

    供令牌页风险提示：这些账户当前无法读写。watchdog（run_reassociate）会另对
    "无任何可用令牌覆盖"的真孤儿发 critical 告警 + TG。
    """
    from ..core.fb_tokens import _is_cred_available
    query = db.query(Account).filter(
        Account.tenant_id == user.tenant_id, Account.is_managed == True  # noqa: E712
    )
    if user.role == "operator":
        query = query.filter(Account.owner_user_id == user.id)
    accs = query.all()
    cred_ids = {a.fb_credential_id for a in accs if a.fb_credential_id}
    creds = {c.id: c for c in db.query(FbCredential).filter(FbCredential.id.in_(cred_ids)).all()} if cred_ids else {}
    out = []
    for a in accs:
        cred = creds.get(a.fb_credential_id) if a.fb_credential_id else None
        if not cred or not _is_cred_available(cred):
            out.append({"act_id": a.act_id, "name": a.name,
                        "account_status": a.account_status,
                        "bound_cred_id": a.fb_credential_id,
                        "bound_alias": (cred.alias or cred.fb_user_name) if cred else None,
                        "bound_status": cred.status if cred else "unbound"})
    return out


@router.delete("/accounts/{act_id}")
def unmanage_account(
    act_id: str,
    user: CurrentUser = Depends(require_permission("ads.create")),
    db: Session = Depends(get_db),
):
    """取消纳管：软删（is_managed=false）—— 保留行+名字+历史消耗，dashboard/报表仍可见该账户历史，
    只是不再巡检/不进活跃管理。FB 上账户仍在、令牌权限不变。要再加回用「恢复纳管」或重新导入。
    """
    aid = act_id.replace("act_", "").replace("ACT_", "").strip()
    acc = db.query(Account).filter(
        Account.tenant_id == user.tenant_id, Account.act_id == aid,
    ).first()
    if not acc:
        raise HTTPException(404, "账户未纳管")
    # 先数 ACTIVE 广告（删缓存前数——前端确认文案要告知"广告不会停、止损失效"）。
    # ads_cache 同 act_id 可跨平台并存（FB/TT act_id 空间独立）——按账户 platform 过滤。
    active_ads = 0
    _plat = acc.platform or "fb"
    try:
        import json as _json
        from ..models.ads_cache import AdsCache as _AC2
        _c = db.query(_AC2).filter(_AC2.tenant_id == user.tenant_id, _AC2.act_id == aid,
                                   _AC2.platform == _plat).first()
        if _c and _c.ads_json:
            active_ads = sum(1 for _a in _json.loads(_c.ads_json or "[]")
                             if str(_a.get("effective_status", "")) == "ACTIVE")
    except Exception:
        pass
    acc.is_managed = False
    # 清哨兵/预热状态：取消纳管后不应再被哨兵停广告；恢复纳管时也不会带着旧 armed 立刻被停
    acc.sentinel_armed = False
    acc.sentinel_auto_armed = False
    acc.warmup_state = "none"
    # 清该账户的 ads_cache（广告管理器读它——不清则移除后仍显示陈旧广告列表）。
    # 同上按 platform 过滤：只清本平台的缓存行，不误删另一平台同 act_id 的行。
    # perf_snapshots 保留（历史消耗数据不丢，dashboard/报表仍可查）。
    try:
        from ..models.ads_cache import AdsCache
        db.query(AdsCache).filter(
            AdsCache.tenant_id == user.tenant_id, AdsCache.act_id == aid,
            AdsCache.platform == _plat).delete()
    except Exception:
        pass
    # 清该账户的素材 FB image_hash/video_id 缓存：解除纳管后成死数据，
    # 重导账户后旧值仍挂在素材上属脏数据（重新部署会自然重传，无需预热）。
    # JSON 键是纯数字 act_id（ensure_image_hash_for_account 写入约定）。
    try:
        from ..models.launch import Asset
        _dirty = False
        for col in (Asset.fb_image_hashes, Asset.fb_video_ids):
            for a in db.query(Asset).filter(
                Asset.tenant_id == user.tenant_id,
                col.isnot(None),
                col.ilike(f'%"{aid}"%'),
            ).all():
                try:
                    cache = json.loads(a.fb_image_hashes if col is Asset.fb_image_hashes else a.fb_video_ids)
                except Exception:
                    cache = None
                if isinstance(cache, dict) and aid in cache:
                    del cache[aid]
                    if col is Asset.fb_image_hashes:
                        a.fb_image_hashes = json.dumps(cache, ensure_ascii=False) if cache else None
                    else:
                        a.fb_video_ids = json.dumps(cache, ensure_ascii=False) if cache else None
                    _dirty = True
    except Exception:
        pass  # 清缓存失败不阻断取消纳管主流程
    # 留痕 + 告警（P0-7）：unmanage 必写 action_logs（审计）；有 ACTIVE 广告时告警——
    # 广告不会自动停、止损/哨兵即刻脱管，必须让 owner/operator 知晓（一次性操作，不 dedup）。
    from ..core.log_utils import write_log, new_trace_id
    _tid = new_trace_id()
    if active_ads > 0:
        try:
            from ..core.notify_utils import emit_notification
            from ..core.i18n import tenant_locale, notify_text
            from html import escape as _esc
            _loc = tenant_locale(db, user.tenant_id)
            _title, _body = notify_text(_loc, "unmanage_active_ads",
                                        name=_esc(acc.name or aid), act_id=aid, n=active_ads)
            emit_notification(db, tenant_id=user.tenant_id, level="warning",
                              event_type="unmanage_active_ads", trace_id=_tid,
                              title=_title, body=_body,
                              target_type="account", target_id=aid, platform=_plat)
        except Exception:
            pass  # 告警失败不阻断取消纳管主流程（log 兜底）
    write_log(db, tenant_id=user.tenant_id, trace_id=_tid, actor_type="user",
              actor_user_id=user.id, target_type="account", target_id=aid,
              action_type="unmanage", source="user", result="success",
              trigger_detail=f"active_ads={active_ads} platform={_plat}",
              metadata={"active_ads": active_ads, "platform": _plat},
              platform=_plat)   # 复审C P2：漏传时 TT 账户取消纳管被记成 fb，审计平台列失真
    db.commit()
    return {"unmanaged": True, "act_id": aid, "active_ads_at_removal": active_ads}


# ── 数据健康诊断 / 脏数据清洗（超管，令牌页挂账项）──
# 只读扫描列出令牌/账户/关联表的脏数据；data-clean 手动清理悬挂关联行（幂等，写 action_logs）。
# 不自动跑：正常写路径（delete_credential/unmanage/import）已各自清理，这里兜历史遗留与中途失败残渣。
_CRED_STATUS_ENUM = ("active", "rate_limited", "limited", "expired")
_TOKEN_TYPE_ENUM = ("user", "manage", "operate")
_AFC_STATUS_ENUM = ("active", "disabled")


def _scan_token_data_health(db: Session) -> dict:
    """全平台扫描令牌/账户关联脏数据（BYPASSRLS，超管专用）。返回 {totals, issues, cleanable}。"""
    from ..models.fb import TokenHealth
    creds = db.query(FbCredential).all()
    accounts = db.query(Account).all()
    afcs = db.query(AccountFbCredential).all()
    ths = db.query(TokenHealth).all()

    cred_by_id = {c.id: c for c in creds}
    acct_by_id = {a.id: a for a in accounts}
    issues: dict = {}

    def _issue(key: str, cleanable: bool, rows: list):
        issues[key] = {"count": len(rows), "cleanable": cleanable, "samples": rows[:20]}

    # ① fb_credentials.status 不在枚举（写路径只产 active/expired/rate_limited/limited）
    _issue("cred_bad_status", False, [
        {"tenant_id": c.tenant_id, "id": c.id, "alias": c.alias, "status": c.status}
        for c in creds if (c.status or "") not in _CRED_STATUS_ENUM])

    # ② token_type 不在枚举（含 "'user'" 这类引号脏值；归一只救引号/大小写，真非法值不动）
    _issue("cred_bad_token_type", True, [
        {"tenant_id": c.tenant_id, "id": c.id, "alias": c.alias, "token_type": c.token_type}
        for c in creds
        if (c.token_type or "").strip().strip("'\"").lower() not in _TOKEN_TYPE_ENUM])

    # ③ accounts.fb_credential_id 悬挂：指向已删令牌 / 跨租户令牌
    rows = []
    for a in accounts:
        if not a.fb_credential_id:
            continue
        c = cred_by_id.get(a.fb_credential_id)
        reason = "missing_cred" if c is None else (
            "cross_tenant" if c.tenant_id != a.tenant_id else None)
        if reason:
            rows.append({"tenant_id": a.tenant_id, "account_id": a.id, "act_id": a.act_id,
                         "fb_credential_id": a.fb_credential_id, "reason": reason})
    _issue("account_dangling_cred", True, rows)

    # ④ account_fb_credentials：悬挂（account/cred 已删）/ 租户错位 / status 非法
    dangling, mismatch, bad_status = [], [], []
    for r in afcs:
        a, c = acct_by_id.get(r.account_id), cred_by_id.get(r.fb_credential_id)
        if a is None or c is None:
            dangling.append({"tenant_id": r.tenant_id, "id": r.id,
                             "account_id": r.account_id, "fb_credential_id": r.fb_credential_id,
                             "reason": "missing_account" if a is None else "missing_cred"})
        elif a.tenant_id != r.tenant_id or c.tenant_id != r.tenant_id:
            mismatch.append({"tenant_id": r.tenant_id, "id": r.id,
                             "account_id": r.account_id, "fb_credential_id": r.fb_credential_id})
        if (r.status or "") not in _AFC_STATUS_ENUM:
            bad_status.append({"tenant_id": r.tenant_id, "id": r.id, "status": r.status})
    _issue("afc_dangling", True, dangling)
    _issue("afc_tenant_mismatch", True, mismatch)
    _issue("afc_bad_status", False, bad_status)

    # ⑤ token_health 悬挂（凭证已删）
    _issue("token_health_dangling", True, [
        {"tenant_id": th.tenant_id, "id": th.id, "fb_credential_id": th.fb_credential_id}
        for th in ths if th.fb_credential_id not in cred_by_id])

    # ⑥ accounts.act_id 空/空白（只报告：修复需人工判断，清了会丢历史关联）
    _issue("account_empty_actid", False, [
        {"tenant_id": a.tenant_id, "id": a.id, "name": a.name}
        for a in accounts if not (a.act_id or "").strip()])

    # ── TikTok 侧（照 FB 思路简化 4 类）──
    from ..models.tt import TtCredential, AccountTtCredential
    tt_creds = db.query(TtCredential).all()
    ttcs = db.query(AccountTtCredential).all()
    tt_cred_by_id = {c.id: c for c in tt_creds}
    _TT_CRED_STATUS_ENUM = ("active", "invalid", "expired")
    _ATC_STATUS_ENUM = ("active", "disabled")

    # ⑦ tt_credentials.status 非法（写路径只产 active/invalid/expired）
    _issue("tt_cred_bad_status", False, [
        {"tenant_id": c.tenant_id, "id": c.id, "alias": c.alias, "status": c.status}
        for c in tt_creds if (c.status or "") not in _TT_CRED_STATUS_ENUM])

    # ⑧ accounts.tt_credential_id 悬挂：指向已删/跨租户 TT 令牌
    rows = []
    for a in accounts:
        if not a.tt_credential_id:
            continue
        c = tt_cred_by_id.get(a.tt_credential_id)
        reason = "missing_cred" if c is None else (
            "cross_tenant" if c.tenant_id != a.tenant_id else None)
        if reason:
            rows.append({"tenant_id": a.tenant_id, "account_id": a.id, "act_id": a.act_id,
                         "tt_credential_id": a.tt_credential_id, "reason": reason})
    _issue("tt_account_dangling_cred", True, rows)

    # ⑨ account_tt_credentials 悬挂/租户错位（reason 区分；⑩ status 非法只报告）
    dangling, bad_status = [], []
    for r in ttcs:
        a, c = acct_by_id.get(r.account_id), tt_cred_by_id.get(r.tt_credential_id)
        if a is None or c is None:
            dangling.append({"tenant_id": r.tenant_id, "id": r.id,
                             "account_id": r.account_id, "tt_credential_id": r.tt_credential_id,
                             "reason": "missing_account" if a is None else "missing_cred"})
        elif a.tenant_id != r.tenant_id or c.tenant_id != r.tenant_id:
            dangling.append({"tenant_id": r.tenant_id, "id": r.id,
                             "account_id": r.account_id, "tt_credential_id": r.tt_credential_id,
                             "reason": "tenant_mismatch"})
        if (r.status or "") not in _ATC_STATUS_ENUM:
            bad_status.append({"tenant_id": r.tenant_id, "id": r.id, "status": r.status})
    _issue("ttc_dangling", True, dangling)
    _issue("ttc_bad_status", False, bad_status)

    return {
        "totals": {"credentials": len(creds), "accounts": len(accounts),
                   "account_fb_credentials": len(afcs), "token_health": len(ths),
                   "tt_credentials": len(tt_creds), "account_tt_credentials": len(ttcs)},
        "issues": issues,
        "cleanable": sum(v["count"] for v in issues.values() if v["cleanable"]),
    }


@router.get("/credentials/data-health")
def credentials_data_health(user: CurrentUser = Depends(require_superadmin),
                            db: Session = Depends(get_system_db)):
    """超管诊断：全平台令牌/账户关联表脏数据扫描（只读，列出计数+明细摘要）。"""
    return _scan_token_data_health(db)


@router.post("/credentials/data-clean")
def credentials_data_clean(user: CurrentUser = Depends(require_superadmin),
                           db: Session = Depends(get_system_db)):
    """超管手动清理（幂等，可重复执行；不删令牌/账户本身）：
    - account_fb_credentials：account 或 cred 已删、或租户错位 → 删行
    - token_health：凭证已删 → 删行
    - accounts.fb_credential_id 悬挂（已删/跨租户）→ 置 NULL（重绑由 reassociate 孤儿自愈兜底）
    - fb_credentials.token_type 引号/大小写脏值 → 归一（真非法值不动，留在 data-health 报告）
    status 非法值与空 act_id 只报告不自动改（需人工判断）。变更按租户写 action_logs。"""
    from ..models.fb import TokenHealth
    from ..core.log_utils import write_log, new_trace_id

    cred_tenant = dict(db.query(FbCredential.id, FbCredential.tenant_id).all())
    acct_tenant = dict(db.query(Account.id, Account.tenant_id).all())

    changes: dict[int, dict] = {}  # tenant_id -> 各类变更计数（写日志用）

    def _hit(tid: int, key: str):
        ch = changes.setdefault(tid, {})
        ch[key] = ch.get(key, 0) + 1

    # ① 悬挂/错位的多令牌关联行 → 删
    for r in db.query(AccountFbCredential).all():
        a_t = acct_tenant.get(r.account_id)
        c_t = cred_tenant.get(r.fb_credential_id)
        if a_t is None or c_t is None or a_t != r.tenant_id or c_t != r.tenant_id:
            db.delete(r)
            _hit(r.tenant_id, "afc_deleted")

    # ② 悬挂的 token_health 行 → 删
    for th in db.query(TokenHealth).all():
        if th.fb_credential_id not in cred_tenant:
            db.delete(th)
            _hit(th.tenant_id, "token_health_deleted")

    # ③ 账户主令牌悬挂 → 置 NULL
    for a in db.query(Account).filter(Account.fb_credential_id.isnot(None)).all():
        if cred_tenant.get(a.fb_credential_id) != a.tenant_id:
            a.fb_credential_id = None
            _hit(a.tenant_id, "primary_cred_nulled")

    # ④ token_type 引号/大小写脏值或 NULL → 归一（归一后仍非枚举的不动，留在报告）
    for c in db.query(FbCredential).all():
        raw = c.token_type or ""
        norm = raw.strip().strip("'\"").lower() or "user"  # NULL/空白 → 模型默认（写权限仍以 scope 快照为准）
        if norm in _TOKEN_TYPE_ENUM and norm != raw:
            c.token_type = norm
            _hit(c.tenant_id, "token_type_normalized")

    # ⑤ TikTok：悬挂/错位 account_tt_credentials → 删；账户 TT 主令牌悬挂 → 置 NULL
    #    （同 ①③ 语义；TT status 非法值只报告不自动改）
    from ..models.tt import TtCredential, AccountTtCredential
    tt_cred_tenant = dict(db.query(TtCredential.id, TtCredential.tenant_id).all())
    for r in db.query(AccountTtCredential).all():
        a_t = acct_tenant.get(r.account_id)
        c_t = tt_cred_tenant.get(r.tt_credential_id)
        if a_t is None or c_t is None or a_t != r.tenant_id or c_t != r.tenant_id:
            db.delete(r)
            _hit(r.tenant_id, "ttc_deleted")
    for a in db.query(Account).filter(Account.tt_credential_id.isnot(None)).all():
        if tt_cred_tenant.get(a.tt_credential_id) != a.tenant_id:
            a.tt_credential_id = None
            _hit(a.tenant_id, "tt_primary_cred_nulled")

    result = {"afc_deleted": sum(ch.get("afc_deleted", 0) for ch in changes.values()),
              "token_health_deleted": sum(ch.get("token_health_deleted", 0) for ch in changes.values()),
              "primary_cred_nulled": sum(ch.get("primary_cred_nulled", 0) for ch in changes.values()),
              "token_type_normalized": sum(ch.get("token_type_normalized", 0) for ch in changes.values()),
              "ttc_deleted": sum(ch.get("ttc_deleted", 0) for ch in changes.values()),
              "tt_primary_cred_nulled": sum(ch.get("tt_primary_cred_nulled", 0) for ch in changes.values())}
    result["cleaned_total"] = sum(result.values())

    if changes:
        trace_id = new_trace_id()
        for tid, ch in changes.items():
            write_log(db, tenant_id=tid, trace_id=trace_id, actor_type="user",
                      actor_user_id=user.id, target_type="fb_credential", target_id="data_clean",
                      action_type="data_clean", source="admin", result="success",
                      trigger_detail=json.dumps(ch, ensure_ascii=False))
        db.commit()
    return result
