"""PagePost：建过的 FB 主页帖缓存（供 object_story_id 复用）。

dev app 不能用 object_story_spec（code3）→ 改为先建主页照片帖(/{page}/photos)拿 post_id，
再 creative 用 object_story_id 引用。本表缓存"同页同素材同文案"的帖，避免重复建。
唯一 (tenant_id, page_id, body_hash)。
"""
from sqlalchemy import Column, BigInteger, Text, DateTime, func
from ..core.database import Base


class PagePost(Base):
    __tablename__ = "page_posts"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, nullable=False)
    page_id = Column(Text, nullable=False)
    post_id = Column(Text, nullable=False)      # FB 主页帖 id（给 object_story_id 用）
    asset_id = Column(BigInteger)
    message = Column(Text)
    link = Column(Text)
    body_hash = Column(Text, nullable=False)    # sha1(asset_id + message + link)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
