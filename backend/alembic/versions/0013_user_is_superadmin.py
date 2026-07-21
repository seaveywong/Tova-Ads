"""users.is_superadmin（平台超管标志；域名分配等平台级操作用）

Revision ID: 0013
Revises: 0012
"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("is_superadmin", sa.Boolean, server_default="false", nullable=False))


def downgrade() -> None:
    op.drop_column("users", "is_superadmin")
