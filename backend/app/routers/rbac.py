"""RBAC 路由：角色 CRUD + 成员管理（邀请/改角色/移除）。

权限矩阵 16 个 key（ALL_PERMISSIONS），任意组合 = 自定义角色。
系统预置角色（owner/operator/finance）可改权限不可删。
"""
import secrets as _secrets
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel
from ..core.database import get_db
from ..core.deps import CurrentUser, require_permission
from ..core.config import settings
from ..core.security import hash_password, create_access_token
from ..models.auth import Role, TenantMembership, User, Invitation
from ..core.permissions import ALL_PERMISSIONS, PERMISSION_GROUPS

router = APIRouter(prefix="/rbac", tags=["rbac"])


# ── 角色 CRUD ──

class RoleIn(BaseModel):
    name: str
    description: str = ""
    permissions: list[str] = []


@router.get("/roles")
def list_roles(user: CurrentUser = Depends(require_permission("members.manage")),
               db: Session = Depends(get_db)):
    """列本租户所有角色 + 每个角色下的人数。"""
    roles = db.query(Role).filter(Role.tenant_id == user.tenant_id).order_by(Role.id).all()
    # 统计每个角色的人数
    counts = {}
    for r in db.query(TenantMembership.role, text("count(*)")).filter(
        TenantMembership.tenant_id == user.tenant_id
    ).group_by(TenantMembership.role).all():
        counts[r[0]] = r[1]
    return [{
        "id": r.id, "name": r.name, "description": r.description or "",
        "permissions": r.permissions or [], "is_system": r.is_system,
        "member_count": counts.get(r.name, 0),
    } for r in roles]


@router.get("/permission-groups")
def get_permission_groups(user: CurrentUser = Depends(require_permission("members.manage"))):
    """权限矩阵（供前端渲染勾选框）。"""
    return {"groups": PERMISSION_GROUPS, "all_keys": ALL_PERMISSIONS}


@router.post("/roles")
def create_role(body: RoleIn,
                user: CurrentUser = Depends(require_permission("members.manage")),
                db: Session = Depends(get_db)):
    """新建自定义角色。"""
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "角色名不能为空")
    if name in ("owner", "superadmin"):
        raise HTTPException(400, "该名称为系统保留")
    exists = db.query(Role).filter(Role.tenant_id == user.tenant_id, Role.name == name).first()
    if exists:
        raise HTTPException(400, "角色名已存在")
    # 校验权限 key 合法
    invalid = set(body.permissions) - set(ALL_PERMISSIONS)
    if invalid:
        raise HTTPException(400, f"未知权限: {invalid}")
    role = Role(tenant_id=user.tenant_id, name=name, description=body.description,
                permissions=body.permissions, is_system=False)
    db.add(role)
    db.commit()
    return {"id": role.id, "name": role.name, "created": True}


@router.put("/roles/{role_id}")
def update_role(role_id: int, body: RoleIn,
                user: CurrentUser = Depends(require_permission("members.manage")),
                db: Session = Depends(get_db)):
    """改角色（权限矩阵 + 名称 + 描述）。系统角色可改权限不可改名。"""
    role = db.query(Role).filter(Role.id == role_id, Role.tenant_id == user.tenant_id).first()
    if not role:
        raise HTTPException(404, "角色不存在")
    if role.name == "owner" and role.is_system:
        # owner 权限不可减（防止把自己锁死）
        if not set(ALL_PERMISSIONS).issubset(set(body.permissions)):
            raise HTTPException(400, "owner 角色必须保留全部权限")
    invalid = set(body.permissions) - set(ALL_PERMISSIONS)
    if invalid:
        raise HTTPException(400, f"未知权限: {invalid}")
    if not role.is_system:
        new_name = body.name.strip()
        if new_name and new_name != role.name:
            conflict = db.query(Role).filter(
                Role.tenant_id == user.tenant_id, Role.name == new_name, Role.id != role_id
            ).first()
            if conflict:
                raise HTTPException(400, "角色名已存在")
            role.name = new_name
    role.description = body.description
    role.permissions = body.permissions
    role.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"updated": True}


@router.delete("/roles/{role_id}")
def delete_role(role_id: int,
                user: CurrentUser = Depends(require_permission("members.manage")),
                db: Session = Depends(get_db)):
    """删自定义角色（系统角色不可删；有人在使用不可删）。"""
    role = db.query(Role).filter(Role.id == role_id, Role.tenant_id == user.tenant_id).first()
    if not role:
        raise HTTPException(404, "角色不存在")
    if role.is_system:
        raise HTTPException(400, "系统角色不可删除")
    in_use = db.query(TenantMembership).filter(
        TenantMembership.tenant_id == user.tenant_id, TenantMembership.role == role.name
    ).first()
    if in_use:
        raise HTTPException(400, "该角色下仍有成员，请先转移或移除")
    db.delete(role)
    db.commit()
    return {"deleted": True}


