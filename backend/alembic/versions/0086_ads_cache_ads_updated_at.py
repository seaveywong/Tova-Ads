"""0086: ads_cache 加 ads_updated_at（广告层独立时间戳）

单 updated_at 盖两层导致误导（2026-09-08 生产）：巡检独家回写广告层后，15min sync 只刷
campaigns/adsets 也刷新 updated_at——令牌切换间隙广告数据陈旧但「缓存不到 1 分钟」。
ads_updated_at 只在广告层写入（巡检回写/手动全量刷新）时刷新；/ads/list 的「数据更新至」
改按它取。回填=updated_at 现值。
"""
from alembic import op
import sqlalchemy as sa

revision = "0086"
down_revision = "0085"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ads_cache", sa.Column("ads_updated_at", sa.DateTime(timezone=True)))
    op.execute("UPDATE ads_cache SET ads_updated_at = updated_at WHERE updated_at IS NOT NULL")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ads_cache TO toveads_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ads_cache TO toveads_super")


def downgrade() -> None:
    op.drop_column("ads_cache", "ads_updated_at")
