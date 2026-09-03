"""删 user_tg_bindings 旧唯一约束 uq_user_tg_tenant_user (tenant_id,user_id)——与 0082 多 TG 语义冲突。

0082 加了 (tenant,user,chat_id) 唯一索引但漏删旧约束，第二条绑定 INSERT 仍撞旧键。

Revision ID: 0083
Revises: 0082
"""
from alembic import op

revision = "0083"
down_revision = "0082"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE user_tg_bindings DROP CONSTRAINT IF EXISTS uq_user_tg_tenant_user")
    op.execute("DROP INDEX IF EXISTS uq_user_tg_tenant_user")


def downgrade() -> None:
    op.execute("CREATE UNIQUE INDEX uq_user_tg_tenant_user ON user_tg_bindings (tenant_id, user_id)")