# ── 成员管理 ──

@router.get("/members")
def list_members(user: CurrentUser = Depends(require_permission("members.manage")),
                 db: Session = Depends(get_db)):
    """列本租户所有成员 + 角色。"""
    memberships = db.query(TenantMembership).filter(
        TenantMembership.tenant_id == user.tenant_id
    ).all()
    user_ids = [m.user_id for m in memberships]
    users_map = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}
    roles_map = {r.name: r for r in db.query(Role).filter(Role.tenant_id == user.tenant_id).all()}
    return [{
        "membership_id": m.id,
        "user_id": m.user_id,
        "email": users_map[m.user_id].email if m.user_id in users_map else "?",
        "status": users_map[m.user_id].status if m.user_id in users_map else "?",
        "role": m.role,
        "is_you": m.user_id == user.id,
        "created_at": m.created_at.isoformat() if m.created_at else "",
    } for m in memberships]


class InviteIn(BaseModel):
    email: str
    password: str = ""
    role: str = "operator"


@router.post("/members/invite")
def invite_member(body: InviteIn,
                  user: CurrentUser = Depends(require_permission("members.invite")),
                  db: Session = Depends(get_db)):
    """直接邀请新成员（建用户 + 加 membership）。"""
    email = body.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "邮箱格式不对")
    # 校验角色存在
    role = db.query(Role).filter(
        Role.tenant_id == user.tenant_id, Role.name == body.role
    ).first()
    if not role:
        raise HTTPException(400, f"角色 '{body.role}' 不存在")
    # 建用户（或复用已有）
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        # 已有用户：检查是否已在本租户
        m = db.query(TenantMembership).filter(
            TenantMembership.tenant_id == user.tenant_id, TenantMembership.user_id == existing.id
        ).first()
        if m:
            raise HTTPException(400, "该用户已是本团队成员")
        db.add(TenantMembership(tenant_id=user.tenant_id, user_id=existing.id, role=body.role))
        db.commit()
        return {"invited": True, "email": email, "existing_user": True}
    # 新用户
    import secrets as _sec
    pwd = body.password.strip() or _sec.token_urlsafe(8)  # 随机默认密码，更安全
    new_user = User(email=email, password_hash=hash_password(pwd), status="must_change_password")
    db.add(new_user)
    db.flush()
    db.add(TenantMembership(tenant_id=user.tenant_id, user_id=new_user.id, role=body.role))
    db.commit()
    return {"invited": True, "email": email, "default_password": pwd}


class ChangeRoleIn(BaseModel):
    role: str


@router.put("/members/{membership_id}/role")
def change_member_role(membership_id: int, body: ChangeRoleIn,
                       user: CurrentUser = Depends(require_permission("members.manage")),
                       db: Session = Depends(get_db)):
    """改成员角色。"""
    m = db.query(TenantMembership).filter(
        TenantMembership.id == membership_id, TenantMembership.tenant_id == user.tenant_id
    ).first()
    if not m:
        raise HTTPException(404, "成员不存在")
    # 不能改自己的 owner 角色（防锁死）
    if m.user_id == user.id and m.role == "owner" and body.role != "owner":
        raise HTTPException(400, "不能取消自己的 owner 角色")
    role = db.query(Role).filter(
        Role.tenant_id == user.tenant_id, Role.name == body.role
    ).first()
    if not role:
        raise HTTPException(400, f"角色 '{body.role}' 不存在")
    m.role = body.role
    db.commit()
    return {"updated": True}


@router.delete("/members/{membership_id}")
def remove_member(membership_id: int,
                  user: CurrentUser = Depends(require_permission("members.manage")),
                  db: Session = Depends(get_db)):
    """移除成员（删 membership，不删用户）。"""
    m = db.query(TenantMembership).filter(
        TenantMembership.id == membership_id, TenantMembership.tenant_id == user.tenant_id
    ).first()
    if not m:
        raise HTTPException(404, "成员不存在")
    if m.user_id == user.id:
        raise HTTPException(400, "不能移除自己")
    # 检查是否是最后一个 owner
    if m.role == "owner":
        owners = db.query(TenantMembership).filter(
            TenantMembership.tenant_id == user.tenant_id, TenantMembership.role == "owner"
        ).count()
        if owners <= 1:
            raise HTTPException(400, "团队至少保留一个 owner")
    db.delete(m)
    db.commit()
    return {"removed": True}
