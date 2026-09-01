"""ORM：FB Lead（潜客数据，来自 Instant Form / leadgen_forms）。

webhook 实时回调（pages_manage_metadata → fb_webhook.py）或按需拉取（leads_retrieval GET /{form_id}/leads）。
lead_id 唯一去重（webhook 回调 + 手动拉取都查 lead_id 存在再插）。
"""
from sqlalchemy import Column, BigInteger, Text, DateTime, ForeignKey, func
from ..core.database import Base


class Lead(Base):
    __tablename__ = "leads"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    page_id = Column(Text)
    ad_id = Column(Text)
    form_id = Column(Text)
    lead_id = Column(Text, unique=True)   # FB lead id（去重）
    field_data_json = Column(Text)        # [{"name":"full_name","values":["张三"]}, ...]
    created_time = Column(DateTime(timezone=True))  # FB lead 创建时间
    fetched_at = Column(DateTime(timezone=True), server_default=func.now())  # 拉取/回调时间
    # 轻 CRM 跟进字段（本地状态，不回写 FB）
    status = Column(Text, nullable=False, server_default="new")  # new/contacted/won/lost
    note = Column(Text)                   # 跟进备注（可空）
    status_updated_at = Column(DateTime(timezone=True))  # 状态/备注最近更新时间
