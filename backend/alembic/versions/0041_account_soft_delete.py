"""accounts 加 is_managed —— 软删（取消纳管置 false，保留行+名字+历史消耗，dashboard 仍可见）

Revision ID: 0041
Revises: 0040
"""
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # is_managed=false = 已取消纳管（历史保留，不再巡检/不进广告管理活跃列表）
    op.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS is_managed BOOLEAN NOT NULL DEFAULT true")
    op.execute("CREATE INDEX IF NOT EXISTS ix_accounts_tenant_managed ON accounts (tenant_id, is_managed)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_accounts_tenant_managed")
    op.execute("ALTER TABLE accounts DROP COLUMN IF EXISTS is_managed")
