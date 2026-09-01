"""action_logs 加 platform 列（TK 一致性批次 C：写路径平台标注）。

TT 写路径（紧急暂停/哨兵/扩量）需要按平台区分审计行；存量与默认 'fb'
（server_default 建列即回填），FB 历史行为与既有查询不变。同 0071/0073：
已有表加列，表级 GRANT 已覆盖新列，不必重授。

Revision ID: 0076
Revises: 0075
"""
import sqlalchemy as sa
from alembic import op

revision = "0076"
down_revision = "0075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("action_logs", sa.Column("platform", sa.Text(), nullable=False, server_default="fb"))


def downgrade() -> None:
    op.drop_column("action_logs", "platform")
