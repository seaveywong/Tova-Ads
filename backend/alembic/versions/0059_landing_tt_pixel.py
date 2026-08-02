"""落地页加 TK 像素(tt_pixel_ids) + 像素库加 platform(fb/tt)

Revision ID: 0059
Revises: 0058
Create Date: 2026-08-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0059"
down_revision = "0058"


def upgrade():
    op.add_column("landing_pages", sa.Column("tt_pixel_ids", sa.Text()))
    op.add_column("landing_pixels", sa.Column("platform", sa.Text(), server_default="fb"))
    # GRANT（参照 0055-0057，铁律）
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON landing_pages, landing_pixels TO toveads_app")
    op.execute("GRANT SELECT ON landing_pages, landing_pixels TO toveads_super")


def downgrade():
    op.drop_column("landing_pages", "tt_pixel_ids")
    op.drop_column("landing_pixels", "platform")
