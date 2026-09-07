"""广告实体缓存模型（巡检顺便拉 campaigns/adsets/ads，广告管理器读缓存跨账户汇总）。"""
from sqlalchemy import Column, BigInteger, Text, DateTime, ForeignKey, func
from ..core.database import Base


class AdsCache(Base):
    """每账户每平台一行（tenant_id+act_id+platform 唯一，迁移 0081），JSON 存三层广告实体。"""
    __tablename__ = "ads_cache"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    act_id = Column(Text, nullable=False)
    platform = Column(Text, nullable=False, server_default="fb")  # fb / tt
    campaigns_json = Column(Text)
    adsets_json = Column(Text)
    ads_json = Column(Text)
    updated_at = Column(DateTime(timezone=True))
    # 广告层独立时间戳（0086）：巡检独家回写 ads_json 时刷新；updated_at 是结构层
    # （campaigns/adsets 15min sync）的时间——单时间戳盖两层会让「缓存不到1分钟」与陈旧
    # 广告数据并存（令牌切换间隙实测误导）。TT 行由 sync 全量拉取，两列同刷。
    ads_updated_at = Column(DateTime(timezone=True))
