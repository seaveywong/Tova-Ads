"""assets + landing_pages + landing_ad_links (子码)

铺广告链路的数据基础（doc 02/04/10）。

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_RLS_TABLES = ["assets", "landing_pages", "landing_ad_links"]
_POLICY = (
    "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint)"
)


def upgrade() -> None:
    # ===== 素材 =====
    op.create_table(
        "assets",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("owner_user_id", sa.BigInteger, sa.ForeignKey("users.id")),
        sa.Column("type", sa.Text, nullable=False),  # image/video
        sa.Column("storage_key", sa.Text, nullable=False),  # R2 key
        sa.Column("filename", sa.Text),
        sa.Column("ai_copy", sa.Text),  # AI 生成的文案
        sa.Column("is_manual", sa.Boolean, server_default=sa.text("false")),  # 手动文案标记
        sa.Column("manual_copy", sa.Text),  # 手动补充文案（铺广告优先用这个）
        sa.Column("category", sa.Text, server_default="常规"),  # 常规/预热素材
        sa.Column("fb_image_hash", sa.Text),  # 上传到 FB 后的 hash
        sa.Column("status", sa.Text, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_assets_tenant", "assets", ["tenant_id"])

    # ===== 落地页 =====
    op.create_table(
        "landing_pages",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("owner_user_id", sa.BigInteger, sa.ForeignKey("users.id")),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("template_id", sa.BigInteger),
        sa.Column("domain_kind", sa.Text, server_default="mira_hosted"),  # mira_hosted/external_url
        sa.Column("custom_domain", sa.Text),
        sa.Column("target_urls", sa.Text),  # JSON array
        sa.Column("rotation_mode", sa.Text, server_default="first"),  # first/random
        sa.Column("pixel_id", sa.Text),
        sa.Column("protection_rules", sa.Text),  # JSON
        sa.Column("status", sa.Text, server_default="draft"),  # draft/published/archived
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_landing_pages_tenant", "landing_pages", ["tenant_id"])

    # ===== 子码（landing_ad_links）=====
    op.create_table(
        "landing_ad_links",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("page_id", sa.BigInteger, sa.ForeignKey("landing_pages.id")),
        sa.Column("slug", sa.Text, nullable=False, unique=True),
        sa.Column("ad_id", sa.Text),  # FB 广告 ID（首次点击后回绑）
        sa.Column("act_id", sa.Text),  # 广告账户 ID（必填，防误杀——doc 04 不变量 4-5）
        sa.Column("target_urls", sa.Text),  # JSON（覆盖落地页全局）
        sa.Column("status", sa.Text, server_default="reserved"),  # reserved/active/failed/paused/archived/unused
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_ad_links_tenant", "landing_ad_links", ["tenant_id"])
    op.create_index("ix_ad_links_slug", "landing_ad_links", ["slug"])
    op.create_index("ix_ad_links_act", "landing_ad_links", ["act_id"])

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
