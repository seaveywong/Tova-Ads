"""user_tg_bindings 加 prefs 列：用户 TG 通知偏好（FBInsider ④通知白名单矩阵）。

JSON 字符串 {"levels": {"warning": true, "info": true}}；NULL=未设置=全推
（fail-open，存量行零迁移负担）。critical 恒推由发送层代码强制，不落 prefs。

Revision ID: 0085
Revises: 0084
"""
from alembic import op

revision = "0085"
down_revision = "0084"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE user_tg_bindings ADD COLUMN IF NOT EXISTS prefs TEXT")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON user_tg_bindings TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON user_tg_bindings TO toveads_super;")


def downgrade() -> None:
    op.execute("ALTER TABLE user_tg_bindings DROP COLUMN IF EXISTS prefs")
