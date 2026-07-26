"""投放模板 + 部署 job（launch_templates / launch_jobs / launch_job_items）+ Asset.fb_image_hashes

asset → template → deploy 链路（[[auto-launch-architecture-plan]] 模块 2）。

Revision ID: 0049
Revises: 0048
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "launch_templates",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("objective", sa.Text(), server_default="OUTCOME_SALES"),
        sa.Column("conversion_goal", sa.Text(), server_default=""),
        sa.Column("budget_mode", sa.Text(), server_default="ABO"),
        sa.Column("bid_strategy", sa.Text(), server_default="LOWEST_COST_WITHOUT_CAP"),
        sa.Column("daily_budget", sa.Integer(), server_default="200000"),
        sa.Column("name_prefix", sa.Text(), server_default="Tova Ads"),
        sa.Column("audience_id", sa.Integer(), server_default="0"),
        sa.Column("asset_id", sa.BigInteger(), sa.ForeignKey("assets.id")),
        sa.Column("headline", sa.Text()),
        sa.Column("body", sa.Text()),
        sa.Column("page_id", sa.Text()),
        sa.Column("pixel_id", sa.Text()),
        sa.Column("landing_url", sa.Text()),
        sa.Column("cta_type", sa.Text()),
        sa.Column("subcode_slug", sa.Text()),
        sa.Column("ad_language", sa.Text()),
        sa.Column("status", sa.Text(), server_default="draft"),
        sa.Column("deploy_count", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "launch_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("template_id", sa.BigInteger(), sa.ForeignKey("launch_templates.id")),
        sa.Column("template_name", sa.Text()),
        sa.Column("status", sa.Text(), server_default="pending"),
        sa.Column("total", sa.Integer(), server_default="0"),
        sa.Column("succeeded", sa.Integer(), server_default="0"),
        sa.Column("failed", sa.Integer(), server_default="0"),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "launch_job_items",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("job_id", sa.BigInteger(), sa.ForeignKey("launch_jobs.id"), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("act_id", sa.Text(), nullable=False),
        sa.Column("page_id", sa.Text()),
        sa.Column("pixel_id", sa.Text()),
        sa.Column("status", sa.Text(), server_default="pending"),
        sa.Column("campaign_id", sa.Text()),
        sa.Column("adset_id", sa.Text()),
        sa.Column("ad_id", sa.Text()),
        sa.Column("subcode_slug", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    # Asset 加 fb_image_hashes（每账户缓存 FB image_hash）
    op.add_column("assets", sa.Column("fb_image_hashes", sa.Text()))
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_super;")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO toveads_super;")


def downgrade():
    op.drop_column("assets", "fb_image_hashes")
    op.drop_table("launch_job_items")
    op.drop_table("launch_jobs")
    op.drop_table("launch_templates")
