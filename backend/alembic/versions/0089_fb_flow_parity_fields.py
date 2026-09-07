"""0089: FB 创建流程 1:1 批G——排期/总预算/投放方式/出价/特殊类别/描述 列

用户对齐 FB 广告管理器（2026-09-08 决策）：预算与排期（日/总+起止时间）、匀速/加速、
COST_CAP/BID_CAP/最小ROAS、特殊广告类别、创意描述。模板级=树模式默认值，组节点可覆盖
（budget_type/lifetime_budget_usd/schedule_start/schedule_end/pacing/bid_amount_usd/
minimum_roas 进 structure 节点；special_ad_categories/description 是系列/广告级模板列）。
"""
from alembic import op
import sqlalchemy as sa

revision = "0089"
down_revision = "0088"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("launch_templates", sa.Column("budget_type", sa.Text(), server_default="daily"))
    op.add_column("launch_templates", sa.Column("lifetime_budget_usd", sa.Float()))
    op.add_column("launch_templates", sa.Column("schedule_start", sa.Text()))
    op.add_column("launch_templates", sa.Column("schedule_end", sa.Text()))
    op.add_column("launch_templates", sa.Column("pacing", sa.Text()))
    op.add_column("launch_templates", sa.Column("bid_amount_usd", sa.Float()))
    op.add_column("launch_templates", sa.Column("minimum_roas", sa.Float()))
    op.add_column("launch_templates", sa.Column("special_ad_categories", sa.Text()))
    op.add_column("launch_templates", sa.Column("link_description", sa.Text()))
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON launch_templates TO toveads_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON launch_templates TO toveads_super")


def downgrade() -> None:
    for col in ("budget_type", "lifetime_budget_usd", "schedule_start", "schedule_end",
                "pacing", "bid_amount_usd", "minimum_roas", "special_ad_categories",
                "link_description"):
        op.drop_column("launch_templates", col)
