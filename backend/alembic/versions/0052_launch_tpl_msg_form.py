"""launch_templates 加 message_template + lead_form_id

Revision ID: 0052
Revises: 0051
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("launch_templates", sa.Column("message_template", sa.Text()))
    op.add_column("launch_templates", sa.Column("lead_form_id", sa.Text()))
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_super;")


def downgrade():
    op.drop_column("launch_templates", "lead_form_id")
    op.drop_column("launch_templates", "message_template")
