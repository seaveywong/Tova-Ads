"""广告实体缓存模型（巡检顺便拉 campaigns/adsets/ads，广告管理器读缓存跨账户汇总）。"""
from sqlalchemy import Column, BigInteger, Text, DateTime, ForeignKey, func
from ..core.database import Base


class AdsCache(Base):
    """每账户一行（tenant_id+act_id 唯一），JSON 存三层广告实体。"""
    __tablename__ = "ads_cache"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    act_id = Column(Text, nullable=False)
    campaigns_json = Column(Text)
    adsets_json = Column(Text)
    ads_json = Column(Text)
    updated_at = Column(DateTime(timezone=True))
