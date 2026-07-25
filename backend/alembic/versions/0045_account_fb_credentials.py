"""account_fb_credentials 多令牌同账户多对多 + 迁移现有单绑 + RLS

Revision ID: 0045
Revises: 0044
Create Date: 2026-07-25

一账户绑多 token（多对多），替代单绑 accounts.fb_credential_id（保留作主令牌/兼容）。
priority 排序 + 轮询分流（可用率 100%）。
"""
from alembic import op
import sqlalchemy as sa

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "account_fb_credentials",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("account_id", sa.BigInteger(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("fb_credential_id", sa.BigInteger(), sa.ForeignKey("fb_credentials.id"), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="0"),
        sa.Column("status", sa.Text(), server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("account_id", "fb_credential_id", name="uq_acct_cred"),
    )
    op.create_index("ix_acct_cred_account_status", "account_fb_credentials", ["account_id", "status"])
    op.create_index("ix_acct_cred_cred", "account_fb_credentials", ["fb_credential_id"])
    # 迁移现有单绑：accounts.fb_credential_id → account_fb_credentials (priority=0 主令牌)
    op.execute("""
        INSERT INTO account_fb_credentials (tenant_id, account_id, fb_credential_id, priority, status)
        SELECT tenant_id, id, fb_credential_id, 0, 'active'
        FROM accounts
        WHERE fb_credential_id IS NOT NULL
    """)
    # RLS（多租户隔离，同其他表）
    op.execute("ALTER TABLE account_fb_credentials ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE account_fb_credentials FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY account_fb_credentials_tenant_iso ON account_fb_credentials "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint)"
    )


def downgrade():
    op.execute("DROP POLICY IF EXISTS account_fb_credentials_tenant_iso ON account_fb_credentials")
    op.drop_index("ix_acct_cred_cred", table_name="account_fb_credentials")
    op.drop_index("ix_acct_cred_account_status", table_name="account_fb_credentials")
    op.drop_table("account_fb_credentials")
