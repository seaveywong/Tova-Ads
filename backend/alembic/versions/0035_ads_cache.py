"""ads_cache: 广告实体缓存（巡检顺便拉，广告管理器读缓存跨账户汇总，0 FB）

Revision ID: 0035
Revises: 0034
"""
from alembic import op
import sqlalchemy as sa

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ads_cache",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("act_id", sa.Text, nullable=False),
        sa.Column("campaigns_json", sa.Text),
        sa.Column("adsets_json", sa.Text),
        sa.Column("ads_json", sa.Text),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_ads_cache_tenant_act", "ads_cache", ["tenant_id", "act_id"], unique=True)
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ads_cache TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ads_cache TO toveads_super;")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE ads_cache_id_seq TO toveads_app;")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE ads_cache_id_seq TO toveads_super;")


def downgrade() -> None:
    op.drop_table("ads_cache")
