"""0090: message_templates.type 消息模板类型（messenger / whatsapp）

表单模板页 1:1 FB 编辑器批：消息模板支持两种类型——messenger（FB Messenger 欢迎语，
投放链已接）与 whatsapp（WhatsApp 开场白，供 Instant Form 感谢页按钮等场景引用）。
存量行回落 'messenger'（原语义）。
"""
from alembic import op
import sqlalchemy as sa

revision = "0090"
down_revision = "0089"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("message_templates", sa.Column("type", sa.Text(), server_default="messenger"))
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON message_templates TO toveads_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON message_templates TO toveads_super")


def downgrade() -> None:
    op.drop_column("message_templates", "type")
