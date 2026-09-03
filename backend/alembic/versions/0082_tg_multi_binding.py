"""user_tg_bindings 支持一人多 TG：唯一索引改为 (tenant_id, user_id, chat_id)。

原单行行为是应用层 .first()+update 造成（DB 无唯一约束）；改为多行追加语义后，
用 (tenant, user, chat_id) 唯一索引防重复绑定同一 chat。存量数据每用户至多 1 行，
建唯一索引无冲突。

Revision ID: 0082
Revises: 0081
"""
from alembic import op

revision = "0082"
down_revision = "0081"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_index("uq_user_tg_chat", "user_tg_bindings",
                            ["tenant_id", "user_id", "chat_id"])
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON user_tg_bindings TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON user_tg_bindings TO toveads_super;")


def downgrade() -> None:
    op.drop_index("uq_user_tg_chat", table_name="user_tg_bindings")
