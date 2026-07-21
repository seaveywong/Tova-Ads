"""ORM：落地页事件（doc 04 转化归因 / 落地追踪）。"""
from sqlalchemy import Column, BigInteger, Text, DateTime, func
from ..core.database import Base


class LandingEvent(Base):
    __tablename__ = "landing_events"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger)
    page_id = Column(BigInteger)
    event_type = Column(Text, nullable=False)  # visit/click/submit/block/redirect/pass/error
    slug = Column(Text)
    ad_id = Column(Text)
    act_id = Column(Text)  # 这次点击的广告账户（?act={{account.id}} 透传；多账户复用按它 fire 正确像素）
    fbclid = Column(Text)  # Facebook 点击 ID（FB 点击时自动拼到 URL，worker 透传采集）
    fired_pixel_ids = Column(Text)  # 本次访问真实 fire 的像素ID（worker visit beacon 透传 route_next 返回值，逗号分隔；地面真相，非推断）
    path = Column(Text)
    target_url = Column(Text)
    decision = Column(Text)
    reason = Column(Text)
    country = Column(Text)
    region = Column(Text)
    city = Column(Text)
    colo = Column(Text)
    asn = Column(Text)
    platform = Column(Text)
    device_type = Column(Text)
    browser = Column(Text)
    os = Column(Text)
    user_agent = Column(Text)
    ip_hash = Column(Text)
    visitor_id = Column(Text)
    referrer = Column(Text)
    metadata_ = Column("metadata", Text)  # 'metadata' 是 SQLAlchemy 保留属性
    created_at = Column(DateTime(timezone=True), server_default=func.now())
