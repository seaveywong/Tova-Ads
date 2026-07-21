"""fb_credentials 加 cooldown_until（限流冷却）+ perf_snapshots 加 KPI 诊断列

Revision ID: 0024
Revises: 0023

学习 1.0 交接包：
- Token 限流冷却（code=17 → rate_limited + cooldown_until）
- KPI 诊断存储（actions_json + resolved_kpi + kpi_source，排查"FB显示X我们显示Y"）
"""
from alembic import op
import sqlalchemy as sa

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # fb_credentials 加 cooldown_until（限流冷却到期时间）
    try:
        op.add_column("fb_credentials", sa.Column("cooldown_until", sa.DateTime(timezone=True)))
    except Exception:
        pass
    # perf_snapshots 加 KPI 诊断列
    for col, typ in [
        ("actions_json", sa.Text),        # FB 回传的原始 actions JSON
        ("resolved_kpi", sa.Text),         # resolver 解析出的 kpi_field（实际用的）
        ("kpi_source", sa.Text),           # 解析来源（manual/matrix/objective_fallback/semantic/user）
    ]:
        try:
            op.add_column("perf_snapshots", sa.Column(col, typ))
        except Exception:
            pass


def downgrade() -> None:
    pass
