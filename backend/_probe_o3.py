"""O3 系列账户状态 + 限流告警的 affected 列表来源核查。"""
from app.core.database import SuperSessionLocal
from sqlalchemy import text

db = SuperSessionLocal()
print("== BSCH-TD-O3xx 账户状态 ==")
rows = db.execute(text("""
    SELECT a.name, a.act_id, a.account_status, a.disable_reason,
           a.is_managed, a.last_inspected_at, c.alias
    FROM accounts a LEFT JOIN fb_credentials c ON c.id = a.fb_credential_id
    WHERE a.name LIKE 'BSCH-TD-O3%'
    ORDER BY a.name LIMIT 20""")).fetchall()
for r in rows:
    print(dict(r._mapping))

print("\n== 各令牌名下绑定账户数（含禁用/未纳管——token_rate_limited affected 列表现状）==")
rows2 = db.execute(text("""
    SELECT c.alias, count(a.id) AS bound_total,
           sum(CASE WHEN a.is_managed THEN 1 ELSE 0 END) AS managed,
           sum(CASE WHEN a.account_status IN (2,8,100,101) THEN 1 ELSE 0 END) AS dead_status
    FROM fb_credentials c LEFT JOIN accounts a ON a.fb_credential_id = c.id
    WHERE c.status = 'active'
    GROUP BY c.alias ORDER BY bound_total DESC""")).fetchall()
for r in rows2:
    print(dict(r._mapping))
db.close()
