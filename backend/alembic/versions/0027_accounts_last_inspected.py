"""accounts 加 last_inspected_at（巡检心跳，区分"无广告"和"真未覆盖"）

Revision ID: 0027
Revises: 0026
"""
from alembic import op
import sqlalchemy as sa

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("last_inspected_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("accounts", "last_inspected_at")
