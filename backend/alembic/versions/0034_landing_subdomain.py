"""landing_pages 加子域名自定义前缀（subdomain_prefix）+ 防重复访客字段

Revision ID: 0034
Revises: 0033
"""
from alembic import op
import sqlalchemy as sa

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("landing_pages", sa.Column("subdomain_prefix", sa.Text()))
    op.add_column("landing_pages", sa.Column("dedup_enabled", sa.Boolean(), server_default=sa.text("false")))
    op.add_column("landing_pages", sa.Column("dedup_window_hours", sa.Integer()))
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON landing_pages TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON landing_pages TO toveads_super;")


def downgrade() -> None:
    op.drop_column("landing_pages", "dedup_window_hours")
    op.drop_column("landing_pages", "dedup_enabled")
    op.drop_column("landing_pages", "subdomain_prefix")
