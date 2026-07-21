"""certified_pages：受监管地区（TW/SG/HK）认证主页 + verified_identity_id（审计项目4，合规红线）

Revision ID: 0008
Revises: 0007

为什么有这张表：
FB API 不暴露 verified_identity_id，但 TW/SG 受监管广告的 AdSet 需要数字身份 ID
（regional_regulation_identities.{region}_universal_beneficiary/payer）。
唯一可行方案：用户在 FB BM 后台手动找到数字身份 ID → 录入此表 → 铺广告时按 region 注入。
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

_RLS = ["certified_pages"]
_POLICY = "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint)"


def upgrade() -> None:
    op.create_table(
        "certified_pages",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("created_by", sa.BigInteger, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("region", sa.Text, nullable=False),  # TW / SG / HK
        sa.Column("page_id", sa.Text, nullable=False),  # FB 主页 id
        sa.Column("page_name", sa.Text),  # 显示名（可选）
        # 数字身份 ID（FB 要求数字；从 BM 后台手抄）—— 受监管广告 AdSet 注入用
        sa.Column("beneficiary_identity_id", sa.Text, nullable=False),
        sa.Column("payer_identity_id", sa.Text),  # 可与 beneficiary 相同
        sa.Column("beneficiary_name", sa.Text),  # 受益方显示名（可选）
        sa.Column("payer_name", sa.Text),  # 付款方显示名（可选）
        sa.Column("status", sa.Text, server_default="active"),  # active/disabled
        sa.Column("note", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "region", "page_id", name="uq_certified_region_page"),
    )
    op.create_index("ix_certified_tenant", "certified_pages", ["tenant_id"])
    op.create_index("ix_certified_region", "certified_pages", ["tenant_id", "region", "status"])

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
