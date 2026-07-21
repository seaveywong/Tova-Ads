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

    # 设 RLS 会话上下文（在同一事务内，后续查询带 RLS 过滤）
    db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id) if tenant_id is not None else ""})
    db.execute(text("SET LOCAL app.is_superadmin = :s"), {"s": "true" if is_super else "false"})

    role = payload.get("role")
    return CurrentUser(
        id=user.id, email=user.email, tenant_id=tenant_id,
        role=role, is_superadmin=is_super,
        permissions=permissions_for_role(db, tenant_id, role) if tenant_id else set(),
        timezone=user.timezone or "Asia/Shanghai",
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
