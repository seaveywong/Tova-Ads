"""ORM：FB 凭证 + Token 健康 + 广告账户。"""
from sqlalchemy import Column, BigInteger, Text, Boolean, Integer, DateTime, ForeignKey, UniqueConstraint, func
from ..core.database import Base


class FbCredential(Base):
    __tablename__ = "fb_credentials"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    type = Column(Text, nullable=False, default="user_token")
    alias = Column(Text)  # 命名（1111/2222...），多 token fallback 基础
    access_token_enc = Column(Text, nullable=False)
    refresh_token_enc = Column(Text)
    expires_at = Column(DateTime(timezone=True))
    scopes = Column(Text)
    fb_user_id = Column(Text)
    fb_user_name = Column(Text)
    status = Column(Text, nullable=False, default="active")
    # 令牌管理设计（migration 0022）
    token_type = Column(Text, default="user")          # manage(读+PAUSE兜底) / operate(写) / user(只读)
    token_source = Column(Text, default="manual")      # oauth(App授权) / manual(手粘)
    permission_snapshot = Column(Text)                  # JSON: debug_token 拉的权限（ads_management/ads_read/pages_*）
    consecutive_fails = Column(Integer, default=0)      # 连续失败计数（限流/瞬时错误）
    last_verified_at = Column(DateTime(timezone=True))  # 最近检测时间
    cooldown_until = Column(DateTime(timezone=True))     # 限流冷却到期时间（code=17 后 30min）
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class TokenHealth(Base):
    __tablename__ = "token_health"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    fb_credential_id = Column(BigInteger, ForeignKey("fb_credentials.id"), nullable=False)
    valid = Column(Boolean, nullable=False, default=False)
    expires_at = Column(DateTime(timezone=True))
    last_checked_at = Column(DateTime(timezone=True))
    error_category = Column(Text)
    error_friendly = Column(Text)


class Account(Base):
    __tablename__ = "accounts"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    fb_credential_id = Column(BigInteger, ForeignKey("fb_credentials.id"))
    act_id = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    currency = Column(Text, nullable=False, default="USD")
    timezone_name = Column(Text, nullable=False, default="UTC")
    owner_user_id = Column(BigInteger, ForeignKey("users.id"))
    account_status = Column(Integer, default=1)
    balance = Column(Text)
    spend_cap = Column(Text)
    amount_spent = Column(Text)
    warmup_state = Column(Text, default="none")
    last_warmup_at = Column(DateTime(timezone=True))
    sentinel_armed = Column(Boolean, default=False)
    sentinel_auto_armed = Column(Boolean, default=False)
    last_inspected_at = Column(DateTime(timezone=True))
    is_managed = Column(Boolean, nullable=False, default=True)  # false=已取消纳管（软删：保留行+名字+历史消耗）
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("tenant_id", "act_id", name="uq_accounts_tenant_actid"),)
