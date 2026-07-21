"""landing_events（落地页事件）+ landing_pages.ingest_secret（doc 04 转化归因 / 落地追踪）

Revision ID: 0019
Revises: 0018

事件类型：visit/click/submit/block/redirect/pass/error。
存事件供 stats + 转化归因（max(FB, 落地点击)）+ 防重粉 + 子码自动绑。
ingest_secret：每页生成（token_urlsafe），Worker 携带 X-Edge-Secret 校验（公开端点安全模型）。
"""
from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

_RLS = ["landing_events"]
_POLICY = "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint)"


def upgrade() -> None:
    op.create_table(
        "landing_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id")),
        sa.Column("page_id", sa.BigInteger),  # landing_pages.id（可空，slug 路由的事件可能无 page_id）
        sa.Column("event_type", sa.Text, nullable=False),  # visit/click/submit/block/redirect/pass/error
        sa.Column("slug", sa.Text),           # 子码 /a/{slug}
        sa.Column("ad_id", sa.Text),
        sa.Column("path", sa.Text),
        sa.Column("target_url", sa.Text),
        sa.Column("decision", sa.Text),       # allow/block/redirect
        sa.Column("reason", sa.Text),         # block 原因（country_block 等）
        sa.Column("country", sa.Text), sa.Column("region", sa.Text), sa.Column("city", sa.Text),
        sa.Column("colo", sa.Text), sa.Column("asn", sa.Text),
        sa.Column("platform", sa.Text),       # facebook/instagram/...
        sa.Column("device_type", sa.Text), sa.Column("browser", sa.Text), sa.Column("os", sa.Text),
        sa.Column("user_agent", sa.Text),
        sa.Column("ip_hash", sa.Text),        # 加盐 SHA-256（非原始 IP）
        sa.Column("visitor_id", sa.Text),     # cookie（visitor_id）
        sa.Column("referrer", sa.Text),
        sa.Column("metadata", sa.Text),       # JSON
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_landing_events_page", "landing_events", ["page_id", "created_at"])
    op.create_index("ix_landing_events_slug", "landing_events", ["slug", "event_type", "created_at"])
    op.create_index("ix_landing_events_ad", "landing_events", ["ad_id", "event_type", "created_at"])

    # landing_pages 加 ingest_secret
    op.add_column("landing_pages", sa.Column("ingest_secret", sa.Text))

    for t in _RLS:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY;")
        op.execute(f"CREATE POLICY tenant_iso ON {t} FOR ALL {_POLICY};")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_super;")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO toveads_super;")


def downgrade() -> None:
    op.drop_column("landing_pages", "ingest_secret")
    op.execute("DROP TABLE IF EXISTS landing_events;")
