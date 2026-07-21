"""ORM：止损规则 + 当日加白（doc 03）。"""
from sqlalchemy import Column, BigInteger, Text, Boolean, DateTime, ForeignKey, UniqueConstraint, func
from ..core.database import Base


class GuardRule(Base):
    __tablename__ = "guard_rules"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    name = Column(Text, nullable=False)
    category = Column(Text, nullable=False)  # 空耗止损/成本超标/效果下滑
    rule_type = Column(Text, nullable=False)  # bleed_abs/cpa_exceed/trend_drop/...
    params = Column(Text)  # JSON
    conversion_source = Column(Text, default="either")
    action = Column(Text, default="default")  # observe/default/pause/pause_adset/pause_campaign
    scope_act_id = Column(Text)  # NULL=全局（名下所有账户）；act_id(裸数字)=仅该账户
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class GuardAllowance(Base):
    __tablename__ = "guard_ad_allowances"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    act_id = Column(Text, nullable=False)
    ad_id = Column(Text, nullable=False)
    allowance_date = Column(Text, nullable=False)
    status = Column(Text, default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("act_id", "ad_id", "allowance_date", name="uq_allowance_act_ad_date"),)
