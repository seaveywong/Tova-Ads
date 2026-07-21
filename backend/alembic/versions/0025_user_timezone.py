"""users 加 timezone（用户显示时区，仅前端展示用，不影响广告账户本地时区）

Revision ID: 0025
Revises: 0024

用户在设置里选自己的系统显示时区，前端按它转换所有时间（止损明细/通知/告警）。
广告账户的本地时区（FB insights/snapshot_date）不受影响——那套按账户 timezone 走。
"""
from alembic import op
import sqlalchemy as sa

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("timezone", sa.Text(), nullable=False, server_default="Asia/Shanghai"))


def downgrade() -> None:
    op.drop_column("users", "timezone")
