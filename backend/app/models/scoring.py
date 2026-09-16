"""素材评分 ORM（asset_ad_links / asset_scores，迁移 0100）。"""
from sqlalchemy import Column, BigInteger, Integer, Text, DateTime, ForeignKey, func
from ..core.database import Base


class AssetAdLink(Base):
    """素材↔广告匹配链（hash 双向匹配维护；跟帖模式无 hash 不入链）。"""
    __tablename__ = "asset_ad_links"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    asset_id = Column(BigInteger, ForeignKey("assets.id"), nullable=False)
    ad_id = Column(Text, nullable=False)
    act_id = Column(Text, nullable=False)
    platform = Column(Text, nullable=False, server_default="fb")
    first_seen = Column(DateTime(timezone=True), server_default=func.now())


class AssetScore(Base):
    """素材评分快照（score=null 表示无投放数据——前端显示 AI 预估分）。"""
    __tablename__ = "asset_scores"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    asset_id = Column(BigInteger, ForeignKey("assets.id"), nullable=False)
    score = Column(Integer)
    grade = Column(Text)
    dims = Column(Text)      # JSON {ctr,conv,conf,cov}
    stats = Column(Text)     # JSON 数值明细
    computed_at = Column(DateTime(timezone=True), server_default=func.now())
