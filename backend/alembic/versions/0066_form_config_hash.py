"""lead_form_templates 加 config_hash 列（config 变更检测：变了不复用旧 FB 表单）

Revision ID: 0066
Revises: 0065
Create Date: 2026-08-17
"""
from alembic import op
import sqlalchemy as sa

revision = "0066"
down_revision = "0065"


def upgrade():
    op.add_column("lead_form_templates", sa.Column("config_hash", sa.Text))
    # 存量行回填：按现 config 算哈希（下次部署同 config 即可复用现有 fb_form_id）
    from alembic import op as _op
    _op.execute("""
        UPDATE lead_form_templates
        SET config_hash = left(md5(coalesce(config_json, '')), 16)
    """)
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_super")


def downgrade():
    op.drop_column("lead_form_templates", "config_hash")
