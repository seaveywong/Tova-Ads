"""assets.fb_video_ids——视频素材部署的每账户 video_id 缓存（与 fb_image_hashes 同构）。

FB 视频上传到 act_{id}/advideos 后的 video_id 按账户隔离，不能跨账户复用，
所以按 {act_id: video_id} 缓存在素材行上，首次部署某账户时上传并写回。

Revision ID: 0068
Revises: 0067
"""
from alembic import op
import sqlalchemy as sa

revision = "0068"
down_revision = "0067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("fb_video_ids", sa.Text()))
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON assets TO toveads_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON assets TO toveads_super")


def downgrade() -> None:
    op.drop_column("assets", "fb_video_ids")
