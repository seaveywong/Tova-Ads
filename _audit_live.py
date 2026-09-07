# 真机跑通后的针对性复审：巡检盯上没/看板数据/对账/止损覆盖
import json
from datetime import datetime, timezone
from sqlalchemy import text
from app.core.database import SuperSessionLocal

ACT = "1338258757886709"
db = SuperSessionLocal()

print("== ① 巡检是否盯上 Roly-V21 ==")
r = db.execute(text("""
    SELECT snapshot_date, spend, conversions, updated_at FROM perf_snapshots
    WHERE act_id = :a ORDER BY updated_at DESC LIMIT 3
"""), {"a": ACT}).all()
for x in r:
    print(f"  snapshot date={x[0]} spend={x[1]} conv={x[2]} at={x[3]}")
if not r:
    print("  !! 无快照——巡检未覆盖或无活跃广告")

print("\n== ② last_inspected_at ==")
r = db.execute(text("SELECT name, last_inspected_at, account_status FROM accounts WHERE act_id = :a"), {"a": ACT}).one()
print(f"  {r[0]} last_inspected={r[1]} status={r[2]}")

print("\n== ③ ads_cache 对账（部署后刷新没） ==")
try:
    row = db.execute(text("""
        SELECT updated_at, ads_json FROM ads_cache WHERE act_id = :a
    """), {"a": ACT}).one()
    import json as _j
    ads = _j.loads(row[1] or "[]")
    print(f"  cache updated={row[0]} ads={len(ads)}")
    for a in ads[:3]:
        print(f"    ad {a.get('id')} status={a.get('status')}/{a.get('effective_status')}")
except Exception as e:
    print("  cache 无行:", str(e)[:60])

print("\n== ④ 最新心跳 ==")
r = db.execute(text("""
    SELECT created_at, trigger_detail FROM action_logs
    WHERE action_type = 'inspection_heartbeat' ORDER BY id DESC LIMIT 1
""")).one()
print(f"  {r[0]} | {r[1][:100]}")

print("\n== ⑤ 止损规则覆盖（tenant 1） ==")
r = db.execute(text("""
    SELECT rule_type, enabled, action FROM guard_rules WHERE tenant_id = 1
""")).all()
for x in r:
    print(f"  {x[0]} enabled={x[1]} action={x[2]}")
if not r:
    print("  (无显式规则——引擎默认注入 bleed_abs $20 止损线)")

print("\n== ⑥ 部署对账日志 ==")
r = db.execute(text("""
    SELECT action_type, result, trigger_detail, created_at FROM action_logs
    WHERE action_type IN ('deploy', 'refresh_cache') AND trigger_detail LIKE '%1338258757886709%'
    ORDER BY id DESC LIMIT 3
""")).all()
for x in r:
    print(f"  {x[0]} {x[1]} {str(x[2])[:80]} {x[3]}")
db.close()
