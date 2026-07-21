"""ORM：素材 + 落地页 + 子码（铺广告链路核心对象）。"""
from sqlalchemy import Column, BigInteger, Integer, Text, Boolean, DateTime, ForeignKey, func
from ..core.database import Base


class Asset(Base):
    __tablename__ = "assets"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    owner_user_id = Column(BigInteger, ForeignKey("users.id"))
    type = Column(Text, nullable=False)
    storage_key = Column(Text, nullable=False)
    filename = Column(Text)
    ai_copy = Column(Text)
    is_manual = Column(Boolean, default=False)
    manual_copy = Column(Text)
    category = Column(Text, default="常规")
    fb_image_hash = Column(Text)
    status = Column(Text, default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class LandingPage(Base):
    __tablename__ = "landing_pages"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    owner_user_id = Column(BigInteger, ForeignKey("users.id"))
    title = Column(Text, nullable=False)
    template_id = Column(BigInteger)
    domain_kind = Column(Text, default="platform_hosted")
    custom_domain = Column(Text)
    custom_domains = Column(Text)
    target_urls = Column(Text)
    rotation_mode = Column(Text, default="first")
    pixel_id = Column(Text)            # legacy 单像素（兼容）
    pixel_ids = Column(Text)           # JSON 数组 ["123","456"]（多像素，决策①）
    conversion_event = Column(Text)    # legacy 单转化事件（兼容旧数据）
    conversion_events = Column(Text)   # JSON 数组 ["Purchase","Contact"]（多转化事件，CTA 点击 forEach fire）
    redirect_mode = Column(Text, default="display")  # display=展示落地页 / redirect=直接跳转
    block_enabled = Column(Boolean, default=False)   # 防护开关：false=不评估规则全放行
    preview_token = Column(Text)                      # 预览令牌（?_pv=token 跳过防护看真实页）
    preview_enabled = Column(Boolean, default=False)  # 预览开关：关闭后该 token URL 失效
    subdomain_prefix = Column(Text)                   # 子域名前缀（空=默认 lp{id}）
    dedup_enabled = Column(Boolean, default=False)    # 防重复访客开关
    dedup_window_hours = Column(Integer)              # 防重时间窗（小时）
    last_health_status = Column(Text)   # pass/warn/fail（自检结果）
    last_health_summary = Column(Text)  # 自检摘要
    last_health_checked_at = Column(DateTime(timezone=True))
    ingest_secret = Column(Text)
    protection_rules = Column(Text)
    status = Column(Text, default="draft")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class LandingAdLink(Base):
    __tablename__ = "landing_ad_links"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    page_id = Column(BigInteger, ForeignKey("landing_pages.id"))
    slug = Column(Text, nullable=False, unique=True)
    ad_id = Column(Text)
    act_id = Column(Text)  # 必填——防 bleed_abs 误杀（doc 04 不变量 4-5）
    target_urls = Column(Text)
    status = Column(Text, default="reserved")  # reserved/active/archived/deleted
    archived_at = Column(DateTime(timezone=True))  # 进入 archived/deleted 的时间（自动清理硬删阈值用）
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AdRedirectOverride(Base):
    """广告级跳转链接覆盖：按 ad_id 给某条广告单独的 target_url（多广告复用一子码时，
    不同广告跳不同链接）。route_next 优先级：广告覆盖 > 子码跳转 > 页默认。"""
    __tablename__ = "ad_redirect_overrides"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    ad_id = Column(Text, nullable=False)  # FB 广告 ID（全局唯一）
    target_url = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class LandingTemplate(Base):
    __tablename__ = "landing_page_templates"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    name = Column(Text, nullable=False)
    description = Column(Text)
    html = Column(Text, nullable=False)
    resources_meta = Column(Text)
    is_builtin = Column(Boolean, default=False)
    status = Column(Text, default="active")
    created_by = Column(BigInteger, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
