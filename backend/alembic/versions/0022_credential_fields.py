"""fb_credentials 加 token_type/token_source/permission_snapshot/consecutive_fails/last_verified_at

Revision ID: 0022
Revises: 0021

令牌管理设计：来源×角色双维度（token_type manage/operate/user + token_source oauth/manual）+ 权限快照 + 连续失败计数 + 检测时间。
"""
from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for col, typ, default in [
        ("token_type", sa.Text, "'user'"),
        ("token_source", sa.Text, "'manual'"),
        ("permission_snapshot", sa.Text, None),
        ("consecutive_fails", sa.Integer, "0"),
        ("last_verified_at", sa.DateTime(timezone=True), None),
    ]:
        try:
            op.add_column("fb_credentials", sa.Column(col, typ, server_default=default))
        except Exception:
            pass


def downgrade() -> None:
    pass
