"""0096 批BZ 部署进度展示令牌：launch_job_items 加 cred_name（本次部署用谁的令牌下发）

用户点名的可观测性：成功失败都知道是谁的令牌（0911 Radar 事故——兜底选中无权令牌
报误导性 #33，若进度里直接看到「Kritins Rae」一眼定位）。表级 GRANT 已覆盖新列。
"""
from alembic import op
import sqlalchemy as sa

revision = "0096"
down_revision = "0095"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("launch_job_items", sa.Column("cred_name", sa.Text(), nullable=True))
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON launch_job_items TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON launch_job_items TO toveads_super;")


def downgrade() -> None:
    op.drop_column("launch_job_items", "cred_name")
