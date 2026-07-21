"""perf_snapshots：广告每日表现快照（守护 consecutive_bad / budget_burn_fast 用，审计项目9）

Revision ID: 0011
Revises: 0010

每巡检轮 upsert 当日快照（spend/conversions/cpa）：
- consecutive_bad：查近 N 天快照，每行 cpa > target*ratio → 命中。
- budget_burn_fast：本轮 spend - 上轮 spend >= threshold → 瞬烧。
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

_RLS = ["perf_snapshots"]
_POLICY = "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint)"


def upgrade() -> None:
    op.create_table(
        "perf_snapshots",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("act_id", sa.Text, nullable=False),
        sa.Column("ad_id", sa.Text, nullable=False),
        sa.Column("snapshot_date", sa.Text, nullable=False),  # 账户本地日 YYYY-MM-DD
        sa.Column("spend", sa.Float, default=0),
        sa.Column("conversions", sa.Integer, default=0),
        sa.Column("cpa", sa.Float),  # spend/conversions（conversions=0 时 NULL）
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("ad_id", "snapshot_date", name="uq_perf_ad_date"),
    )
    op.create_index("ix_perf_ad_date", "perf_snapshots", ["ad_id", "snapshot_date"])
    op.create_index("ix_perf_tenant_date", "perf_snapshots", ["tenant_id", "snapshot_date"])

    for t in _RLS:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY;")
        op.execute(f"CREATE POLICY tenant_iso ON {t} FOR ALL {_POLICY};")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_super;")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO toveads_super;")


def downgrade() -> None:
    for t in reversed(_RLS):
        op.execute(f"DROP TABLE IF EXISTS {t};")
