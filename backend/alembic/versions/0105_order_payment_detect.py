"""0105: 域名订单到账检测字段（USDT 监听批，2026-09-24）

payment_txid / paid_amount：TronGrid 检测到匹配入账时落证据，pending_payment →
payment_detected（超管一键确认后注册）。
"""
from alembic import op
import sqlalchemy as sa

revision = "0105"
down_revision = "0104"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("domain_orders", sa.Column("payment_txid", sa.Text))
    op.add_column("domain_orders", sa.Column("paid_amount", sa.Float))
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON domain_orders TO toveads_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON domain_orders TO toveads_super")


def downgrade() -> None:
    op.drop_column("domain_orders", "paid_amount")
    op.drop_column("domain_orders", "payment_txid")
