"""ads_cache 唯一索引 (tenant_id, act_id) → (tenant_id, act_id, platform)。

FB/TT 的 act_id 是不同空间，撞号时 tenant+act_id 唯一索引会互相覆写。
加 platform 进唯一键；FB 行为不变（存量全 'fb' 命中同一行）。

Revision ID: 0081
Revises: 0080
"""
from alembic import op

revision = "0081"
down_revision = "0080"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ads_cache_tenant_act")
    op.execute("CREATE UNIQUE INDEX ix_ads_cache_tenant_act ON ads_cache (tenant_id, act_id, platform)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ads_cache_tenant_act")
    op.execute("CREATE UNIQUE INDEX ix_ads_cache_tenant_act ON ads_cache (tenant_id, act_id)")
