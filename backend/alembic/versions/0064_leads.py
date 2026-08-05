"""leads 表（FB 潜客数据存储，leads_retrieval + webhook 回调写入）

Revision ID: 0064
Revises: 0063
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0064"
down_revision = "0063"


def upgrade():
    op.create_table(
        "leads",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("page_id", sa.Text),
        sa.Column("ad_id", sa.Text),
        sa.Column("form_id", sa.Text),
        sa.Column("lead_id", sa.Text, unique=True),
        sa.Column("field_data_json", sa.Text),
        sa.Column("created_time", sa.DateTime(timezone=True)),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_leads_tenant", "leads", ["tenant_id"])
    op.create_index("idx_leads_form", "leads", ["form_id"])
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_super")


def downgrade():
    op.drop_table("leads")
