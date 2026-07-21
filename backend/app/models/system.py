"""ORM：平台级系统设置（全局 key-value，如调度配置）。"""
from sqlalchemy import Column, Text, DateTime, func
from ..core.database import Base


class SystemSetting(Base):
    __tablename__ = "system_settings"
    key = Column(Text, primary_key=True)
    value = Column(Text)  # JSON 字符串
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
