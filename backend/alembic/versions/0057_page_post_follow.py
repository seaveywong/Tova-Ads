"""跟帖模式 Phase 1：page_posts 表 + 各表加列（建帖→object_story_id 基础设施）

object_story_spec 被 dev app code3 拒 → 改走 object_story_id（先建主页帖再引用）。
- accounts.keepalive_post_id：保活种子帖 id（per 账户复用，不重复建）
- fb_apps.access_level：standard/dev（dev=走建帖 object_story_id；standard=走 object_story_spec）
- launch_templates.post_source：new(建帖)/reuse(跟帖) + reuse_post_ref（跟帖引用 post_id）—— Phase 2 UI 用
- launch_job_items.page_post_id：部署后存的帖 id
- page_posts：建过的主页帖缓存（同页同素材同文案→复用一帖），唯一 (tenant_id,page_id,body_hash)

Revision ID: 0057
Revises: 0056
Create Date: 2026-07-31
"""
from alembic import op
import sqlalchemy as sa

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("accounts", sa.Column("keepalive_post_id", sa.Text()))
    op.add_column("fb_apps", sa.Column("access_level", sa.Text(), nullable=False, server_default="dev"))
    op.add_column("launch_templates", sa.Column("post_source", sa.Text(), server_default="new"))
    op.add_column("launch_templates", sa.Column("reuse_post_ref", sa.Text()))
    op.add_column("launch_job_items", sa.Column("page_post_id", sa.Text()))
    op.create_table(
        "page_posts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("page_id", sa.Text(), nullable=False),
        sa.Column("post_id", sa.Text(), nullable=False),
        sa.Column("asset_id", sa.BigInteger()),
        sa.Column("message", sa.Text()),
        sa.Column("link", sa.Text()),
        sa.Column("body_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "page_id", "body_hash", name="uq_page_posts_tenant_page_hash"),
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_super;")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO toveads_super;")


def downgrade():
    op.drop_table("page_posts")
    op.drop_column("launch_job_items", "page_post_id")
    op.drop_column("launch_templates", "reuse_post_ref")
    op.drop_column("launch_templates", "post_source")
    op.drop_column("fb_apps", "access_level")
    op.drop_column("accounts", "keepalive_post_id")
