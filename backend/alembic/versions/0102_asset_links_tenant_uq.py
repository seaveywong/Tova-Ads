"""asset_ad_links 唯一约束改 (tenant_id, ad_id, platform)——跨租户同 act_id/ad_id 撞全局唯一曾致评分永久瘫痪

Revision ID: 0102
Revises: 0101
"""
from alembic import op

revision = "0102"
down_revision = "0101"


def upgrade():
    op.drop_constraint("uq_asset_ad_links_ad", "asset_ad_links", type_="unique")
    op.create_unique_constraint("uq_asset_ad_links_ad", "asset_ad_links",
                                ["tenant_id", "ad_id", "platform"])
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON asset_ad_links TO toveads_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON asset_ad_links TO toveads_super")


def downgrade():
    op.drop_constraint("uq_asset_ad_links_ad", "asset_ad_links", type_="unique")
    op.create_unique_constraint("uq_asset_ad_links_ad", "asset_ad_links", ["ad_id", "platform"])
