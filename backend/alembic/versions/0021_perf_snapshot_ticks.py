"""perf_snapshot_ticks 时序表（趋势折线 5min 颗粒度，巡检双写）

Revision ID: 0021
Revises: 0020

每次巡检验证写一条（5min 粒度），供折线图最小颗粒度。perf_snapshots 每日 upsert（缓存），
perf_snapshot_ticks 时序（不覆盖，每次一条）。保留 N 天（清理 job）。
"""
from alembic import op
import sqlalchemy as sa

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "perf_snapshot_ticks",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("act_id", sa.Text, nullable=False),
        sa.Column("snapshot_date", sa.Text, nullable=False),      # 北京日
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),  # 巡检时刻（5min）
        sa.Column("spend", sa.Float, default=0),
        sa.Column("conversions", sa.Integer, default=0),
        sa.Column("cpa", sa.Float),
        sa.Column("roas", sa.Float),
    )
    op.create_index("ix_perf_ticks_tenant_date_at", "perf_snapshot_ticks",
                    ["tenant_id", "snapshot_date", "snapshot_at"])
    # RLS（tenant 级隔离，照其他租户表）
    op.execute("ALTER TABLE perf_snapshot_ticks ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE perf_snapshot_ticks FORCE ROW LEVEL SECURITY;")
    op.execute("""CREATE POLICY perf_ticks_tenant ON perf_snapshot_ticks
        FOR ALL
        USING (tenant_id = current_setting('app.tenant_id', true)::bigint)
        WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::bigint);""")
    op.execute("GRANT SELECT, INSERT ON perf_snapshot_ticks TO toveads_app;")
    op.execute("GRANT SELECT ON perf_snapshot_ticks TO toveads_super;")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS perf_snapshot_ticks;")
