"""landing_events 加 fbclid 列（采集 FB 点击 ID）

Revision ID: 0036
Revises: 0035
"""
from alembic import op
import sqlalchemy as sa

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ADD COLUMN 在已授权的表上，列继承表级 GRANT，无需再 GRANT。
    op.add_column("landing_events", sa.Column("fbclid", sa.Text))


def downgrade() -> None:
    op.drop_column("landing_events", "fbclid")
