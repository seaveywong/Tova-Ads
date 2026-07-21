"""ORM：KPI 配置（KPI resolver L0 手动覆盖，审计项目10/11）。"""
from sqlalchemy import Column, BigInteger, Text, Float, Boolean, DateTime, func
from ..core.database import Base


class KpiConfig(Base):
    __tablename__ = "kpi_configs"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, nullable=False)
    target_type = Column(Text, nullable=False, default="campaign")  # campaign/adset/ad/account
    target_id = Column(Text, nullable=False)
    kpi_field = Column(Text)        # 转化 action_type（手动指定；空=走 resolver 自动）
    target_cpa = Column(Float)      # 目标 CPA（USD）
    source = Column(Text, default="manual")  # manual/auto
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
