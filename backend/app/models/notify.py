"""ORM：通知 + TG 绑定（doc 06）。"""
from sqlalchemy import Column, BigInteger, Text, DateTime, ForeignKey, func
from ..core.database import Base


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.id"))
    level = Column(Text, nullable=False)  # critical/warning/info
    event_type = Column(Text, nullable=False)
    title = Column(Text, nullable=False)
    body = Column(Text)
    trace_id = Column(Text)
    target_type = Column(Text)
    target_id = Column(Text)
    roles = Column(Text)  # 角色订阅（决策①，逗号分隔 owner,operator,finance）；空=全员
    read_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TenantTgBinding(Base):
    __tablename__ = "tenant_tg_bindings"
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), primary_key=True)
    bot_token_enc = Column(Text, nullable=False)
    chat_id = Column(Text, nullable=False)
    verified_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class UserTgBinding(Base):
    """用户级 TG 绑定（决策③，每人绑自己的 TG）。"""
    __tablename__ = "user_tg_bindings"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    bot_token_enc = Column(Text, nullable=False)
    chat_id = Column(Text, nullable=False)
    verified_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
