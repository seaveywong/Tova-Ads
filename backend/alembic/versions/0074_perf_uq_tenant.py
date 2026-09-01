"""perf_snapshots 唯一键补 tenant_id。

TT 的 ad_id 是每广告主小整数（≠FB 全局唯一），跨租户/跨广告主撞号概率高：
(ad_id, platform, date) 键下会 IntegrityError 或 UPDATE 到别租户行。加 tenant_id
后键=(tenant, ad, platform, date)。FB 行为不变（tenant 本就隐含在数据里）。

Revision ID: 0074
Revises: 0073
"""
from alembic import op

revision = "0074"
down_revision = "0073"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_perf_ad_date", "perf_snapshots", type_="unique")
    op.create_unique_constraint(
        "uq_perf_ad_date", "perf_snapshots",
        ["tenant_id", "ad_id", "platform", "snapshot_date"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_perf_ad_date", "perf_snapshots", type_="unique")
    op.create_unique_constraint("uq_perf_ad_date", "perf_snapshots",
                                ["ad_id", "platform", "snapshot_date"])
