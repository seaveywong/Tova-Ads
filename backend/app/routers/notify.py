"""通知路由：站内信列表/已读/未读数 + TG 绑定/测试（doc 06）。"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from ..core.database import get_db, get_system_db
from ..core.deps import CurrentUser, require_permission
from ..core.encryption import encrypt, decrypt
from ..core.notify_utils import _tg_send
from ..models.notify import Notification, TenantTgBinding
import httpx

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
    level: str | None = None,
    unread_only: bool = False,
    date_preset: str = "",
    date_from: str = "",
    date_to: str = "",
    platform: str = "",  # all/空=不过滤；fb/tt=只看该平台告警（历史无 platform 行按 fb 口径）
    offset: int = 0,
    limit: int = 100,
):
    """站内信列表（角色订阅过滤 + 级别/未读 + 日期范围，RLS 隔离）。

    决策①：只看自己角色订阅的（notification.roles 空=全员，否则含自己角色才看）。
    日期：date_preset/date_from/date_to → 业务日（北京）→ UTC 窗口（照 dashboard.py）。
    """
    from sqlalchemy import or_, func
    from datetime import datetime, timezone, timedelta
    BIZ_TZ = timezone(timedelta(hours=8))
    query = db.query(Notification).filter(Notification.tenant_id == user.tenant_id)
    if platform in ("fb", "tt"):
        query = query.filter(Notification.platform == platform)
    # 日期范围（业务日 → UTC 窗口，照 dashboard pause 逻辑）
    biz_today = datetime.now(BIZ_TZ).strftime("%Y-%m-%d")
    if date_from and date_to:
        since, until = date_from, date_to
    elif date_preset == "yesterday":
        since = until = (datetime.now(BIZ_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
    elif date_preset == "last_2d":
        since = (datetime.now(BIZ_TZ) - timedelta(days=1)).strftime("%Y-%m-%d"); until = biz_today
    elif date_preset == "last_7d":
        since = (datetime.now(BIZ_TZ) - timedelta(days=6)).strftime("%Y-%m-%d"); until = biz_today
    elif date_preset == "last_30d":
        since = (datetime.now(BIZ_TZ) - timedelta(days=29)).strftime("%Y-%m-%d"); until = biz_today
    elif date_preset:
        since = until = biz_today
    else:
        since = until = ""
    if since and until:
        utc_start = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=BIZ_TZ).astimezone(timezone.utc)
        utc_end = datetime.strptime(until, "%Y-%m-%d").replace(tzinfo=BIZ_TZ).astimezone(timezone.utc) + timedelta(days=1)
        query = query.filter(Notification.created_at >= utc_start, Notification.created_at < utc_end)
    # 角色订阅过滤
    role = (user.role or "owner").lower()
    padded = func.concat(",", func.coalesce(Notification.roles, ""), ",")
    query = query.filter(or_(
        Notification.roles.is_(None),
        Notification.roles == "",
        padded.like(f"%,{role},%"),
    ))
    if level:
        query = query.filter(Notification.level == level)
    if unread_only:
        query = query.filter(Notification.read_at == None)  # noqa: E711
    notifs = query.order_by(Notification.created_at.desc()).limit(limit).offset(offset).all()
    total = query.count()
    return {
        "items": [
            {"id": n.id, "level": n.level, "event_type": n.event_type,
             "title": n.title, "body": n.body, "read": n.read_at is not None,
             "roles": n.roles, "created_at": str(n.created_at), "trace_id": n.trace_id}
            for n in notifs
        ],
        "total": total, "offset": offset, "limit": limit,
        "has_more": offset + len(notifs) < total,
    }


def _visible_scope(user, db):
    """该用户可见通知的过滤条件（与 list 同口径：只算自己角色订阅的）。"""
    from sqlalchemy import or_, func
    role = (user.role or "owner").lower()
    padded = func.concat(",", func.coalesce(Notification.roles, ""), ",")
    return db.query(Notification).filter(
        Notification.tenant_id == user.tenant_id,
        or_(
            Notification.roles.is_(None),
            Notification.roles == "",
            padded.like(f"%,{role},%"),
        ),
    )


@router.get("/unread-count")
def unread_count(
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """未读数（顶栏红点用）——与列表同口径（只数自己角色可见的）。"""
    return {"unread": _visible_scope(user, db).filter(
        Notification.read_at == None,  # noqa: E711
    ).count()}


@router.post("/read")
def mark_read(
    body: dict,
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """标记已读（ids 列表 or all）。只影响该用户可见口径——批量已读不清掉
    定向发别的角色（如 finance）的告警红点。"""
    ids = body.get("ids")
    query = _visible_scope(user, db).filter(
        Notification.read_at == None,  # noqa: E711
    )
    if ids:
        query = query.filter(Notification.id.in_(ids))
    query.update({Notification.read_at: datetime.now(timezone.utc)}, synchronize_session="fetch")
    db.commit()
    return {"marked": True}


# ── TG 绑定 ──
class TgBindingIn(BaseModel):
    bot_token: str
    chat_id: str


@router.post("/tg/binding")
def set_tg_binding(
    body: TgBindingIn,
    user: CurrentUser = Depends(require_permission("members.manage")),
    db: Session = Depends(get_db),
):
    """绑/换 TG bot（加密存 bot_token）。Owner 专用。"""
    existing = db.query(TenantTgBinding).filter(
        TenantTgBinding.tenant_id == user.tenant_id,
    ).first()
    if existing:
        existing.bot_token_enc = encrypt(body.bot_token)
        existing.chat_id = body.chat_id
        existing.verified_at = None
    else:
        binding = TenantTgBinding(
            tenant_id=user.tenant_id,
            bot_token_enc=encrypt(body.bot_token),
            chat_id=body.chat_id,
        )
        db.add(binding)
    db.commit()
    return {"status": "saved"}


@router.post("/tg/test")
def test_tg(
    user: CurrentUser = Depends(require_permission("members.manage")),
    db: Session = Depends(get_db),
):
    """发测试消息验证 TG 绑定（租户级）。"""
    binding = db.query(TenantTgBinding).filter(
        TenantTgBinding.tenant_id == user.tenant_id,
    ).first()
    if not binding:
        raise HTTPException(400, "未绑定 TG")
    try:
        _tg_send(decrypt(binding.bot_token_enc), binding.chat_id,
                 "[Tova Ads 🔵]\n租户级 TG 测试\n绑定成功！")
        binding.verified_at = datetime.now(timezone.utc)
        db.commit()
        return {"status": "sent"}
    except Exception as e:
        raise HTTPException(400, f"发送失败：{e}")


# ── 用户级 TG 绑定（决策③，每人绑自己的 TG）──
class UserTgBindingIn(BaseModel):
    bot_token: str = ""   # 空 = 解绑语义（chat_id 也空时删行）或复用现有绑定 token
    chat_id: str


@router.post("/tg/user-binding")
def set_user_tg_binding(
    body: UserTgBindingIn,
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """用户绑自己的 TG（决策③）。告警按角色推到对应用户的绑定。"""
    from ..models.notify import UserTgBinding
    # 占位 bot '__use_tenant_bot__' → 解析成租户真 bot（否则发送时 token 无效，绑了也收不到告警）
    real_bot = body.bot_token
    if real_bot == '__use_tenant_bot__':
        tb = db.query(TenantTgBinding).filter(
            TenantTgBinding.tenant_id == user.tenant_id).first()
        real_bot = decrypt(tb.bot_token_enc) if tb else body.bot_token
    # 解绑语义：chat_id 空 = 删行（原只更新空串——行还在=GET 判 bound=true，
    # 卡片仍显已绑定、告警继续发往空 chat_id 必失败）
    if body.chat_id == "":
        db.query(UserTgBinding).filter(
            UserTgBinding.tenant_id == user.tenant_id,
            UserTgBinding.user_id == user.id,
        ).delete()
        db.commit()
        return {"status": "deleted", "user_id": user.id}
    existing = db.query(UserTgBinding).filter(
        UserTgBinding.tenant_id == user.tenant_id,
        UserTgBinding.user_id == user.id,
    ).first()
    # bot_token 留空 = 不换 bot（复用现有绑定的 token——TG 解绑/重绑 chat_id 场景）
    _tok_to_store = real_bot if real_bot else None
    if existing:
        if _tok_to_store:
            existing.bot_token_enc = encrypt(_tok_to_store)
        existing.chat_id = body.chat_id
        existing.verified_at = None
    else:
        if not _tok_to_store:
            raise HTTPException(400, "缺少 bot_token")
        db.add(UserTgBinding(tenant_id=user.tenant_id, user_id=user.id,
                             bot_token_enc=encrypt(_tok_to_store), chat_id=body.chat_id))
    db.commit()
    return {"status": "saved", "user_id": user.id}


@router.get("/tg/user-binding")
def get_user_tg_binding(
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """查当前用户的 TG 绑定（chat_id 打码）。"""
    from ..models.notify import UserTgBinding
    b = db.query(UserTgBinding).filter(
        UserTgBinding.tenant_id == user.tenant_id,
        UserTgBinding.user_id == user.id,
    ).first()
    if not b:
        return {"bound": False}
    cid = b.chat_id
    masked = (cid[:3] + "***" + cid[-3:]) if len(cid) > 8 else "***"
    return {"bound": True, "chat_id_masked": masked, "verified": b.verified_at is not None}


@router.post("/tg/user-test")
def user_tg_test(
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """给当前用户的 TG 绑定发测试消息。"""
    from ..models.notify import UserTgBinding
    from ..core.notify_utils import _tg_send
    b = db.query(UserTgBinding).filter(
        UserTgBinding.tenant_id == user.tenant_id,
        UserTgBinding.user_id == user.id,
    ).first()
    if not b:
        raise HTTPException(400, "你未绑定 TG（POST /notifications/tg/user-binding）")
    try:
        _tg_send(decrypt(b.bot_token_enc), b.chat_id,
                 "[Tova Ads 🔵]\n用户级 TG 测试\n绑定成功！")
        b.verified_at = datetime.now(timezone.utc)
        db.commit()
        return {"status": "sent"}
    except Exception as e:
        raise HTTPException(400, f"发送失败：{e}")


# ── TG OAuth（Telegram Login Widget，用户点击授权→自动绑定，不手填）──
@router.get("/tg/bot-info")
def tg_bot_info(user: CurrentUser = Depends(require_permission("ads.read")),
                db: Session = Depends(get_db)):
    """返 TG bot username（前端 Telegram Login Widget 渲染按钮用）。"""
    import httpx
    tb = db.query(TenantTgBinding).filter(
        TenantTgBinding.tenant_id == user.tenant_id).first()
    if not tb:
        return {"configured": False}
    try:
        resp = httpx.get(
            f"https://api.telegram.org/bot{decrypt(tb.bot_token_enc)}/getMe", timeout=10)
        info = resp.json().get("result", {})
        return {"configured": True, "bot_username": info.get("username", "")}
    except Exception:
        return {"configured": True, "bot_username": ""}


class TgOAuthIn(BaseModel):
    id: int
    first_name: str = ""
    last_name: str = ""
    username: str = ""
    photo_url: str = ""
    auth_date: int
    hash: str


@router.get("/tg/bind-link")
def tg_bind_link(user: CurrentUser = Depends(require_permission("ads.read")),
                 db: Session = Depends(get_db)):
    """生成 TG bot deep link（用户点开 → bot 自动收到 chat_id → webhook 绑定）。"""
    from ..core.security import create_access_token
    import httpx
    tb = db.query(TenantTgBinding).filter(
        TenantTgBinding.tenant_id == user.tenant_id).first()
    if not tb:
        raise HTTPException(400, "管理员未配置 TG Bot")
    # 获取 bot username
    try:
        resp = httpx.get(f"https://api.telegram.org/bot{decrypt(tb.bot_token_enc)}/getMe", timeout=10)
        bot_username = resp.json().get("result", {}).get("username", "")
    except Exception:
        raise HTTPException(500, "获取 Bot 信息失败")
    if not bot_username:
        raise HTTPException(500, "Bot username 为空")
    # 生成绑定 token：专用 type=tg_bind + 10 分钟短效（deep-link 经 TG 服务器/聊天记录传播，
    # 不能复用 7 天 access token——泄露即账号接管）
    bind_token = create_access_token(
        user_id=user.id, email=user.email,
        tenant_id=user.tenant_id, role=user.role,
        is_superadmin=bool(user.is_superadmin),
        token_use="tg_bind", expire_min=10,
    )
    return {"url": f"https://t.me/{bot_username}?start={bind_token}",
            "bot_username": bot_username}


@router.post("/tg/oauth-callback")
def tg_oauth_callback(body: TgOAuthIn,
                      user: CurrentUser = Depends(require_permission("ads.read")),
                      db: Session = Depends(get_db)):
    """Telegram Login Widget OAuth 回调：验 hash → 绑 user_tg_binding（OAuth 式，不手填 bot_token）。

    用租户级 bot_token 验签 → chat_id = Telegram user id。
    """
    import hmac, hashlib, time as _time
    tb = db.query(TenantTgBinding).filter(
        TenantTgBinding.tenant_id == user.tenant_id).first()
    if not tb:
        raise HTTPException(400, "管理员未配置 TG Bot（联系管理员先绑租户 TG）")
    bot_token = decrypt(tb.bot_token_enc)
    # Telegram Login Widget hash 验证：secret=SHA256(bot_token), HMAC-SHA256(data_check_string, secret)
    secret = hashlib.sha256(bot_token.encode()).digest()
    data = body.dict()
    received_hash = data.pop("hash", "")
    data_check = "\n".join(
        f"{k}={v}" for k, v in sorted(data.items()) if v is not None and v != "")
    expected = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if expected != received_hash:
        raise HTTPException(400, "TG 验证失败（hash 不匹配）")
    # auth_date 新鲜（24h 内）
    if _time.time() - body.auth_date > 86400:
        raise HTTPException(400, "TG 登录已过期（超过 24h）")
    # 绑定 UserTgBinding（用租户 bot + Telegram user id 作 chat_id）
    chat_id = str(body.id)
    from ..models.notify import UserTgBinding
    existing = db.query(UserTgBinding).filter(
        UserTgBinding.tenant_id == user.tenant_id,
        UserTgBinding.user_id == user.id,
    ).first()
    if existing:
        existing.chat_id = chat_id
        existing.bot_token_enc = tb.bot_token_enc
        existing.verified_at = datetime.now(timezone.utc)
    else:
        db.add(UserTgBinding(
            tenant_id=user.tenant_id, user_id=user.id,
            bot_token_enc=tb.bot_token_enc, chat_id=chat_id,
            verified_at=datetime.now(timezone.utc),
        ))
    db.commit()
    return {"bound": True, "tg_username": body.username or str(body.id)}
