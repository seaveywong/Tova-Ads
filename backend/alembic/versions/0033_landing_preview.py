"""landing_pages 加预览模式字段（preview_token + preview_enabled）

Revision ID: 0033
Revises: 0032
"""
from alembic import op
import sqlalchemy as sa

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("landing_pages", sa.Column("preview_token", sa.Text()))
    op.add_column("landing_pages", sa.Column("preview_enabled", sa.Boolean(), server_default=sa.text("false")))
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON landing_pages TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON landing_pages TO toveads_super;")


def downgrade() -> None:
    op.drop_column("landing_pages", "preview_enabled")
    op.drop_column("landing_pages", "preview_token")
