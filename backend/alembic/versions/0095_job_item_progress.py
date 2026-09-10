"""0095 批BQ 部署进度透明化：launch_job_items 加 progress（实时进度注记）

背景：部署中 item 只有「creating」转圈——视频上传/12 广告序列跑几分钟，用户看到的是
黑盒「卡住」。runner 现在逐步写 progress（"广告 3/12：US4"），进度弹窗实时显示 +
「最后更新 X 秒前」+ 超过 2 分钟无进展橙显「进程可能已中断」。
终态由 _apply_batch_result 写"完成：成功 X/Y"。表级 GRANT 已覆盖新列，按惯例仍补齐。
"""
from alembic import op
import sqlalchemy as sa

revision = "0095"
down_revision = "0094"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("launch_job_items", sa.Column("progress", sa.Text(), nullable=True))
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON launch_job_items TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON launch_job_items TO toveads_super;")


def downgrade() -> None:
    op.drop_column("launch_job_items", "progress")
