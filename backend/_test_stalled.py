"""sync_stalled 告警实测：触发一次→验证入库+TG路由→再触发验证 24h dedup 不重复。"""
from sqlalchemy import text
from app.core.database import SuperSessionLocal
from app.services.ads_cache_sync import run_ads_cache_sync

r1 = run_ads_cache_sync()
print(f"第1次触发: {r1}")
db = SuperSessionLocal()
rows = db.execute(text("SELECT id, tenant_id, level, event_type, title, platform FROM notifications "
                       "WHERE event_type = 'sync_stalled' ORDER BY id DESC LIMIT 3")).fetchall()
for x in rows:
    print(f"  通知#{x[0]} tenant={x[1]} {x[2]} {x[4]} [{x[5]}]")
db.close()

r2 = run_ads_cache_sync()
db = SuperSessionLocal()
n = db.execute(text("SELECT count(*) FROM notifications WHERE event_type = 'sync_stalled'")).scalar()
db.close()
print(f"第2次触发: {r2} → 总通知数 {n}（应为第1次的数量，24h dedup 生效）")
