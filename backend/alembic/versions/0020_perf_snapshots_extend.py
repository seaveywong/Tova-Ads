"""perf_snapshots 扩字段（reach/frequency/ctr/cpc/impressions/clicks/roas）+ currency_rates 表

Revision ID: 0020
Revises: 0019

照搬 1.0 缓存架构：巡检写入完整指标 → 看板读缓存秒开（不调 FB）。
"""
from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

_RLS = []  # currency_rates 是全局表，不加 RLS


def upgrade() -> None:
    # 扩 perf_snapshots
    for col, typ in [
        ("impressions", sa.Integer), ("clicks", sa.Integer),
        ("reach", sa.Integer), ("frequency", sa.Float),
        ("ctr", sa.Float), ("cpc", sa.Float), ("roas", sa.Float),
        ("spend_native", sa.Float), ("currency", sa.Text),
    ]:
        try:
            op.add_column("perf_snapshots", sa.Column(col, typ))
        except Exception:
            pass  # 已存在

    # currency_rates 表（照搬 1.0，每日刷新）
    op.create_table(
        "currency_rates",
        sa.Column("code", sa.Text, primary_key=True),
        sa.Column("rate", sa.Float, nullable=False),  # 1 USD = rate × 本币
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    # seed 常用汇率（静态兜底，定时 job 会刷新）
    op.execute("""
        INSERT INTO currency_rates (code, rate) VALUES
        ('USD', 1.0), ('VND', 25400), ('IDR', 16300), ('THB', 36),
        ('PHP', 58), ('MYR', 4.7), ('SGD', 1.34), ('TWD', 32),
        ('CNY', 7.25), ('HKD', 7.8), ('INR', 83), ('BRL', 5.4),
        ('MXN', 17), ('EUR', 0.93), ('GBP', 0.79),
        ('JPY', 157), ('KRW', 1380), ('AUD', 1.52), ('CAD', 1.36)
        ON CONFLICT (code) DO NOTHING;
    """)

    # currency_rates 是全局引用表（非租户级），不加 RLS
    op.execute("GRANT SELECT ON currency_rates TO toveads_app;")
    op.execute("GRANT SELECT ON currency_rates TO toveads_super;")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS currency_rates;")
    # perf_snapshots 扩的字段不回退（安全）
