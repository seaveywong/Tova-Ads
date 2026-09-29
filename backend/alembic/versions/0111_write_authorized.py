"""0111: 账户投放授权标记（导入即区分「BM 可读」vs「正式分配」，2026-09-29）

背景：Deedunsd30x 批实证——点查 GET act_x 通过（BM 间接可读）→ 导入成功，
但保活/部署写操作全被拒（2490585 无广告账户写入权限）。/me/adaccounts 列表
=「直接分配」的权威面（在列=可投放；不在=仅 BM 可读）。导入时比对列表，
本列持久化判定结果；后续写操作遇 2490585 自动反标 False。
"""
from alembic import op
import sqlalchemy as sa

revision = "0111"
down_revision = "0110"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("write_authorized", sa.Boolean(), nullable=True))
    # 存量账户：出现在任一令牌授权列表的置 True（一次性回填由应用层自愈/导入路径补，迁移不调 FB）
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON accounts TO toveads_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON accounts TO toveads_super")


def downgrade() -> None:
    op.drop_column("accounts", "write_authorized")
