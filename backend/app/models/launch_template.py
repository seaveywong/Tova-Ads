"""ORM：投放模板 + 部署 job（asset → template → deploy 链路）。

模板 = Campaign/AdSet/Ad 配置（结构 + 素材引用 + 文案）。
job = 一次批量部署（选模板 + 选 N 账户 → 逐账户建广告，per-item 状态）。
"""
from sqlalchemy import Column, BigInteger, Integer, Float, Text, DateTime, ForeignKey, func
from ..core.database import Base


class LaunchTemplate(Base):
    """投放模板：可复用的广告结构 + 素材 + 文案。部署时套到多账户。"""
    __tablename__ = "launch_templates"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    created_by = Column(BigInteger, ForeignKey("users.id"))
    name = Column(Text, nullable=False)
    description = Column(Text)
    # Campaign 层
    objective = Column(Text, default="OUTCOME_SALES")
    conversion_goal = Column(Text, default="")
    budget_mode = Column(Text, default="ABO")          # ABO / CBO
    bid_strategy = Column(Text, default="LOWEST_COST_WITHOUT_CAP")
    daily_budget = Column(Integer, default=200000)     # legacy（账户本币最小单位）；新数据用 budget_usd
    budget_usd = Column(Float)                         # 每日预算（美元）——部署时按目标账户本币+汇率转
    name_prefix = Column(Text, default="Tova Ads")
    # AdSet 层
    optimization_goal = Column(Text, default="")       # LINK_CLICKS/OFFSITE_CONVERSIONS/REACH/...（空=按 objective 推）
    billing_event = Column(Text, default="IMPRESSIONS")
    destination_type = Column(Text, default="")        # WEBSITE/ON_AD/ON_PAGE/MESSENGER/...（空=按 objective 推）
    audience_id = Column(Integer, default=0)           # FK saved_audiences.id；0=默认定向
    audience_json = Column(Text)                       # 内联受众 {countries,interests[{id,name}],age_min/max,gender,languages}（⑦）
    advanced_config = Column(Text)                     # JSON：高级 FB 字段（bid_amount/attribution/placements/dayparting/custom_audiences...），部署时合并进 payload
    # Ad 层（素材引用 + 文案）
    asset_id = Column(BigInteger, ForeignKey("assets.id"))
    headline = Column(Text)
    body = Column(Text)
    page_id = Column(Text)
    pixel_id = Column(Text)
    landing_url = Column(Text)
    cta_type = Column(Text)
    subcode_slug = Column(Text)
    ad_language = Column(Text)
    message_template = Column(Text)  # Messenger 欢迎语（ENGAGEMENT+消息）
    lead_form_id = Column(Text)      # Instant Form ID（LEADS）
    # 编辑器选中态持久化（迁移0054）：落地页=子码下拉过滤依据；表单/消息模板=回显+部署解析
    landing_page_id = Column(BigInteger)
    lead_form_template_id = Column(Integer)
    message_template_id = Column(Integer)
    # 受益人/付款人披露（EU/泰国/印度/巴西/台湾/澳洲/新加坡等强制；FB adset 的 dsa_beneficiary/dsa_payor）
    beneficiary = Column(Text)
    payer = Column(Text)
    # 跟帖模式（Phase 2 UI）：new=每素材建帖 / reuse=复用已有帖
    post_source = Column(Text, default="new")
    reuse_post_ref = Column(Text)   # 跟帖引用的 post_id
    status = Column(Text, default="draft")             # draft/active/archived
    deploy_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class LaunchJob(Base):
    """一次批量部署（模板 → N 账户）。BackgroundTasks 异步跑，前端轮询。"""
    __tablename__ = "launch_jobs"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    template_id = Column(BigInteger, ForeignKey("launch_templates.id"))
    template_name = Column(Text)                       # 冗余存名（模板可能删）
    status = Column(Text, default="pending")           # pending/running/completed/partial_failed/failed
    total = Column(Integer, default=0)
    succeeded = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    created_by = Column(BigInteger, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True))


class LaunchJobItem(Base):
    """部署明细：每账户一行。per-item commit，单失败不回滚其他。"""
    __tablename__ = "launch_job_items"
    id = Column(BigInteger, primary_key=True)
    job_id = Column(BigInteger, ForeignKey("launch_jobs.id"), nullable=False)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    act_id = Column(Text, nullable=False)
    page_id = Column(Text)
    pixel_id = Column(Text)
    status = Column(Text, default="pending")           # pending/creating/success/fail
    campaign_id = Column(Text)
    adset_id = Column(Text)
    ad_id = Column(Text)
    page_post_id = Column(Text)     # 部署后存的帖 id（object_story_id 用的主页帖）
    subcode_slug = Column(Text)
    error = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
