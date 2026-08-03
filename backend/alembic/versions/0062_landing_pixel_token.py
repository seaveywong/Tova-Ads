"""landing_pixels 加 tt_access_token_enc（TK Events API S2S 鉴权）

Revision ID: 0062
Revises: 0061
Create Date: 2026-08-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0062"
down_revision = "0061"

def upgrade():
    op.add_column("landing_pixels", sa.Column("tt_access_token_enc", sa.Text()))
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_super")

def downgrade():
    op.drop_column("landing_pixels", "tt_access_token_enc")
