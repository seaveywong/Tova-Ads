"""landing_events 加 fired_pixel_ids 列（记录每次访问真实 fire 的像素ID）

worker visit beacon 透传 route_next 实际返回的 pixel_ids（地面真相，不臆想推断）。
历史访问无此值→空（老实显示未记录，不回填猜测）。

Revision ID: 0043
Revises: 0042
"""
from alembic import op
import sqlalchemy as sa

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("landing_events", sa.Column("fired_pixel_ids", sa.Text))


def downgrade() -> None:
    op.drop_column("landing_events", "fired_pixel_ids")
