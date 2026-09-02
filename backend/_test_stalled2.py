"""修复后验证：删重复测试通知 → 连跑 2 次 → 第 2 次必须不再发（dedup 真生效）。"""
from sqlalchemy import text
from app.core.database import SuperSessionLocal
from app.services.ads_cache_sync import run_ads_cache_sync

db = SuperSessionLocal()
db.execute(text("DELETE FROM notifications WHERE event_type = 'sync_stalled'"))
db.execute(text("DELETE FROM action_logs WHERE action_type = 'sync_stalled'"))
db.commit()
db.close()
print("已清测试数据")

run_ads_cache_sync()
db = SuperSessionLocal()
n1 = db.execute(text("SELECT count(*) FROM notifications WHERE event_type = 'sync_stalled'")).scalar()
db.close()
print(f"第1次触发后通知数: {n1}（预期 1，真实状态触发合法告警）")

run_ads_cache_sync()
db = SuperSessionLocal()
n2 = db.execute(text("SELECT count(*) FROM notifications WHERE event_type = 'sync_stalled'")).scalar()
logs = db.execute(text("SELECT count(*) FROM action_logs WHERE action_type = 'sync_stalled'")).scalar()
db.close()
print(f"第2次触发后通知数: {n2}（必须 = {n1}，dedup 生效）")
print(f"action_logs 记录: {logs}")
print("✅ dedup 验证通过" if n2 == n1 and logs >= 1 else "❌ dedup 仍失效！")
