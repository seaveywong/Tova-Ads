"""ORM：像素库 + 域名库（落地页重做，决策 2/6）。

按租户隔离。用量统计（usage_count/used_by）不存表，按需子查询 landing_pages（见 routers/landing_lib.py）。
像素 ID 明文（决策⑦：像素本就公开在页面 HTML，遮掩反 UX）。
"""
from sqlalchemy import Column, BigInteger, Boolean, Text, DateTime, ForeignKey, func
from ..core.database import Base


class LandingPixel(Base):
    __tablename__ = "landing_pixels"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    created_by = Column(BigInteger, ForeignKey("users.id"))
    pixel_id = Column(Text, nullable=False)
    platform = Column(Text, default="fb")     # fb / tt
    tt_access_token_enc = Column(Text)        # TK Events API access token（加密存；仅 platform=tt 用）
    test_event_code = Column(Text)            # TK Events Manager Test Events 标签的测试码（明文，定期过期需更新）
    fb_capi_enabled = Column(Boolean, nullable=False, server_default="false")  # FB CAPI S2S 灰度开关（默认关；true=visit 时同 event_id 服务器端双发）
    pixel_name = Column(Text)
    act_id = Column(Text, index=True)
    source = Column(Text, default="manual")
    note = Column(Text)
    status = Column(Text, default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class LandingDomain(Base):
    __tablename__ = "landing_domains"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    created_by = Column(BigInteger, ForeignKey("users.id"))
    domain = Column(Text, nullable=False)
    label = Column(Text)
    source = Column(Text, default="manual")  # manual/discovered
    cf_zone_status = Column(Text)  # active/pending_nameserver/error
    note = Column(Text)
    status = Column(Text, default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
