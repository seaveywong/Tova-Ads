"""launch_templates 加 beneficiary + payer（FB dsa_beneficiary/dsa_payor，EU/泰国等强制披露）

Revision ID: 0050
Revises: 0049
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("launch_templates", sa.Column("beneficiary", sa.Text()))
    op.add_column("launch_templates", sa.Column("payer", sa.Text()))
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_super;")


def downgrade():
    op.drop_column("launch_templates", "payer")
    op.drop_column("launch_templates", "beneficiary")
