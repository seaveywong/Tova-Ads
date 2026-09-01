"""email_routes 表：CF Email Routing 转发映射（平台级，超管自助配 tovaads.com 邮箱）

照 tt_apps（0070 建表 + 0075 收紧）先例：tenant_id 可空列、系统级行 tenant_id IS NULL。
policy USING 放行系统行读取；WITH CHECK 收紧（租户会话只写本租户行——
本表全部行为系统级，正常写路径走 SuperSessionLocal/BYPASSRLS，不受影响）。

GRANT：DML 双角色 + 序列 USAGE（leads_id_seq 教训）。

Revision ID: 0077
Revises: 0076
"""
from alembic import op
import sqlalchemy as sa

revision = "0077"
down_revision = "0076"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_routes",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), nullable=True),  # NULL=系统级
        sa.Column("alias", sa.Text, nullable=False),          # @ 前部分，如 dev
        sa.Column("destination_email", sa.Text, nullable=False),  # CF 已验证目的地邮箱
        sa.Column("rule_id", sa.Text),                        # CF 转发规则 id
        sa.Column("enabled", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("alias", name="uq_email_routes_alias"),
    )
    op.create_index("ix_email_routes_tenant", "email_routes", ["tenant_id"])

    # RLS（0070+0075 模式：系统行可读，租户会话只写自己行）
    op.execute("DROP POLICY IF EXISTS email_routes_tenant ON email_routes;")
    op.execute("ALTER TABLE email_routes ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE email_routes FORCE ROW LEVEL SECURITY;")
    op.execute("""CREATE POLICY email_routes_tenant ON email_routes
        FOR ALL
        USING (tenant_id IS NULL OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint)
        WITH CHECK (tenant_id IS NOT NULL AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint);""")

    # GRANT（DML + 序列，双角色）
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON email_routes TO toveads_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON email_routes TO toveads_super")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE email_routes_id_seq TO toveads_app")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE email_routes_id_seq TO toveads_super")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS email_routes_tenant ON email_routes;")
    op.drop_index("ix_email_routes_tenant", table_name="email_routes")
    op.drop_table("email_routes")
