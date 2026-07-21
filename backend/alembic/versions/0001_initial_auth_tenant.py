"""initial: auth & tenant core + RLS

核心表：platform_admins / tenants / users / tenant_memberships / invitations
RLS：tenant_memberships / invitations 按 tenant_id 隔离（见 doc 01/09/10）

Revision ID: 0001
Revises:
Create Date: 2026-07-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ===== 平台级（全局，无 tenant_id）=====
    op.create_table(
        "platform_admins",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("email", sa.Text, nullable=False, unique=True),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("is_superadmin", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("status", sa.Text, nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ===== 租户 =====
    op.create_table(
        "tenants",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="active"),  # active/suspended/deleted
        sa.Column("plan", sa.Text, nullable=False, server_default="internal"),
        sa.Column("sentinel_timeout_min", sa.Integer, nullable=False, server_default="30"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ===== 用户（全局，一人可属多租户）=====
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("email", sa.Text, nullable=False, unique=True),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="active"),
        sa.Column("last_active_at", sa.DateTime(timezone=True)),  # 喂自动哨兵
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ===== 用户-租户-角色 多对多 =====
    op.create_table(
        "tenant_memberships",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.Text, nullable=False, server_default="operator"),  # owner/operator/finance
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_membership_tenant_user"),
    )
    op.create_index("ix_memberships_tenant", "tenant_memberships", ["tenant_id"])
    op.create_index("ix_memberships_user", "tenant_memberships", ["user_id"])

    # ===== 邀请码 =====
    op.create_table(
        "invitations",
        sa.Column("code", sa.Text, primary_key=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("created_by", sa.BigInteger, sa.ForeignKey("users.id")),
        sa.Column("used_by", sa.BigInteger, sa.ForeignKey("users.id")),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_invitations_tenant", "invitations", ["tenant_id"])

    # ===== RLS（tenant_memberships / invitations 按 tenant_id 隔离）=====
    op.execute("ALTER TABLE tenant_memberships ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE tenant_memberships FORCE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY tenant_iso ON tenant_memberships FOR ALL "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint);"
    )
    op.execute("ALTER TABLE invitations ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE invitations FORCE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY tenant_iso ON invitations FOR ALL "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint);"
    )

    # 应用角色授权
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO toveads_app;")


def downgrade() -> None:
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM toveads_app;")
    op.execute("DROP TABLE IF EXISTS invitations;")
    op.execute("DROP TABLE IF EXISTS tenant_memberships;")
    op.execute("DROP TABLE IF EXISTS users;")
    op.execute("DROP TABLE IF EXISTS tenants;")
    op.execute("DROP TABLE IF EXISTS platform_admins;")
