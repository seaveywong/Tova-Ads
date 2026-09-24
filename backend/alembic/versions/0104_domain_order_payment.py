"""0104: 域名订单支付方式字段（USDT 轻量预留，2026-09-24）

domain_orders.payment_method varchar(16) server_default 'usdt'——全站暂统一 USDT，
后续支付宝/卡等只加枚举值不改表。钱包（余额/冻结/自动扣）是 P0 计费地基批，
本迁移只留支付方式位，不动状态机。
"""
from alembic import op
import sqlalchemy as sa

revision = "0104"
down_revision = "0103"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("domain_orders",
                  sa.Column("payment_method", sa.String(16), nullable=False,
                            server_default="usdt"))
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON domain_orders TO toveads_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON domain_orders TO toveads_super")


def downgrade() -> None:
    op.drop_column("domain_orders", "payment_method")
