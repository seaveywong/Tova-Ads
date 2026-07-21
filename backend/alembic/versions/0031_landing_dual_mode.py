"""landing_pages 加 redirect_mode（落地页/跳转双模式）+ conversion_events（多转化）+ block_enabled（防护开关）

Revision ID: 0031
Revises: 0030
"""
from alembic import op
import sqlalchemy as sa

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("landing_pages", sa.Column("redirect_mode", sa.Text(), server_default="display"))
    op.add_column("landing_pages", sa.Column("conversion_events", sa.Text()))
    op.add_column("landing_pages", sa.Column("block_enabled", sa.Boolean(), server_default="false"))
    # 迁移旧数据：conversion_event（单值）→ conversion_events（JSON 数组）
    op.execute("UPDATE landing_pages SET conversion_events = '[\"' || conversion_event || '\"]' "
               "WHERE conversion_event IS NOT NULL AND conversion_event != ''")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON landing_pages TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON landing_pages TO toveads_super;")


def downgrade() -> None:
    op.drop_column("landing_pages", "block_enabled")
    op.drop_column("landing_pages", "conversion_events")
    op.drop_column("landing_pages", "redirect_mode")
