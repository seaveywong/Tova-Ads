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
):
    """站内信列表（角色订阅过滤 + 级别/未读 + 日期范围，RLS 隔离）。

    决策①：只看自己角色订阅的（notification.roles 空=全员，否则含自己角色才看）。
    日期：date_preset/date_from/date_to → 业务日（北京）→ UTC 窗口（照 dashboard.py）。
    """
    from sqlalchemy import or_, func
    from datetime import datetime, timezone, timedelta
    BIZ_TZ = timezone(timedelta(hours=8))
    query = db.query(Notification).filter(Notification.tenant_id == user.tenant_id)
    # 日期范围（业务日 → UTC 窗口，照 dashboard pause 逻辑）
    biz_today = datetime.now(BIZ_TZ).strftime("%Y-%m-%d")
    if date_from and date_to:
        since, until = date_from, date_to
    elif date_preset == "yesterday":
        since = until = (datetime.now(BIZ_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
    elif date_preset == "last_2d":
        since = (datetime.now(BIZ_TZ) - timedelta(days=1)).strftime("%Y-%m-%d"); until = biz_today
    elif date_preset == "last_7d":
        since = (datetime.now(BIZ_TZ) - timedelta(days=7)).strftime("%Y-%m-%d"); until = biz_today
    elif date_preset == "last_30d":
        since = (datetime.now(BIZ_TZ) - timedelta(days=30)).strftime("%Y-%m-%d"); until = biz_today
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
    notifs = query.order_by(Notification.created_at.desc()).limit(100).all()
    return [
        {"id": n.id, "level": n.level, "event_type": n.event_type,
         "title": n.title, "body": n.body, "read": n.read_at is not None,
         "roles": n.roles, "created_at": str(n.created_at), "trace_id": n.trace_id}
        for n in notifs
    ]


@router.get("/unread-count")
def unread_count(
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """未读数（顶栏红点用）。"""
    count = db.query(Notification).filter(
        Notification.tenant_id == user.tenant_id,
        Notification.read_at == None,  # noqa: E711
    ).count()
    return {"unread": count}


@router.post("/read")
def mark_read(
    body: dict,
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """标记已读（ids 列表 or all）。"""
    ids = body.get("ids")
    query = db.query(Notification).filter(
        Notification.tenant_id == user.tenant_id,
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
    bot_token: str
    chat_id: str


@router.post("/tg/user-binding")
def set_user_tg_binding(
    body: UserTgBindingIn,
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """用户绑自己的 TG（决策③）。告警按角色推到对应用户的绑定。"""
    from ..models.notify import UserTgBinding
    existing = db.query(UserTgBinding).filter(
        UserTgBinding.tenant_id == user.tenant_id,
        UserTgBinding.user_id == user.id,
    ).first()
    if existing:
        existing.bot_token_enc = encrypt(body.bot_token)
        existing.chat_id = body.chat_id
        existing.verified_at = None
    else:
        db.add(UserTgBinding(tenant_id=user.tenant_id, user_id=user.id,
                             bot_token_enc=encrypt(body.bot_token), chat_id=body.chat_id))
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
