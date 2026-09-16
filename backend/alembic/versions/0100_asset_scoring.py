"""素材评分：asset_ad_links（素材↔广告 hash 匹配链）+ asset_scores（评分快照）

Revision ID: 0100
Revises: 0099
"""
from alembic import op
import sqlalchemy as sa

revision = "0100"
down_revision = "0099"


def upgrade():
    op.create_table(
        "asset_ad_links",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("asset_id", sa.BigInteger(), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("ad_id", sa.Text(), nullable=False),
        sa.Column("act_id", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), server_default="fb", nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("ad_id", "platform", name="uq_asset_ad_links_ad"),
    )
    op.create_index("ix_asset_ad_links_asset", "asset_ad_links", ["asset_id"])
    op.create_table(
        "asset_scores",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("asset_id", sa.BigInteger(), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("score", sa.Integer(), nullable=True),          # 0-100；null=未评分（无投放数据）
        sa.Column("grade", sa.Text()),                             # S/A/B/C/D
        sa.Column("dims", sa.Text()),                              # JSON {ctr,conv,conf,cov}
        sa.Column("stats", sa.Text()),                             # JSON 数值明细（弹窗直读）
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("asset_id", name="uq_asset_scores_asset"),
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON asset_ad_links TO toveads_app")
    op.execute("GRANT SELECT ON asset_ad_links TO toveads_super")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON asset_scores TO toveads_app")
    op.execute("GRANT SELECT ON asset_scores TO toveads_super")


def downgrade():
    op.drop_table("asset_scores")
    op.drop_table("asset_ad_links")
