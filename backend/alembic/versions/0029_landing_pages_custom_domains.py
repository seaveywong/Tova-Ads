"""landing_pages 加 custom_domains（JSON 多域名，一页绑多域）

Revision ID: 0029
Revises: 0028
"""
from alembic import op
import sqlalchemy as sa

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("landing_pages", sa.Column("custom_domains", sa.Text()))


def downgrade() -> None:
    op.drop_column("landing_pages", "custom_domains")
