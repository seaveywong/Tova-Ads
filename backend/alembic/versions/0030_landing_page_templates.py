"""landing_page_templates 表（租户上传落地页 HTML 模板，zip 解压取 index.html + 文本资源）

Revision ID: 0030
Revises: 0029
"""
from alembic import op
import sqlalchemy as sa

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "landing_page_templates",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("html", sa.Text, nullable=False),
        sa.Column("resources_meta", sa.Text),
        sa.Column("is_builtin", sa.Boolean, server_default="false"),
        sa.Column("status", sa.Text, server_default="active"),
        sa.Column("created_by", sa.BigInteger, sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_lpt_tenant", "landing_page_templates", ["tenant_id"])
    op.execute("ALTER TABLE landing_page_templates ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE landing_page_templates FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY lpt_tenant ON landing_page_templates "
               "USING (tenant_id = NULLIF(current_setting('app.tenant_id'::text, true), '')::bigint) "
               "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id'::text, true), '')::bigint)")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON landing_page_templates TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON landing_page_templates TO toveads_super;")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO toveads_super;")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS lpt_tenant ON landing_page_templates")
    op.drop_index("ix_lpt_tenant", table_name="landing_page_templates")
    op.drop_table("landing_page_templates")
