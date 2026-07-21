"""fb_apps 表（Facebook App 配置：系统级 + 团队）

Revision ID: 0023
Revises: 0022

系统级 App（is_system=true）：全租户共享（超管创建，所有租户可用授权）
团队 App（is_system=false）：租户私有（owner 创建，仅自己租户）
"""
from alembic import op
import sqlalchemy as sa

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fb_apps",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), nullable=True),  # NULL=系统级
        sa.Column("name", sa.Text),
        sa.Column("app_id", sa.Text, nullable=False),
        sa.Column("app_secret_enc", sa.Text, nullable=False),
        sa.Column("is_system", sa.Boolean, server_default="false"),  # true=全租户共享
        sa.Column("status", sa.Text, server_default="active"),
        sa.Column("created_by", sa.BigInteger),  # user_id（超管 or owner）
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_fb_apps_system", "fb_apps", ["is_system"])
    op.create_index("ix_fb_apps_tenant", "fb_apps", ["tenant_id"])
    # RLS：团队 App 按 tenant_id 隔离（系统级 app tenant_id=NULL，超管 super session 可见）
    op.execute("ALTER TABLE fb_apps ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE fb_apps FORCE ROW LEVEL SECURITY;")
    # 系统级 App（tenant_id IS NULL）+ 自己租户的 App 都可见
    op.execute("""CREATE POLICY fb_apps_tenant ON fb_apps
        FOR ALL
        USING (tenant_id IS NULL OR tenant_id = current_setting('app.tenant_id', true)::bigint)
        WITH CHECK (tenant_id IS NULL OR tenant_id = current_setting('app.tenant_id', true)::bigint);""")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON fb_apps TO toveads_app;")
    op.execute("GRANT SELECT ON fb_apps TO toveads_super;")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS fb_apps;")
