"""assets 表 v2 加列（name/tags/public_url/尺寸/时长/usage_count）

Revision ID: 0046
Revises: 0045
Create Date: 2026-07-26
"""
from alembic import op
import sqlalchemy as sa

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("assets", sa.Column("name", sa.Text()))
    op.add_column("assets", sa.Column("tags", sa.Text()))
    op.add_column("assets", sa.Column("public_url", sa.Text()))
    op.add_column("assets", sa.Column("file_size", sa.BigInteger(), server_default="0"))
    op.add_column("assets", sa.Column("mime_type", sa.Text()))
    op.add_column("assets", sa.Column("width", sa.Integer(), server_default="0"))
    op.add_column("assets", sa.Column("height", sa.Integer(), server_default="0"))
    op.add_column("assets", sa.Column("duration_sec", sa.Integer(), server_default="0"))
    op.add_column("assets", sa.Column("usage_count", sa.Integer(), server_default="0"))
    # 把现有行的 name 默认填 filename（避免空名）
    op.execute("UPDATE assets SET name = filename WHERE name IS NULL AND filename IS NOT NULL")
    op.execute("UPDATE assets SET name = storage_key WHERE name IS NULL")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_super;")


def downgrade():
    for col in ("usage_count", "duration_sec", "height", "width", "mime_type", "file_size", "public_url", "tags", "name"):
        op.drop_column("assets", col)
