"""assets 表加 ai_purpose + ai_language（用途驱动文案分析记录用）

Revision ID: 0048
Revises: 0047
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("assets", sa.Column("ai_purpose", sa.Text()))
    op.add_column("assets", sa.Column("ai_language", sa.Text()))
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_super;")


def downgrade():
    for col in ("ai_language", "ai_purpose"):
        op.drop_column("assets", col)
