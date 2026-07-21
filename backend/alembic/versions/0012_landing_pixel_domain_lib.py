"""landing_pixels + landing_domains：像素库 + 域名库（落地页重做，决策 2/6）

Revision ID: 0012
Revises: 0011

按租户隔离（决策②）。用量统计（决策⑥）不存表，按需子查询 landing_pages：
- landing_pixels 用量 = count(landing_pages WHERE pixel_ids 含此像素)
- landing_domains 用量 = count(landing_pages WHERE custom_domain = 此域名)
（landing_pages 迁移到 pixel_ids JSON 后生效；现阶段 pixel_id 单值。）
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

_RLS = ["landing_pixels", "landing_domains"]
_POLICY = "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint)"


def upgrade() -> None:
    # 像素库
    op.create_table(
        "landing_pixels",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("created_by", sa.BigInteger, sa.ForeignKey("users.id")),
        sa.Column("pixel_id", sa.Text, nullable=False),  # FB 像素数字 ID（明文，决策⑦）
        sa.Column("pixel_name", sa.Text),                # 友好名（FENG-0706 等）
        sa.Column("note", sa.Text),
        sa.Column("status", sa.Text, server_default="active"),  # active/disabled
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "pixel_id", name="uq_landing_pixels_tenant_pixel"),
    )
    op.create_index("ix_landing_pixels_tenant", "landing_pixels", ["tenant_id", "status"])

    # 域名库（按租户隔离）
    op.create_table(
        "landing_domains",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("created_by", sa.BigInteger, sa.ForeignKey("users.id")),
        sa.Column("domain", sa.Text, nullable=False),
        sa.Column("label", sa.Text),                    # 友好名
        sa.Column("source", sa.Text, server_default="manual"),  # manual/discovered
        sa.Column("cf_zone_status", sa.Text),           # active/pending_nameserver/error（CF 联动状态）
        sa.Column("note", sa.Text),
        sa.Column("status", sa.Text, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "domain", name="uq_landing_domains_tenant_domain"),
    )
    op.create_index("ix_landing_domains_tenant", "landing_domains", ["tenant_id", "status"])

    for t in _RLS:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY;")
        op.execute(f"CREATE POLICY tenant_iso ON {t} FOR ALL {_POLICY};")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_super;")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO toveads_super;")


def downgrade() -> None:
    for t in reversed(_RLS):
        op.execute(f"DROP TABLE IF EXISTS {t};")
