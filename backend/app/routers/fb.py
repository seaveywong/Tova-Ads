"""FB 集成路由：绑定凭证 / 拉资产 / 导入账户 / 列账户 / 令牌管理。

所有 FB 调用走 fb_client（总则4），凭证加密存（doc 01 D 节）。
"""
import json
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from ..core.database import get_db
from ..core.deps import CurrentUser, require_permission
from ..core.i18n import req_locale, L
from ..core.encryption import encrypt, decrypt
from ..core.fb_client import FbClient, FbApiError
from ..models.fb import FbCredential, Account, AccountFbCredential
from ..schemas.fb import StoreCredentialIn, FbCredentialOut, ImportAccountsIn

router = APIRouter(prefix="/fb", tags=["fb"])


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

    # 去重：同 tenant + 同 fb_user_id + 同 source → 更新，不重复建
    existing = db.query(FbCredential).filter(
        FbCredential.tenant_id == user.tenant_id,
        FbCredential.fb_user_id == me.get("id"),
    ).first()

    if existing:
        existing.access_token_enc = encrypt(body.access_token)
        existing.alias = body.alias or existing.alias
        existing.status = "active"
        existing.token_type = getattr(body, 'token_type', None) or existing.token_type or "user"
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
            access_token_enc=encrypt(body.access_token),
            fb_user_id=me.get("id"),
            fb_user_name=me.get("name"),
            status="active",
            token_type=getattr(body, 'token_type', None) or "user",
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
        # 临时错误豁免（code 1/2/4/17/32/341/613 不标 expired）
        transient = {"rate_limited", "network", "unknown"}
        if e.category not in transient:
            cred.status = "expired"
        else:
            # 限流（code=17）→ rate_limited + 30min 冷却（学习 1.0 §3.4）
            if e.category == "rate_limited":
                cred.status = "rate_limited"
                cred.cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=30)
            elif cred.consecutive_fails >= 3:
                cred.status = "limited"
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
            "fields": "id,message,attachments{media_type,media{src}},created_time,permalink_url",
            "limit": 100,  # published_posts FB 上限 100（get_paged 默认 200 会 #100）
        })
    except FbApiError as e:
        raise HTTPException(400, e.friendly)
    out = []
    for p in posts:
        atts = (p.get("attachments") or {}).get("data", []) if isinstance(p.get("attachments"), dict) else []
        picture = ""
        if atts and isinstance(atts[0], dict):
            picture = (atts[0].get("media") or {}).get("src", "")
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


def _fetch_post_content(db: Session, tenant_id: int, post_id: str) -> dict:
    """取帖子内容(文案/图/链接)供跟帖预览。
    ① page_posts 本地(系统建过的帖，含 message+asset 图)
    ② ads_cache creative.object_story_spec（暗帖——广告帖大多是暗帖，published_posts 读不到；
       但同步广告时拉了 object_story_spec，含 link_data/video_data 的文案+图）
    ③ FB published_posts 边(有机帖，page token——GET /{post_id} 节点对主页帖常权限不足，边才行)。
    都取不到→空 dict（前端显"无法读取"）。"""
    import json as _json
    from ..models.page_post import PagePost
    from ..models.launch import Asset
    from ..models.ads_cache import AdsCache
    from ..core.fb_tokens import iter_tenant_clients
    post_suffix = post_id.split("_")[-1] if "_" in post_id else post_id
    # ① 本地 page_posts（系统帖：message + asset 图）。视频帖无图 → 只留 message 继续往下取缩略图。
    pp_msg = ""; pp = db.query(PagePost).filter(PagePost.post_id == post_id).first()
    if pp:
        pp_msg = pp.message or ""
        if pp.asset_id:
            a = db.query(Asset).filter(Asset.id == pp.asset_id).first()
            if a and a.type == "image" and a.public_url:
                return {"message": pp_msg, "headline": "", "picture": a.public_url, "cta_type": "", "permalink_url": ""}
    # ② ads_cache 定位 creative_id → 实时 GET /{creative_id} 拿真实内容+缩略图（不靠缓存陈旧字段；
    #    缓存常缺 thumbnail_url，实时拉才有图）。暗帖主场景。
    creative_id = ""
    cached = {}
    for row in db.query(AdsCache).filter(AdsCache.tenant_id == tenant_id).all():
        try:
            ads = _json.loads(row.ads_json or "[]")
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
        return {"message": pp_msg, "headline": "", "picture": "", "cta_type": "", "permalink_url": ""} if pp_msg else {}
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
                        "cta_type": "", "permalink_url": p.get("permalink_url", "")}
        break  # 该令牌管此主页但 published_posts 里没这条（暗帖/已删）→ 不再试别的令牌
    # 都没图：至少返 page_posts 的 message（若有），比空好
    return {"message": pp_msg, "headline": "", "picture": "", "cta_type": "", "permalink_url": ""} if pp_msg else {}


