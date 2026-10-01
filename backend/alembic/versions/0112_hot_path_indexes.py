"""0112: 落地热路径索引（优化扫描 P2→批1 落地）

背景（2026-10-01 优化扫描实证）：
- landing_events 无 tenant_id 前导索引——dashboard/ads_manager 聚合按
  tenant_id + created_at 范围过滤，现有 (page_id,created_at)/(slug,event_type,created_at)
  全部用不上 → 60 天保留窗的事件表顺序扫描
- dedup/frequency 检查（每次落地点击调用）按 (page_id, ip_hash, event_type, created_at)
  过滤，ip_hash 不在任何索引里

本迁移：
- (tenant_id, created_at) 支撑租户聚合主查询
- (page_id, ip_hash, event_type) 支撑防重/频次检查热路径
"""
from alembic import op

revision = "0112"
down_revision = "0111"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_landing_events_tenant_time "
               "ON landing_events (tenant_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_landing_events_dedup "
               "ON landing_events (page_id, ip_hash, event_type, created_at DESC)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_landing_events_tenant_time")
    op.execute("DROP INDEX IF EXISTS ix_landing_events_dedup")
