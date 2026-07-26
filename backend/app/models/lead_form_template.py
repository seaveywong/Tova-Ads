"""ORM：Instant Form 模板 + Messenger 消息模板（可存可复用）。

表单模板存完整配置 JSON（form_title/questions/privacy/thank_you/...），部署时 build_lead_form_payload → 建到 FB。
消息模板存 welcome_text + ice_breakers，部署时 parse_message_template → 传创意。
"""
from sqlalchemy import Column, BigInteger, Integer, Text, DateTime, ForeignKey, func
from ..core.database import Base


class LeadFormTemplate(Base):
    """Instant Form 模板：可复用的表单配置。部署时建到 FB leadgen_forms → 存 fb_form_id 复用。"""
    __tablename__ = "lead_form_templates"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    created_by = Column(BigInteger, ForeignKey("users.id"))
    name = Column(Text, nullable=False)
    description = Column(Text)
    config_json = Column(Text)      # 完整表单配置 JSON（form_title/privacy_url/locale/custom_questions/extra_contact_fields/thank_you_*/...）
    fb_form_id = Column(Text)       # 部署成功后 FB 返回的 form_id（复用免重建）
    fb_page_id = Column(Text)       # 建在哪个 page 上（fb_form_id 绑 page）
    locale = Column(Text, default="en_US")
    status = Column(Text, default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class MessageTemplate(Base):
    """Messenger 欢迎语模板：welcome_text + ice_breakers。部署时 parse_message_template → 传创意。"""
    __tablename__ = "message_templates"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    created_by = Column(BigInteger, ForeignKey("users.id"))
    name = Column(Text, nullable=False)
    welcome_text = Column(Text)
    ice_breakers_json = Column(Text)  # [{title, response}, ...]
    status = Column(Text, default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
