"""ORM：受众模板库（doc 02 受众，审计项目16）。

v1 仅兴趣受众（flexible_spec），无 custom_audiences/lookalikes（v2）。
"""
from sqlalchemy import Column, BigInteger, Text, Integer, DateTime, ForeignKey, func
from ..core.database import Base


class SavedAudience(Base):
    __tablename__ = "saved_audiences"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    created_by = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    name = Column(Text, nullable=False)
    interests_json = Column(Text, default="[]")  # [{id,name}, ...]
    countries = Column(Text, default="[]")  # JSON ["US","TW"]
    age_min = Column(Integer, default=18)
    age_max = Column(Integer, default=65)
    gender = Column(Integer, default=0)  # 0=all 1=male 2=female
    strategy = Column(Text, default="broad_interest")  # broad_interest/broad_only/interest_only
    note = Column(Text)
    status = Column(Text, default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
