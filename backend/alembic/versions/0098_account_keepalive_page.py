"""accounts 加 keepalive_page_id（手动指定保活主页）

强绑户（1815645 熔断）的指定主页无法从令牌侧推断——允许用户在 UI 里指定，
run_keepalive 优先使用指定主页；指定即解除 burnt（用户已知该用哪个页）。
"""
from alembic import op
import sqlalchemy as sa

revision = "0098"
down_revision = "0097"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("keepalive_page_id", sa.Text(), nullable=True))
    op.execute("GRANT SELECT, UPDATE, INSERT, DELETE ON accounts TO toveads_app")
    op.execute("GRANT SELECT, UPDATE, INSERT, DELETE ON accounts TO toveads_super")


def downgrade() -> None:
    op.drop_column("accounts", "keepalive_page_id")
