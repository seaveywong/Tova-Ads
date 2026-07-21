"""landing_events 加 act_id 列（采集每次点击的广告账户，多账户复用按它 fire 正确像素）

Revision ID: 0038
Revises: 0037
"""
from alembic import op
import sqlalchemy as sa

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("landing_events", sa.Column("act_id", sa.Text))


def downgrade() -> None:
    op.drop_column("landing_events", "act_id")
