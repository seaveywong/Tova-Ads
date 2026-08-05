"""ORM：FB App 配置（系统级 + 团队）。

系统级 App（is_system=true）：superadmin 创建，全租户共享
团队 App（is_system=false）：owner 创建，自己租户私有

app_secret_enc 加密存；webhook HMAC 验签时解密逐一比对（core/webhook_config.py）。
"""
from sqlalchemy import Column, BigInteger, Text, Boolean, DateTime, func
from ..core.database import Base


class FbApp(Base):
    __tablename__ = "fb_apps"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger)  # NULL=系统级
    name = Column(Text)
    app_id = Column(Text, nullable=False)
    app_secret_enc = Column(Text, nullable=False)
    is_system = Column(Boolean, default=False)
    status = Column(Text, default="active")
    access_level = Column(Text, default="dev")  # standard/dev：dev=走建帖(object_story_id)；standard=走 object_story_spec
    created_by = Column(BigInteger)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
