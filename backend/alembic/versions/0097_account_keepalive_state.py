"""accounts 加保活状态列（keepalive_state/keepalive_note）

run_keepalive 每轮把每账户结果落库：
- active_ad  已有/已建保活广告在跑
- has_spend  近期有真实消耗，无需保活
- failed     上次尝试失败（note 存原因）
- burnt      熔断：强绑户连续 2 个主页撞 1815645，等手动「立即保活」重试
前端 Ads 页保活徽标按状态区分显示（曾清一色"保活"看不出实际情况，用户 2026-09-12 要求）。
"""
from alembic import op
import sqlalchemy as sa

revision = "0097"
down_revision = "0096"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("keepalive_state", sa.Text(), nullable=True))
    op.add_column("accounts", sa.Column("keepalive_note", sa.Text(), nullable=True))
    op.execute("GRANT SELECT, UPDATE, INSERT, DELETE ON accounts TO toveads_app")
    op.execute("GRANT SELECT, UPDATE, INSERT, DELETE ON accounts TO toveads_super")


def downgrade() -> None:
    op.drop_column("accounts", "keepalive_note")
    op.drop_column("accounts", "keepalive_state")
