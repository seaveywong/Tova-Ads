"""0087: fb_credentials 加 max_accounts（令牌级账户绑定上限）

operate 型令牌默认 100（防一个操作号带几千账户导入炸巡检/同步——用户决策 2026-09-08）；
manage 型默认不限（NULL）。令牌抽屉可改。导入时逐账户检查覆盖令牌的现有绑定数，
超额令牌不再接收新绑定（账户计入 skipped_over_limit，可换令牌覆盖或调上限后重导）。
"""
from alembic import op
import sqlalchemy as sa

revision = "0087"
down_revision = "0086"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fb_credentials", sa.Column("max_accounts", sa.BigInteger()))
    # operate 型默认 100；manage/user 型不限
    op.execute("UPDATE fb_credentials SET max_accounts = 100 WHERE token_type = 'operate'")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON fb_credentials TO toveads_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON fb_credentials TO toveads_super")


def downgrade() -> None:
    op.drop_column("fb_credentials", "max_accounts")
