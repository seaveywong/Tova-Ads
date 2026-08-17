"""依赖：JWT 解析 + 当前用户 + RBAC + RLS 会话上下文接线。"""
from dataclasses import dataclass
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import text
from sqlalchemy.orm import Session
from .database import get_db
from .security import decode_token
from .permissions import permissions_for_role
from ..models.auth import User

_bearer = HTTPBearer()


@dataclass
class CurrentUser:
    id: int
    email: str
    tenant_id: int | None
    role: str | None
    is_superadmin: bool
    permissions: set[str]
    timezone: str = "Asia/Shanghai"
    locale: str = "zh"


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> CurrentUser:
    """解析 JWT → 校验用户 → 设 RLS 会话上下文（此请求的 db session）。

    SET LOCAL 随事务结束自动清，防泄漏。平台超管用 is_superadmin（v2 接 BYPASSRLS 角色）。
    """
    try:
        payload = decode_token(creds.credentials)
    except Exception:
        raise HTTPException(401, "无效或过期 token")
    if payload.get("type") != "access":
        raise HTTPException(401, "token 类型错误")

    user = db.get(User, payload["user_id"])
    if not user or user.status not in ("active", "must_change_password"):
        raise HTTPException(401, "用户不可用")

    tenant_id = payload.get("tenant_id")
    is_super = bool(payload.get("is_superadmin", False))

    # 复查团队身份（防 JWT 无吊销窗口：被移除/停用团队的 token 立即失效，不等 7 天过期）
    if tenant_id and not is_super:
        from ..models.auth import TenantMembership
        m = db.query(TenantMembership).filter(
            TenantMembership.user_id == user.id,
            TenantMembership.tenant_id == tenant_id,
        ).first()
        if not m:
            raise HTTPException(401, "团队身份已变更，请重新登录")
        if (payload.get("role") or "") != (m.role or ""):
            # 角色已变（升降权）→ 拒旧 token，强制重登拿新角色
            raise HTTPException(401, "角色已变更，请重新登录")

    # 设 RLS 会话上下文。set_config(is_local=false)=会话级：请求中途 commit 后仍生效
    # （SET LOCAL 随事务结束蒸发 → commit 后同 session 查询静默 0 行，曾击穿批量写/紧急暂停/refresh）。
    # 安全性：连接归池走 rollback/reset，会话变量随连接归还被清理，不泄漏到下一请求。
    db.execute(text("SELECT set_config('app.tenant_id', :tid, false)"),
               {"tid": str(tenant_id) if tenant_id is not None else ""})
    db.execute(text("SELECT set_config('app.is_superadmin', :s, false)"),
               {"s": "true" if is_super else "false"})

    role = payload.get("role")
    return CurrentUser(
        id=user.id, email=user.email, tenant_id=tenant_id,
        role=role, is_superadmin=is_super,
        permissions=permissions_for_role(db, tenant_id, role) if tenant_id else set(),
        timezone=user.timezone or "Asia/Shanghai",
        locale=user.locale or "zh",
    )


def require_permission(key: str):
    """RBAC 依赖工厂：检查当前用户是否持有某功能键。超管放行。"""
    def dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.is_superadmin or key in user.permissions:
            return user
        raise HTTPException(403, f"无权限：{key}")
    return dep


def require_superadmin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """严格平台超管依赖（跨租户操作：域名分配/平台监控等）。"""
    if not user.is_superadmin:
        raise HTTPException(403, "需要平台超管权限")
    return user
