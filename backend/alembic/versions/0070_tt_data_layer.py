"""TikTok 接入 P0 数据层：tt_credentials / account_tt_credentials / tt_apps + accounts 平台列

- accounts.platform（'fb'/'tt'，存量行 server_default 回填 'fb'）+ accounts.tt_credential_id
  （TT 主令牌，同 fb_credential_id 语义；候选池在 account_tt_credentials）。
- tt_credentials：TikTok 授权令牌（access 24h / refresh 365d，加密存）。
- account_tt_credentials：多令牌同账户多对多（照 account_fb_credentials/0045 模式）。
- tt_apps：TikTok App 配置（照 fb_apps/0023 模式；无 access_level——FB dev/standard 专属语义）。

纯增量：不改任何 FB 存量行/约束，FB 路径行为不变。

Revision ID: 0070
Revises: 0069
Create Date: 2026-09-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0070"
down_revision = "0069"
branch_labels = None
depends_on = None

_TENANT_TABLES = ["tt_credentials", "account_tt_credentials"]


def upgrade() -> None:
    # ── 3 张新表 ──
    op.create_table(
        "tt_credentials",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("owner_user_id", sa.BigInteger, sa.ForeignKey("users.id")),
        sa.Column("alias", sa.Text),
        sa.Column("app_id", sa.Text, nullable=False),
        sa.Column("advertiser_id", sa.Text),
        sa.Column("access_token_enc", sa.Text, nullable=False),
        sa.Column("refresh_token_enc", sa.Text),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("refresh_expires_at", sa.DateTime(timezone=True)),
        sa.Column("token_source", sa.Text, server_default="oauth"),
        sa.Column("status", sa.Text, server_default="active"),
        sa.Column("scopes", sa.Text),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True)),
        sa.Column("consecutive_fails", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_tt_credentials_tenant", "tt_credentials", ["tenant_id"])
    op.create_index("ix_tt_credentials_status", "tt_credentials", ["status"])

    op.create_table(
        "account_tt_credentials",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("account_id", sa.BigInteger, sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("tt_credential_id", sa.BigInteger, sa.ForeignKey("tt_credentials.id"), nullable=False),
        sa.Column("status", sa.Text, server_default="active"),
        sa.Column("priority", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("account_id", "tt_credential_id", name="uq_acct_tt_cred"),
    )
    op.create_index("ix_acct_tt_cred_account_status", "account_tt_credentials", ["account_id", "status"])
    op.create_index("ix_acct_tt_cred_cred", "account_tt_credentials", ["tt_credential_id"])

    op.create_table(
        "tt_apps",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), nullable=True),  # NULL=系统级
        sa.Column("name", sa.Text),
        sa.Column("app_id", sa.Text, nullable=False),
        sa.Column("app_secret_enc", sa.Text, nullable=False),
        sa.Column("is_system", sa.Boolean, server_default="false"),
        sa.Column("status", sa.Text, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_tt_apps_system", "tt_apps", ["is_system"])
    op.create_index("ix_tt_apps_tenant", "tt_apps", ["tenant_id"])

    # ── accounts 平台列（存量行自动回填 'fb'）──
    op.add_column("accounts", sa.Column("platform", sa.Text(), nullable=False, server_default="fb"))
    op.add_column("accounts", sa.Column("tt_credential_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key("fk_accounts_tt_cred", "accounts", "tt_credentials",
                          ["tt_credential_id"], ["id"])

    # ── RLS（0065 模式：租户表 fail-closed tenant_iso）──
    for t in _TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_iso ON {t};")
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"CREATE POLICY tenant_iso ON {t} FOR ALL "
            "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint);")
    # tt_apps：照 fb_apps（0023）——系统级行（tenant_id IS NULL）对所有租户可见
    op.execute("DROP POLICY IF EXISTS tt_apps_tenant ON tt_apps;")
    op.execute("ALTER TABLE tt_apps ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE tt_apps FORCE ROW LEVEL SECURITY;")
    op.execute("""CREATE POLICY tt_apps_tenant ON tt_apps
        FOR ALL
        USING (tenant_id IS NULL OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint)
        WITH CHECK (tenant_id IS NULL OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint);""")

    # ── GRANT（leads_id_seq 教训：新表 DML + 序列 USAGE 双角色都显式授）──
    for t in ["tt_credentials", "account_tt_credentials", "tt_apps"]:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO toveads_app")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO toveads_super")
    for seq in ["tt_credentials_id_seq", "account_tt_credentials_id_seq", "tt_apps_id_seq"]:
        op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {seq} TO toveads_app")
        op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {seq} TO toveads_super")


def downgrade() -> None:
    op.drop_constraint("fk_accounts_tt_cred", "accounts", type_="foreignkey")
    op.drop_column("accounts", "tt_credential_id")
    op.drop_column("accounts", "platform")
    op.execute("DROP POLICY IF EXISTS tt_apps_tenant ON tt_apps;")
    op.drop_index("ix_tt_apps_tenant", table_name="tt_apps")
    op.drop_index("ix_tt_apps_system", table_name="tt_apps")
    op.drop_table("tt_apps")
    op.execute("DROP POLICY IF EXISTS tenant_iso ON account_tt_credentials;")
    op.drop_index("ix_acct_tt_cred_cred", table_name="account_tt_credentials")
    op.drop_index("ix_acct_tt_cred_account_status", table_name="account_tt_credentials")
    op.drop_table("account_tt_credentials")
    op.execute("DROP POLICY IF EXISTS tenant_iso ON tt_credentials;")
    op.drop_index("ix_tt_credentials_status", table_name="tt_credentials")
    op.drop_index("ix_tt_credentials_tenant", table_name="tt_credentials")
    op.drop_table("tt_credentials")
