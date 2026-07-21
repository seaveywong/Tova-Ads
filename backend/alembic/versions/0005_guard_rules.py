"""guard_rules + guard_ad_allowances（止损规则 + 当日加白）

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

_RLS = ["guard_rules", "guard_ad_allowances"]
_POLICY = "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint)"


def upgrade() -> None:
    op.create_table(
        "guard_rules",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("category", sa.Text, nullable=False),  # 空耗止损/成本超标/效果下滑
        sa.Column("rule_type", sa.Text, nullable=False),  # bleed_abs/cpa_exceed/...
        sa.Column("params", sa.Text),  # JSON: {spend_threshold, days, cpa_target, ...}
        sa.Column("conversion_source", sa.Text, server_default="either"),  # either/fb
        sa.Column("action", sa.Text, server_default="default"),  # observe/default
        sa.Column("enabled", sa.Boolean, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_guard_rules_tenant", "guard_rules", ["tenant_id"])

    op.create_table(
        "guard_ad_allowances",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("act_id", sa.Text, nullable=False),
        sa.Column("ad_id", sa.Text, nullable=False),
        sa.Column("allowance_date", sa.Text, nullable=False),  # YYYY-MM-DD（账户本地日）
        sa.Column("status", sa.Text, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("act_id", "ad_id", "allowance_date", name="uq_allowance_act_ad_date"),
    )
    op.create_index("ix_allowance_lookup", "guard_ad_allowances", ["act_id", "ad_id", "allowance_date"])

    for t in _RLS:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY;")
        op.execute(f"CREATE POLICY tenant_iso ON {t} FOR ALL {_POLICY};")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_super;")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO toveads_super;")


def downgrade() -> None:
    for t in reversed(_RLS):
        op.execute(f"DROP TABLE IF EXISTS {t};")
