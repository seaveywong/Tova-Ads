"""accounts 加两列：group_label（用户自定义分组标签）+ disable_reason（FB 官方禁用原因枚举）。

对标 FBInsider ③账户分组（纯标签、非外键非枚举——分组本质就是标签，保持轻）
与 ⑤禁用原因副行（account_sync 每 30min 从 /me/adaccounts 落库，前端状态徽标
下方副行展示）。两列均可空，存量行为 NULL，无需回填。

Revision ID: 0084
Revises: 0083
"""
from alembic import op
import sqlalchemy as sa

revision = "0084"
down_revision = "0083"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("group_label", sa.Text(), nullable=True))
    op.add_column("accounts", sa.Column("disable_reason", sa.Integer(), nullable=True))
    # 新增列继承表级权限，此处按迁移规范重申双角色 GRANT（幂等，已有时为空操作）
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON accounts TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON accounts TO toveads_super;")


def downgrade() -> None:
    op.drop_column("accounts", "disable_reason")
    op.drop_column("accounts", "group_label")
