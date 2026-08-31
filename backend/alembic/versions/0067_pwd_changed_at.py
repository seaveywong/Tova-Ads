"""users.pwd_changed_at——改密/改邮箱后旧 JWT 失效机制的比对基准。

Revision ID: 0067
Revises: 0066
"""
from alembic import op
import sqlalchemy as sa

revision = "0067"
down_revision = "0066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("pwd_changed_at", sa.DateTime(timezone=True)))
    # 回填为当前时间——存量 JWT 的 iat 都早于它？不：回填会让所有在线用户立即全掉线。
    # 回填为 NULL：deps 里 NULL 视为"从未改密"，不失效任何存量 token（平滑上线）。
    op.execute("GRANT SELECT, UPDATE ON users TO toveads_app")
    op.execute("GRANT SELECT, UPDATE, INSERT, DELETE ON users TO toveads_super")


def downgrade() -> None:
    op.drop_column("users", "pwd_changed_at")
