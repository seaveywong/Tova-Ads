"""平台列铺开：perf_snapshots / ads_cache / guard_ad_allowances / launch_templates + perf 唯一键重建

- 四表各加 platform（Text NOT NULL，server_default 'fb'，存量行同事务自动回填）。
- perf_snapshots 唯一键 (ad_id, snapshot_date) → (ad_id, platform, snapshot_date)：
  同一 ad_id 双平台各存一行（TT ad_id 与 FB 数字 id 理论可撞，平台入键隔离）。
- 纯增量：不改任何存量行的值（全部回填 'fb'），FB 查询侧已同步加 platform='fb' 过滤。

Revision ID: 0071
Revises: 0070
Create Date: 2026-09-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0071"
down_revision = "0070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 加列（server_default 即回填，同事务生效）
    op.add_column("perf_snapshots", sa.Column("platform", sa.Text(), nullable=False, server_default="fb"))
    op.add_column("ads_cache", sa.Column("platform", sa.Text(), nullable=False, server_default="fb"))
    op.add_column("guard_ad_allowances", sa.Column("platform", sa.Text(), nullable=False, server_default="fb"))
    op.add_column("launch_templates", sa.Column("platform", sa.Text(), nullable=False, server_default="fb"))
    # 唯一键重建：ad_id 维度加 platform
    op.drop_constraint("uq_perf_ad_date", "perf_snapshots", type_="unique")
    op.create_unique_constraint("uq_perf_ad_date", "perf_snapshots", ["ad_id", "platform", "snapshot_date"])
    # 表已授权过 DML（0064/0065 双角色 ALL TABLES），列级变更无需重授


def downgrade() -> None:
    op.drop_constraint("uq_perf_ad_date", "perf_snapshots", type_="unique")
    op.create_unique_constraint("uq_perf_ad_date", "perf_snapshots", ["ad_id", "snapshot_date"])
    op.drop_column("launch_templates", "platform")
    op.drop_column("guard_ad_allowances", "platform")
    op.drop_column("ads_cache", "platform")
    op.drop_column("perf_snapshots", "platform")
