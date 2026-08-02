"""landing_pages 加 tt_conversion_events（TK 转化事件，与 FB 分开）

Revision ID: 0060
Revises: 0059
Create Date: 2026-08-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0060"
down_revision = "0059"

def upgrade():
    op.add_column("landing_pages", sa.Column("tt_conversion_events", sa.Text()))
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_super")

def downgrade():
    op.drop_column("landing_pages", "tt_conversion_events")
