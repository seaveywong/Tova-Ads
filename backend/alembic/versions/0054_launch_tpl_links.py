"""launch_templates 加落地页/表单模板/消息模板外键（编辑器选中态持久化）

- landing_page_id：选中的落地页（编辑器据此过滤子码下拉；部署仍用 landing_url + subcode_slug）
- lead_form_template_id：选中的 Instant Form 模板（部署时解析：有 fb_form_id 直接用，否则按 config 建到目标 page）
- message_template_id：选中的 Messenger 消息模板（仅回显用；内容已在 message_template 字段）

Revision ID: 0054
Revises: 0053
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("launch_templates", sa.Column("landing_page_id", sa.BigInteger()))
    op.add_column("launch_templates", sa.Column("lead_form_template_id", sa.Integer()))
    op.add_column("launch_templates", sa.Column("message_template_id", sa.Integer()))
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_super;")


def downgrade():
    op.drop_column("launch_templates", "message_template_id")
    op.drop_column("launch_templates", "lead_form_template_id")
    op.drop_column("launch_templates", "landing_page_id")
