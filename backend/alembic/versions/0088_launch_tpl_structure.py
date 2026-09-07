"""0088: launch_templates 加 structure（1:1 FB 三层结构 JSON）

结构模式（2026-09-08 用户决策）：模板 = 1 系列含 N 广告组、每组 M 广告节点（素材组节点
部署时每素材展开一个广告），组/广告级字段覆盖模板默认；空 = 平铺模式（现有部署链路零改动）。
JSON 而非三张子表：节点不需要 SQL 级查询，行级 RLS 已覆盖（audience_json/advanced_config 先例）。
"""
from alembic import op
import sqlalchemy as sa

revision = "0088"
down_revision = "0087"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("launch_templates", sa.Column("structure", sa.Text()))
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON launch_templates TO toveads_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON launch_templates TO toveads_super")


def downgrade() -> None:
    op.drop_column("launch_templates", "structure")
