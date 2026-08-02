"""landing_pages 加 bound_subdomains（追踪所有绑定的子域名，支持多域名管理）

Revision ID: 0061
Revises: 0060
Create Date: 2026-08-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0061"
down_revision = "0060"

def upgrade():
    op.add_column("landing_pages", sa.Column("bound_subdomains", sa.Text()))
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_super")

def downgrade():
    op.drop_column("landing_pages", "bound_subdomains")
