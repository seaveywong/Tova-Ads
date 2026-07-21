"""system_settings 全局 key-value 表（存调度配置等平台级设置）

Revision ID: 0026
Revises: 0025
"""
from alembic import op
import sqlalchemy as sa

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON system_settings TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON system_settings TO toveads_super;")


def downgrade() -> None:
    op.drop_table("system_settings")
