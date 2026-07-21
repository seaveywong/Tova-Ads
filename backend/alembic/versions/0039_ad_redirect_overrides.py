"""ad_redirect_overrides: 广告级跳转链接覆盖（按 ad_id 给单条广告单独 target_url）

Revision ID: 0039
Revises: 0038
"""
from alembic import op
import sqlalchemy as sa

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ad_redirect_overrides",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("ad_id", sa.Text, nullable=False),
        sa.Column("target_url", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_ad_redirect_overrides_tenant_ad", "ad_redirect_overrides",
                    ["tenant_id", "ad_id"], unique=True)
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ad_redirect_overrides TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ad_redirect_overrides TO toveads_super;")
    # BigInteger 主键隐式 sequence 也要授权（建表 GRANT 坑）
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO toveads_super;")


def downgrade() -> None:
    op.drop_index("ix_ad_redirect_overrides_tenant_ad", table_name="ad_redirect_overrides")
    op.drop_table("ad_redirect_overrides")
