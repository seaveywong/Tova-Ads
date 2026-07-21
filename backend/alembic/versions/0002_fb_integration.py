"""fb integration: fb_credentials + token_health + accounts

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_RLS_TABLES = ["fb_credentials", "token_health", "accounts"]
_POLICY = (
    "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint)"
)


def upgrade() -> None:
    # ===== FB 凭证（每租户加密）=====
    op.create_table(
        "fb_credentials",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("type", sa.Text, nullable=False, server_default="user_token"),  # user_token/oauth_app
        sa.Column("access_token_enc", sa.Text, nullable=False),
        sa.Column("refresh_token_enc", sa.Text),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("scopes", sa.Text),  # JSON
        sa.Column("fb_user_id", sa.Text),
        sa.Column("fb_user_name", sa.Text),
        sa.Column("status", sa.Text, nullable=False, server_default="active"),  # active/expired/revoked
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_fb_creds_tenant", "fb_credentials", ["tenant_id"])

    # ===== Token 健康监测（10min 同步缓存）=====
    op.create_table(
        "token_health",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("fb_credential_id", sa.BigInteger, sa.ForeignKey("fb_credentials.id"), nullable=False),
        sa.Column("valid", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("error_category", sa.Text),
        sa.Column("error_friendly", sa.Text),
    )
    op.create_index("ix_token_health_tenant", "token_health", ["tenant_id"])

    # ===== 广告账户（运营导入 + 归属）=====
    op.create_table(
        "accounts",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("fb_credential_id", sa.BigInteger, sa.ForeignKey("fb_credentials.id")),
        sa.Column("act_id", sa.Text, nullable=False),  # FB 广告账户 ID（裸数字）
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("currency", sa.Text, nullable=False, server_default="USD"),
        sa.Column("timezone_name", sa.Text, nullable=False, server_default="UTC"),
        sa.Column("owner_user_id", sa.BigInteger, sa.ForeignKey("users.id")),  # 负责运营
        sa.Column("account_status", sa.Integer, server_default=sa.text("1")),
        sa.Column("balance", sa.Text),
        sa.Column("spend_cap", sa.Text),
        sa.Column("amount_spent", sa.Text),
        sa.Column("warmup_state", sa.Text, server_default="none"),
        sa.Column("last_warmup_at", sa.DateTime(timezone=True)),
        sa.Column("sentinel_armed", sa.Boolean, server_default=sa.text("false")),
        sa.Column("sentinel_auto_armed", sa.Boolean, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "act_id", name="uq_accounts_tenant_actid"),
    )
    op.create_index("ix_accounts_tenant", "accounts", ["tenant_id"])
    op.create_index("ix_accounts_owner", "accounts", ["owner_user_id"])

    # ===== RLS =====
    for t in _RLS_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY;")
        op.execute(f"CREATE POLICY tenant_iso ON {t} FOR ALL {_POLICY};")

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_super;")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO toveads_super;")


def downgrade() -> None:
    for t in reversed(_RLS_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t};")
