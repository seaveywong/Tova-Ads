"""landing_pixels.fb_capi_enabled——FB CAPI S2S 灰度开关（默认 false）。

FB Conversions API 服务器端双发按像素灰度：只有显式打开的像素才会在 visit 时
同 event_id 发 S2S 转化事件（与浏览器 fbq trackSingle 的 eventID 去重）。
默认关 = FB 投放数据零变化。已有表加列，表级 GRANT 已覆盖新列，不必重授。

Revision ID: 0072
Revises: 0071
"""
from alembic import op
import sqlalchemy as sa

revision = "0072"
down_revision = "0071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("landing_pixels", sa.Column(
        "fb_capi_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("landing_pixels", "fb_capi_enabled")
