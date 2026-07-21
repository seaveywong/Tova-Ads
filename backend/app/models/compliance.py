"""ORM：受监管地区（TW/SG/HK）认证主页 + verified_identity_id（doc 02 受监管地区，审计项目4）。

为什么需要手动 verified_identity_id：FB API 不暴露该 ID，但 TW/SG 受监管广告 AdSet
要求数字身份 ID 注入 regional_regulation_identities。用户从 FB BM 后台手抄录入。
"""
from sqlalchemy import Column, BigInteger, Text, DateTime, ForeignKey, func
from ..core.database import Base


class CertifiedPage(Base):
    __tablename__ = "certified_pages"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    created_by = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    region = Column(Text, nullable=False)  # TW / SG / HK
    page_id = Column(Text, nullable=False)
    page_name = Column(Text)
    # 数字身份 ID（FB 要求数字）—— 从 BM 后台手抄
    beneficiary_identity_id = Column(Text, nullable=False)
    payer_identity_id = Column(Text)
    beneficiary_name = Column(Text)
    payer_name = Column(Text)
    status = Column(Text, default="active")
    note = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
