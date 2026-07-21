"""landing_pages.pixel_ids（多像素，JSON 数组）—— 落地页重做 ⑤，决策①

Revision ID: 0015
Revises: 0014

决策①：一页多像素，每个事件用 fbq('trackSingle') 发给所有像素。
保留 pixel_id（单像素 legacy 兼容）。新页用 pixel_ids（数组）。
"""
from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("landing_pages", sa.Column("pixel_ids", sa.Text))  # JSON 数组 ["123","456"]
    op.add_column("landing_pages", sa.Column("conversion_event", sa.Text))  # 广告配置驱动：Purchase/Contact/Lead；空=只 PageView


def downgrade() -> None:
    op.drop_column("landing_pages", "conversion_event")
    op.drop_column("landing_pages", "pixel_ids")
