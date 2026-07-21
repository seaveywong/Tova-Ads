"""kpi_configs：KPI 手动配置（KPI resolver L0，审计项目10/11）

Revision ID: 0016
Revises: 0015

存每条 campaign（或 ad/adset/account）的 KPI 转化字段 + target_cpa（手动覆盖）。
resolver: L0 手动 kpi_configs → L4 objective 矩阵 → L5 语义兜底。完整 5 级 + AI 见 v2。
"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

_RLS = ["kpi_configs"]
_POLICY = "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint)"


def upgrade() -> None:
    op.create_table(
        "kpi_configs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("target_type", sa.Text, nullable=False, server_default="campaign"),  # campaign/adset/ad/account
        sa.Column("target_id", sa.Text, nullable=False),  # campaign_id 等
        sa.Column("kpi_field", sa.Text),                  # 转化 action_type（手动指定；空=走 resolver 自动）
        sa.Column("target_cpa", sa.Float),                # 目标 CPA（USD；cpa_exceed/consecutive_bad 用）
        sa.Column("source", sa.Text, server_default="manual"),  # manual/auto(rule)
        sa.Column("enabled", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_kpi_configs_target", "kpi_configs", ["tenant_id", "target_type", "target_id"])
    for t in _RLS:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY;")
        op.execute(f"CREATE POLICY tenant_iso ON {t} FOR ALL {_POLICY};")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_super;")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO toveads_super;")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS kpi_configs;")
