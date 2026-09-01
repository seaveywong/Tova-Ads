"""ORM：TikTok 凭证 + 账户关联 + App 配置（TK 接入 P0 数据层）。

与 FB 侧（fb.py/fb_app.py）同构，差异点：
- TikTok access_token 24h 过期（expires_at）+ refresh_token 365d（refresh_expires_at），
  需 cron 刷新（P1）；FB 无 refresh。
- tt_credentials.advertiser_id = 授权主体广告主 ID（一个授权可带多个 advertiser，
  账户级关联走 account_tt_credentials）。
- tt_apps 无 access_level（FB dev/standard 专属语义，TikTok 不适用）。
"""
from sqlalchemy import Column, BigInteger, Text, Integer, Boolean, DateTime, ForeignKey, UniqueConstraint, func
from ..core.database import Base


class TtCredential(Base):
    __tablename__ = "tt_credentials"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    owner_user_id = Column(BigInteger, ForeignKey("users.id"))   # 添加人（审计）
    alias = Column(Text)                                          # 命名（多 token fallback 基础）
    app_id = Column(Text, nullable=False)                         # 授权用的 TikTok App ID
    advertiser_id = Column(Text)                                  # 授权主体广告主 ID（可空=授权时未指定）
    access_token_enc = Column(Text, nullable=False)               # 加密存（同 fb_credentials）
    refresh_token_enc = Column(Text)
    expires_at = Column(DateTime(timezone=True))                  # access_token 过期（~24h，cron 刷）
    refresh_expires_at = Column(DateTime(timezone=True))          # refresh_token 过期（~365d）
    token_source = Column(Text, default="oauth")                  # oauth(App授权) / manual(手粘)
    status = Column(Text, default="active")                       # active / expired / invalid
    scopes = Column(Text)                                         # JSON 数组（授权 scope 列表）
    last_refreshed_at = Column(DateTime(timezone=True))
    consecutive_fails = Column(Integer, default=0)                # 连续失败计数（刷新/调用）
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AccountTtCredential(Base):
    """TikTok 多令牌同账户多对多（照 FB 的 account_fb_credentials 模式）。

    accounts.tt_credential_id 保留作"主令牌"（快查/兼容），本表是候选池
    （priority 排序 + RR 分流 + 孤儿重绑来源）。
    """
    __tablename__ = "account_tt_credentials"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    account_id = Column(BigInteger, ForeignKey("accounts.id"), nullable=False)
    tt_credential_id = Column(BigInteger, ForeignKey("tt_credentials.id"), nullable=False)
    status = Column(Text, default="active")   # active / disabled
    priority = Column(Integer, default=0)     # 数字越小优先级越高（0=最高）
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("account_id", "tt_credential_id", name="uq_acct_tt_cred"),)


class TtApp(Base):
    """TikTok App 配置（照 fb_apps：系统级 is_system=true 全租户共享 / 团队级私有）。

    app_secret_enc 加密存。无 access_level（FB dev/standard 专属语义）。
    """
    __tablename__ = "tt_apps"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"))  # NULL=系统级
    name = Column(Text)
    app_id = Column(Text, nullable=False)
    app_secret_enc = Column(Text, nullable=False)
    is_system = Column(Boolean, default=False)
    status = Column(Text, default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
