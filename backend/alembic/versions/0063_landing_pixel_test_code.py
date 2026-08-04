"""landing_pixels 加 test_event_code（TK Events API 测试模式，事件进 Test Events 标签秒级可见）

Revision ID: 0063
Revises: 0062
Create Date: 2026-08-03
"""
from alembic import op
import sqlalchemy as sa

revision = "0063"
down_revision = "0062"

def upgrade():
    op.add_column("landing_pixels", sa.Column("test_event_code", sa.Text()))
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_super")

def downgrade():
    op.drop_column("landing_pixels", "test_event_code")
