"""users 加 locale 字段（'zh'/'en'，默认 zh）

- 用户界面语言偏好。前端切换语言时存到这里。
- 后端异步通知（站内信/TG）按租户 owner 的 locale 渲染。
- 全局异常处理器对 en-locale 请求把中文报错 detail 译成英文。

Revision ID: 0056
Revises: 0055
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("locale", sa.Text(), nullable=False, server_default="zh"))
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_super;")


def downgrade():
    op.drop_column("users", "locale")
