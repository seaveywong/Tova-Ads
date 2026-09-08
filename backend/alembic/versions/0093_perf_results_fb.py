"""0093: perf_snapshots 加 results_fb（FB 口径成效——只算优化目标 action 类型）

用户对齐 FB Ads Manager 数字（方案 B 双列）：conversions=综合转化（含兜底，止损用），
results_fb=FB 口径成效（只算优化目标的 action，展示用——跟 FB 后台数字一致）。
"""
from alembic import op
import sqlalchemy as sa

revision = "0093"
down_revision = "0092"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("perf_snapshots", sa.Column("results_fb", sa.Integer, server_default="0"))
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON perf_snapshots TO toveads_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON perf_snapshots TO toveads_super")


def downgrade() -> None:
    op.drop_column("perf_snapshots", "results_fb")
