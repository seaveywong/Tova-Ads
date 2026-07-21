"""landing_ad_links 加 archived_at 列（子码归档时间，自动硬删阈值用）

Revision ID: 0037
Revises: 0036
"""
from alembic import op
import sqlalchemy as sa

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("landing_ad_links", sa.Column("archived_at", sa.DateTime(timezone=True)))
    # 旧 archived 子码补一下 archived_at（取 created_at 兜底），避免立刻被 30d 硬删规则误杀
    op.execute("UPDATE landing_ad_links SET archived_at = created_at WHERE status = 'archived' AND archived_at IS NULL")


def downgrade() -> None:
    op.drop_column("landing_ad_links", "archived_at")
