"""landing_domains.domain 改全局唯一（域名唯一分配：一个域名只能给一个租户）

Revision ID: 0014
Revises: 0013

用户决策：被分配对象唯一——同域名不可分给多租户（跨租户重复也报错）。
原 (tenant_id, domain) 组合唯一允许同域名多租户，错；改为 domain 全局唯一。
"""
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE landing_domains DROP CONSTRAINT IF EXISTS uq_landing_domains_tenant_domain;")
    op.create_unique_constraint("uq_landing_domains_domain", "landing_domains", ["domain"])


def downgrade() -> None:
    op.execute("ALTER TABLE landing_domains DROP CONSTRAINT IF EXISTS uq_landing_domains_domain;")
    op.create_unique_constraint("uq_landing_domains_tenant_domain", "landing_domains", ["tenant_id", "domain"])
