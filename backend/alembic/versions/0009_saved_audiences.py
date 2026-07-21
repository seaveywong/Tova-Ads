"""saved_audiences：受众模板库（审计项目16，v1 仅兴趣受众：search+save+use+edit）

Revision ID: 0009
Revises: 0008

v1 范围：仅 flexible_spec 兴趣受众（无 custom_audiences / lookalikes，v2 再做）。
interests_json = [{id, name}, ...]；strategy = broad_interest / broad_only / interest_only。
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

_RLS = ["saved_audiences"]
_POLICY = "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint)"


def upgrade() -> None:
    op.create_table(
        "saved_audiences",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("created_by", sa.BigInteger, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("interests_json", sa.Text, server_default="[]"),  # [{id,name}, ...]
        sa.Column("countries", sa.Text, server_default="[]"),  # JSON ["US","TW"]
        sa.Column("age_min", sa.Integer, server_default="18"),
        sa.Column("age_max", sa.Integer, server_default="65"),
        sa.Column("gender", sa.Integer, server_default="0"),  # 0=all 1=male 2=female
        sa.Column("strategy", sa.Text, server_default="broad_interest"),  # broad_interest/broad_only/interest_only
        sa.Column("note", sa.Text),
        sa.Column("status", sa.Text, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_saved_audiences_tenant", "saved_audiences", ["tenant_id"])

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
