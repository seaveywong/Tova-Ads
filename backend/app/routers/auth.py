"""认证路由：注册（邀请码）/ 登录 / 当前用户。

注册/登录用 system 连接（toveads_super，BYPASSRLS）——因为尚未建立租户上下文。
/auth/me 用普通连接（toveads_app + RLS），get_current_user 接线 tenant 上下文。
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..core.database import get_system_db
from ..core.security import hash_password, verify_password, create_access_token
from ..core.deps import get_current_user, CurrentUser
from ..models.auth import User, TenantMembership, Invitation, Tenant
from ..schemas.auth import RegisterIn, LoginIn, TokenOut, UserOut, UpdateTimezoneIn, UpdateEmailIn, UpdatePasswordIn
from pydantic import BaseModel


def _tenant_name_of(db, tid):
    """取租户名（login/switch-tenant 用，内联避免跨模块导入）。"""
    if not tid:
        return ""
    t = db.query(Tenant).filter(Tenant.id == tid).first()
    return t.name if t else f"团队{tid}"

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut)
def register(body: RegisterIn, db: Session = Depends(get_system_db)):
    """邀请码注册 → 建用户 + membership(默认 operator) → 返 token。"""
    inv = db.query(Invitation).filter(Invitation.code == body.code).first()
    if not inv or inv.used_by is not None:
        raise HTTPException(400, "邀请码无效或已使用")
    if inv.expires_at and inv.expires_at < datetime.now(timezone.utc):
        raise HTTPException(400, "邀请码已过期")
    email_lc = body.email.strip().lower()
    if db.query(User).filter(User.email == email_lc).first():
        raise HTTPException(400, "邮箱已注册")

    user = User(email=email_lc, password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    db.add(TenantMembership(tenant_id=inv.tenant_id, user_id=user.id, role="operator"))
    inv.used_by = user.id
    inv.used_at = datetime.now(timezone.utc)
    db.commit()

    token = create_access_token(user_id=user.id, email=user.email, tenant_id=inv.tenant_id, role="operator")
    return TokenOut(access_token=token, role="operator", tenant_id=inv.tenant_id)


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_system_db)):
    """邮箱密码登录 → 返 token（含第一个 membership 的 tenant/role）+ 所有 memberships。"""
    user = db.query(User).filter(User.email == body.email.strip().lower()).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "邮箱或密码错误")
    if user.status not in ("active", "must_change_password"):
        raise HTTPException(403, "用户已停用")
    mems = db.query(TenantMembership).filter(TenantMembership.user_id == user.id).all()
    # 非超管且无 membership → 拒绝（防止"盲人 token"tenant_id=None 啥都看不到）
    if not mems and not user.is_superadmin:
        raise HTTPException(403, "该用户未加入任何团队，请联系管理员")
    # 取第一个 membership 的 tenant/role 作为默认
    mem = mems[0] if mems else None
    tenant_id = mem.tenant_id if mem else None
    role = mem.role if mem else None
    token = create_access_token(user_id=user.id, email=user.email, tenant_id=tenant_id,
                                role=role, is_superadmin=bool(user.is_superadmin))
    # 返回所有 memberships 供前端团队切换器用
    memberships = [{"tenant_id": m.tenant_id, "role": m.role} for m in mems]
    for ms in memberships:
        ms["tenant_name"] = _tenant_name_of(db, ms["tenant_id"])
    return {"access_token": token, "token_type": "bearer", "role": role,
            "tenant_id": tenant_id, "is_superadmin": bool(user.is_superadmin),
            "memberships": memberships}


class SwitchTenantIn(BaseModel):
    tenant_id: int


@router.post("/switch-tenant")
def switch_tenant(body: SwitchTenantIn,
                  user=Depends(get_current_user),
                  db: Session = Depends(get_system_db)):
    """切换当前团队 → 重 mint token（新 tenant_id + role）。"""
    mem = db.query(TenantMembership).filter(
        TenantMembership.user_id == user.id, TenantMembership.tenant_id == body.tenant_id
    ).first()
    if not mem:
        raise HTTPException(403, "你不属于该团队")
    token = create_access_token(user_id=user.id, email=user.email,
                                tenant_id=mem.tenant_id, role=mem.role,
                                is_superadmin=bool(user.is_superadmin))
    return {"access_token": token, "token_type": "bearer",
            "role": mem.role, "tenant_id": mem.tenant_id,
            "tenant_name": _tenant_name_of(db, mem.tenant_id),
            "is_superadmin": bool(user.is_superadmin)}


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser = Depends(get_current_user),
       db: Session = Depends(get_system_db)):
    u = db.query(User).filter(User.id == user.id).first()
    return UserOut(
        id=user.id, email=user.email, role=user.role,
        tenant_id=user.tenant_id, is_superadmin=user.is_superadmin,
        timezone=user.timezone or "Asia/Shanghai",
        permissions=sorted(user.permissions),
        must_change_password=(u.status == "must_change_password") if u else False,
    )


@router.patch("/me")
def update_me(body: UpdateTimezoneIn, user: CurrentUser = Depends(get_current_user),
              db: Session = Depends(get_system_db)):
    """更新当前用户的显示时区（仅前端展示用，不影响广告账户本地时区）。"""
    tz = (body.timezone or "").strip() or "Asia/Shanghai"
    u = db.query(User).filter(User.id == user.id).first()
    if u:
        u.timezone = tz
        db.commit()
    return {"timezone": tz}


@router.patch("/me/email")
def update_my_email(body: UpdateEmailIn, user: CurrentUser = Depends(get_current_user),
                   db: Session = Depends(get_system_db)):
    """修改当前用户名（登录邮箱）。"""
    new = (body.email or "").strip().lower()
    if not new or "@" not in new:
        raise HTTPException(400, "邮箱格式不正确")
    if db.query(User).filter(User.email == new, User.id != user.id).first():
        raise HTTPException(400, "该邮箱已被占用")
    u = db.query(User).filter(User.id == user.id).first()
    if not u:
        raise HTTPException(404, "用户不存在")
    u.email = new
    db.commit()
    return {"email": new}


@router.put("/me/password")
def update_my_password(body: UpdatePasswordIn, user: CurrentUser = Depends(get_current_user),
                       db: Session = Depends(get_system_db)):
    """修改当前用户密码（需验证旧密码）。must_change_password 状态改密后自动激活。"""
    if len(body.new_password) < 8:
        raise HTTPException(400, "新密码至少 8 位")
    u = db.query(User).filter(User.id == user.id).first()
    if not u or not verify_password(body.old_password, u.password_hash):
        raise HTTPException(400, "旧密码错误")
    u.password_hash = hash_password(body.new_password)
    if u.status == "must_change_password":
        u.status = "active"  # 首次改密 → 激活
    db.commit()
    return {"ok": True}
