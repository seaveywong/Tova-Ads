"""assets.tt_file_ids——TikTok 素材部署的每广告主 file_id 缓存（与 fb_image_hashes/fb_video_ids 同构）。

TT 素材必须先上传到目标 advertiser 的文件库拿 file_id（image_id / video_id），
file_id 按 advertiser 隔离不能跨账户复用，按 {advertiser_id: file_id} 缓存在素材行上，
首次部署某账户时上传并写回（_merge_asset_cache 行锁合并，防并发 job 互相覆盖丢条目）。
已有表加列，表级 GRANT 已覆盖新列（同 0072 理由），不必重授。

Revision ID: 0073
Revises: 0072
"""
from alembic import op
import sqlalchemy as sa

revision = "0073"
down_revision = "0072"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("tt_file_ids", sa.Text()))


def downgrade() -> None:
    op.drop_column("assets", "tt_file_ids")
