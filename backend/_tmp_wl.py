# -*- coding: utf-8 -*-
from app.core.database import SuperSessionLocal
from sqlalchemy import text
s = SuperSessionLocal()
print("== 加白(allowance) 近2日 ==")
r = s.execute(text("select act_id, ad_id, allowance_date, platform, status from guard_ad_allowances where allowance_date >= '2026-09-03' order by allowance_date, act_id")).fetchall()
if not r: print("  (无)")
for x in r: print(" ", x)
print("== 账户币种 ==")
print(" ", s.execute(text("select currency from accounts where act_id='1816188396040295'")).fetchall())
print("== 昨夜01:00-02:30 UTC 的 pause/observe 日志(全租户) ==")
r2 = s.execute(text("""
    select created_at, action_type, result, substr(coalesce(trigger_detail,''),1,120)
    from action_logs
    where created_at between '2026-09-04 00:30:00+00' and '2026-09-04 02:35:00+00'
      and action_type in ('pause','observe_alert')
    order by id desc limit 15
""")).fetchall()
if not r2: print("  (昨夜窗口无任何规则动作)")
for x in r2: print(" ", x)
s.close()
