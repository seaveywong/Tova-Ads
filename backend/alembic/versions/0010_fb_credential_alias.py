"""fb_credentials 加 alias 列（支持多 token 命名：1111/2222 等，token fallback 基础）

Revision ID: 0010
Revises: 0009
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fb_credentials", sa.Column("alias", sa.Text))
    op.create_index("ix_fb_creds_tenant_active", "fb_credentials", ["tenant_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_fb_creds_tenant_active", table_name="fb_credentials")
    op.drop_column("fb_credentials", "alias")
