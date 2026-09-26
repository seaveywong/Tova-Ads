"""0106: 域名订单收款地址池字段（2026-09-26 用户拍板：收款地址=地址池）

payment_address：下单时从池中轮询分配给本单的收款地址——多地址分散资金流（隐私/风控），
且地址本身即对账维度（同尾号订单分到不同地址，彻底防串单）。空=兼容单地址模式（监听回落
首个池地址）。
"""
from alembic import op
import sqlalchemy as sa

revision = "0106"
down_revision = "0105"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("domain_orders", sa.Column("payment_address", sa.Text))
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON domain_orders TO toveads_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON domain_orders TO toveads_super")


def downgrade() -> None:
    op.drop_column("domain_orders", "payment_address")
