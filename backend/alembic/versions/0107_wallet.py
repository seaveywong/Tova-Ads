"""0107: 钱包（批1，方案 toveads/钱包计费方案.md v2）

wallet_accounts：团队级余额账户（tenant 唯一；行锁+version 乐观锁）。
wallet_txns：唯一记账流水（balance_after 快照；(ref_type, ref_id, type) 唯一=幂等）。
wallet_topups：USDT-TRC20 充值单（与域名订单同款监听/地址池/尾号对账）。
"""
from alembic import op
import sqlalchemy as sa

revision = "0107"
down_revision = "0106"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("wallet_accounts",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), nullable=False, unique=True, index=True),
        sa.Column("balance_usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_table("wallet_txns",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("amount_usd", sa.Float, nullable=False),
        sa.Column("balance_after", sa.Float, nullable=False),
        sa.Column("ref_type", sa.Text, nullable=False),
        sa.Column("ref_id", sa.BigInteger),
        sa.Column("txid", sa.Text),
        sa.Column("note", sa.Text),
        sa.Column("created_by", sa.BigInteger),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("ref_type", "ref_id", "type", name="uq_wallet_txn_ref"))
    op.create_table("wallet_topups",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("created_by", sa.BigInteger),
        sa.Column("amount_usd", sa.Float, nullable=False),
        sa.Column("pay_amount", sa.Float, nullable=False),
        sa.Column("payment_address", sa.Text),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("txid", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("paid_at", sa.DateTime(timezone=True)))
    for tbl in ("wallet_accounts", "wallet_txns", "wallet_topups"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tbl} TO toveads_app")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tbl} TO toveads_super")


def downgrade() -> None:
    op.drop_table("wallet_topups")
    op.drop_table("wallet_txns")
    op.drop_table("wallet_accounts")
