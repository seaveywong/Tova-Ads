"""ORM：平台级系统设置（全局 key-value，如调度配置）+ CF 邮箱转发映射。"""
from sqlalchemy import Column, Text, DateTime, BigInteger, Boolean, ForeignKey, func
from ..core.database import Base


class SystemSetting(Base):
    __tablename__ = "system_settings"
    key = Column(Text, primary_key=True)
    value = Column(Text)  # JSON 字符串
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class EmailRoute(Base):
    """CF Email Routing 转发映射（平台级，tenant_id 恒 NULL——照 tt_apps 先例）。

    alias 存 @ 前部分（如 dev → dev@tovaads.com），destination_email 是 CF 已验证的
    目的地邮箱。rule_id 存 CF 规则 id（删除本地行时同步删 CF 规则）。启停双写：
    本地 enabled + CF 规则 enabled。
    """
    __tablename__ = "email_routes"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"))  # NULL=系统级（照 tt_apps）
    alias = Column(Text, nullable=False, unique=True)         # @ 前部分，全小写
    destination_email = Column(Text, nullable=False)          # 已验证的目的地邮箱
    rule_id = Column(Text)                                    # CF rule id
    enabled = Column(Boolean, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
