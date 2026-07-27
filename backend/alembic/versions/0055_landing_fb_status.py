"""landing_pages 加 FB 屏蔽探测状态字段（自动扫描持久化用）

- last_fb_status: pass/fail/warn（fail=被 FB 屏蔽）；看板红标 + 通知直接读
- last_fb_checked_at: 上次 FB 屏蔽探测时间

Revision ID: 0055
Revises: 0054
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("landing_pages", sa.Column("last_fb_status", sa.Text()))
    op.add_column("landing_pages", sa.Column("last_fb_checked_at", sa.DateTime(timezone=True)))
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_super;")


def downgrade():
    op.drop_column("landing_pages", "last_fb_checked_at")
    op.drop_column("landing_pages", "last_fb_status")
