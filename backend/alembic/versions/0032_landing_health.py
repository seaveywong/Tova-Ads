"""landing_pages 加健康检查字段（last_health_status/summary/checked_at）

Revision ID: 0032
Revises: 0031
"""
from alembic import op
import sqlalchemy as sa

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("landing_pages", sa.Column("last_health_status", sa.Text()))
    op.add_column("landing_pages", sa.Column("last_health_summary", sa.Text()))
    op.add_column("landing_pages", sa.Column("last_health_checked_at", sa.DateTime(timezone=True)))
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON landing_pages TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON landing_pages TO toveads_super;")


def downgrade() -> None:
    op.drop_column("landing_pages", "last_health_checked_at")
    op.drop_column("landing_pages", "last_health_summary")
    op.drop_column("landing_pages", "last_health_status")
