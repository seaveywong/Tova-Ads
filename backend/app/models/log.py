"""ORM：action_logs（doc 05/10）。"""
from sqlalchemy import Column, BigInteger, Text, DateTime, ForeignKey, func
from ..core.database import Base


class ActionLog(Base):
    __tablename__ = "action_logs"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    trace_id = Column(Text, nullable=False)
    actor_user_id = Column(BigInteger)
    actor_type = Column(Text, default="system")  # user/system/sentinel/warmup/sync
    target_type = Column(Text)
    target_id = Column(Text)
    action_type = Column(Text)
    source = Column(Text)  # fb_api/landing/rule_engine/user/scheduled
    result = Column(Text, default="success")
    raw_error = Column(Text)
    friendly_error = Column(Text)
    trigger_type = Column(Text)
    trigger_detail = Column(Text)
    metadata_ = Column("metadata", Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