@router.post("/resolve-post")
def resolve_post(body: ResolvePostIn,
                 user: CurrentUser = Depends(require_permission("ads.create")),
                 db: Session = Depends(get_db)):
    """帖子 ID/URL → 主页 + 完整 post_id + 内容预览(文案/图/链接)。供跟帖手动输入。
    顺序：完整 {page}_{post} 直接拆 → 本地 ads_cache 反查 → FB 遍历令牌兜底。
    统一返回 {page_id, post_id, source, message, picture, permalink_url}（内容尽力取，无权访问则空）。"""
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
    return {"page_id": page_id, "post_id": post_id, "source": source,
            "message": content.get("message", ""), "headline": content.get("headline", ""),
            "picture": content.get("picture", ""), "cta_type": content.get("cta_type", ""),
            "link": content.get("link", ""), "permalink_url": content.get("permalink_url", "")}



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
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """全部令牌的资产计数：账户(DB 已导入) + 主页/BM(FB)。像素不在此列。"""
    creds = db.query(FbCredential).filter(
        FbCredential.tenant_id == user.tenant_id, FbCredential.status == "active"
    ).all()
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
            tasks = b.get("permitted_tasks", []) or []
            role = "完全" if "MANAGE" in tasks else "基本"
            businesses.append({"id": b.get("id", ""), "name": b.get("name", ""), "role": role})
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
        fb_accounts = fb.get_ad_accounts()
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
        except FbApiError:
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
    """
    from ..core.fb_tokens import _is_cred_available
    creds = db.query(FbCredential).filter(
        FbCredential.tenant_id == user.tenant_id, FbCredential.status == "active"
    ).all()
    imported_ids = {a.act_id for a in db.query(Account).filter(
        Account.tenant_id == user.tenant_id, Account.is_managed == True  # noqa: E712
    ).all()}
    merged: dict = {}
    for c in creds:
        fb = FbClient(decrypt(c.access_token_enc))
        avail = _is_cred_available(c)
        try:
            for a in fb.get_ad_accounts():
                aid = a.get("account_id", "")
                if not aid or not a.get("name"):
                    continue  # 无 ID 或 FB 未返回 name（管不了/无意义）→ 不进载入列表
                if aid not in merged:
                    merged[aid] = {
                        "account_id": aid, "name": a.get("name", aid),
                        "currency": a.get("currency", "USD"),
                        "account_status": a.get("account_status"),
                        "imported": aid in imported_ids,
                        "tokens": [],
                    }
                merged[aid]["tokens"].append(
                    {"id": c.id, "alias": c.alias or c.fb_user_name, "available": avail})
        except FbApiError:
            continue
    return list(merged.values())


@router.post("/import")
def import_accounts(
    body: ImportAccountsIn,
    user: CurrentUser = Depends(require_permission("ads.create")),
    db: Session = Depends(get_db),
):
    """导入广告账户（手动选择）。输入自动清洗：去 act_ 前缀、去空格、去重；跳过已存在。

    返回 {imported, skipped_existing, not_found, total}：
    - imported: 新导入的 act_id
    - skipped_existing: 已存在（含重绑到新 token）
    - not_found: 无任何 active token 覆盖的 ID
    """
    from ..core.fb_tokens import iter_tenant_clients
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
    cleaned_set = set(cleaned)
    pairs = iter_tenant_clients(db, user.tenant_id)
    if not pairs:
        raise HTTPException(400, "未绑定 FB 凭证")
    imported: list[str] = []
    skipped_existing = 0
    covered: set = set()
    for cred, fb in pairs:
        try:
            token_accounts = fb.get_ad_accounts()
        except FbApiError:
            continue
        for acc in token_accounts:
            aid = acc.get("account_id", "")
            if aid not in cleaned_set:
                continue
            covered.add(aid)
            exists = db.query(Account).filter(
                Account.tenant_id == user.tenant_id,
                Account.act_id == aid,
            ).first()
            if exists:
                if exists.fb_credential_id != cred.id:
                    exists.fb_credential_id = cred.id
                exists.is_managed = True  # 重新导入 = 恢复纳管（把软删的拉回活跃管理）
                # 多令牌同账户：加 account_fb_credentials 关联（已有则跳过 → 多 token 共管）
                if not db.query(AccountFbCredential).filter(
                    AccountFbCredential.account_id == exists.id,
                    AccountFbCredential.fb_credential_id == cred.id,
                ).first():
                    db.add(AccountFbCredential(
                        tenant_id=user.tenant_id, account_id=exists.id,
                        fb_credential_id=cred.id, priority=0, status="active",
                    ))
                skipped_existing += 1
                continue
            new_acc = Account(
                tenant_id=user.tenant_id,
                fb_credential_id=cred.id,
                act_id=aid,
                name=acc.get("name") or "",
                currency=acc.get("currency", "USD"),
                timezone_name=acc.get("timezone_name", "UTC"),
                owner_user_id=user.id,
                account_status=acc.get("account_status", 1),
                balance=str(acc.get("balance", "") or ""),
                spend_cap=str(acc.get("spend_cap", "") or ""),
                amount_spent=str(acc.get("amount_spent", "") or ""),
            )
            db.add(new_acc)
            db.flush()  # 拿 new_acc.id 用于关联
            db.add(AccountFbCredential(
                tenant_id=user.tenant_id, account_id=new_acc.id,
                fb_credential_id=cred.id, priority=0, status="active",
            ))
            imported.append(aid)
    db.commit()
    not_found = sorted(cleaned_set - covered)
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
            "timezone": a.timezone_name, "account_status": a.account_status,
            "is_managed": a.is_managed if a.is_managed is not None else True,
            "warmup_state": a.warmup_state or "none",
            "balance": bal, "balance_usd": round(to_usd(bal, cur), 2) if bal is not None else None,
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
    acc.is_managed = False
    # 清哨兵/预热状态：取消纳管后不应再被哨兵停广告；恢复纳管时也不会带着旧 armed 立刻被停
    acc.sentinel_armed = False
    acc.sentinel_auto_armed = False
    acc.warmup_state = "none"
    # 清该账户的 ads_cache（广告管理器读它——不清则移除后仍显示陈旧广告列表）。
    # perf_snapshots 保留（历史消耗数据不丢，dashboard/报表仍可查）。
    try:
        from ..models.ads_cache import AdsCache
        db.query(AdsCache).filter(
            AdsCache.tenant_id == user.tenant_id, AdsCache.act_id == aid).delete()
    except Exception:
        pass
    db.commit()
    return {"unmanaged": True, "act_id": aid}
