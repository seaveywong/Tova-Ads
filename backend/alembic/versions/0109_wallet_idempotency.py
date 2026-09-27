"""0109: 钱包幂等键重构 + 链上 TXID 防重 + 序列 GRANT 补漏（商用审计 P0 修复，2026-09-27）

背景（审计实证三起资金漏洞同根因——幂等键设计错误/缺失）：
① 旧唯一约束 (ref_type, ref_id, type) 把「业务 ref」当幂等键：续费用域名 row.id → 同域名第二次续费
  被旧流水吞掉扣款却照常续费（免费续费）；重试扣款无法与首次区分。
② 监听 used_txids 仅单轮内存：同一笔链上入账跨轮可再次匹配另一 pending 单（双倍入账/既交付又入账）。
③ 0107 漏 GRANT 序列（BIGSERIAL 需要 USAGE）。

本迁移：
- wallet_txns 加 idempotency 列（nullable，调用方生成的唯一键）+ 部分唯一索引；
  删除旧约束 uq_wallet_txn_ref（ref 转纯对账展示，幂等职责移交 idempotency）。
- domain_orders.payment_txid / wallet_topups.txid 加部分唯一索引（DB 层双保险防跨轮重复消费）。
- 补 wallet 三表序列 GRANT。
"""
from alembic import op
import sqlalchemy as sa

revision = "0109"
down_revision = "0108"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("wallet_txns", sa.Column("idempotency", sa.Text))
    op.execute("CREATE UNIQUE INDEX uq_wallet_txn_idem ON wallet_txns (idempotency) WHERE idempotency IS NOT NULL")
    op.execute("ALTER TABLE wallet_txns DROP CONSTRAINT IF EXISTS uq_wallet_txn_ref")
    op.execute("CREATE UNIQUE INDEX uq_domain_order_txid ON domain_orders (payment_txid) WHERE payment_txid IS NOT NULL")
    op.execute("CREATE UNIQUE INDEX uq_wallet_topup_txid ON wallet_topups (txid) WHERE txid IS NOT NULL")
    for seq in ("wallet_accounts_id_seq", "wallet_txns_id_seq", "wallet_topups_id_seq"):
        op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {seq} TO toveads_app")
        op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {seq} TO toveads_super")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON wallet_txns TO toveads_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON wallet_txns TO toveads_super")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_wallet_topup_txid")
    op.execute("DROP INDEX IF EXISTS uq_domain_order_txid")
    op.execute("DROP INDEX IF EXISTS uq_wallet_txn_idem")
    op.execute("ALTER TABLE wallet_txns ADD CONSTRAINT uq_wallet_txn_ref UNIQUE (ref_type, ref_id, type)")
    op.drop_column("wallet_txns", "idempotency")
