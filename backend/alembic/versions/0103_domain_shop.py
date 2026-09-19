"""域名商店：代购订单表 + landing_domains 月租字段

- domain_orders：Porkbun 代购订单（成本快照/年限/状态机 pending_payment→approved→
  registered→bound / failed / cancelled；全自动链=批准后注册+NS 指向 CF+建 zone+入库）
- landing_domains + rent_usd/billed_until：托管月租预埋（计费接钱包后由 cron 扣，
  本迁移只埋字段；催续 cron 读取 billed_until 发 TG 提醒）
"""
from alembic import op
import sqlalchemy as sa

revision = "0103"
down_revision = "0102"


def upgrade():
    op.create_table(
        "domain_orders",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("years", sa.Integer(), nullable=False, server_default="1"),
        # 成本快照（下单时 Porkbun 实时价，minor→美元浮点；防后续涨价漂移）
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("fee_usd", sa.Float(), nullable=False, server_default="5"),
        sa.Column("total_usd", sa.Float(), nullable=False),
        # pending_payment=等付款（钱包上线后自动冻结扣款；当前=超管人工确认收款）
        # approved=已确认收款 → 自动注册链；registering=注册中；
        # registered=注册成功；bound=已入 CF+域名库（终态成功）；
        # failed=注册失败（原因留 error）；cancelled=取消/退款
        sa.Column("status", sa.Text(), nullable=False, server_default="pending_payment"),
        sa.Column("error", sa.Text()),
        sa.Column("porkbun_order_id", sa.Text()),
        sa.Column("cf_zone_id", sa.Text()),
        sa.Column("approved_by", sa.BigInteger()),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("fulfilled_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_domain_orders_tenant", "domain_orders", ["tenant_id"])
    op.create_index("ix_domain_orders_status", "domain_orders", ["status"])

    op.add_column("landing_domains", sa.Column("rent_usd", sa.Float()))
    op.add_column("landing_domains", sa.Column("billed_until", sa.DateTime(timezone=True)))

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_super")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO toveads_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO toveads_super")


def downgrade():
    op.drop_column("landing_domains", "billed_until")
    op.drop_column("landing_domains", "rent_usd")
    op.drop_index("ix_domain_orders_status", table_name="domain_orders")
    op.drop_index("ix_domain_orders_tenant", table_name="domain_orders")
    op.drop_table("domain_orders")
