"""ORM 模型：认证与租户核心（对应迁移 0001 的表）。"""
from sqlalchemy import Column, BigInteger, Text, Integer, Boolean, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from ..core.database import Base


class Tenant(Base):
    __tablename__ = "tenants"
    id = Column(BigInteger, primary_key=True)
    name = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="active")
    plan = Column(Text, nullable=False, default="internal")
    sentinel_timeout_min = Column(Integer, nullable=False, default=30)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    id = Column(BigInteger, primary_key=True)
    email = Column(Text, unique=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="active")
    is_superadmin = Column(Boolean, default=False, nullable=False)  # 平台超管（域名分配等）
    timezone = Column(Text, default="Asia/Shanghai")  # 用户显示时区（仅前端展示，不影响广告账户）
    last_active_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TenantMembership(Base):
    __tablename__ = "tenant_memberships"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    role = Column(Text, nullable=False, default="operator")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_membership_tenant_user"),)


class Invitation(Base):
    __tablename__ = "invitations"
    code = Column(Text, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    created_by = Column(BigInteger, ForeignKey("users.id"))
    used_by = Column(BigInteger, ForeignKey("users.id"))
    used_at = Column(DateTime(timezone=True))
    expires_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Role(Base):
    """RBAC 角色：租户自定义角色 + 权限矩阵（16 个模块 key 任意组合）。"""
    __tablename__ = "roles"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    name = Column(Text, nullable=False)  # 角色名（租户内唯一；tenant_memberships.role 存这个名）
    description = Column(Text, default="")
    permissions = Column(JSONB, nullable=False, default=list)  # ["ads.read","landing.manage",...]
    is_system = Column(Boolean, default=False, nullable=False)  # 系统预置（owner/operator/finance，可改权限不可删）
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_roles_tenant_name"),)
