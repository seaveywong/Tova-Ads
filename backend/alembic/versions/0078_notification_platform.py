"""notifications.platform——告警按平台隔离展示（fb/tt）。

存量行回填 'fb'（历史告警全部来自 FB 链路或平台级事件）；
emit_notification 加 platform 参数默认 fb（零破坏）。

Revision ID: 0078
Revises: 0077
"""
from alembic import op
import sqlalchemy as sa

revision = "0078"
down_revision = "0077"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("platform", sa.Text(), server_default="fb", nullable=False))


def downgrade() -> None:
    op.drop_column("notifications", "platform")
