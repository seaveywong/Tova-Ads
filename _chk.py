import app.main
from app.core.database import SuperSessionLocal
from sqlalchemy import text
db = SuperSessionLocal()
# 各归属人的账户 + 是否有广告数据
rows = db.execute(text("""
    SELECT u.email AS owner, a.act_id, a.name,
           (SELECT count(*) FROM json_array_elements(c.ads_json::json)) AS ad_count
    FROM accounts a
    LEFT JOIN users u ON u.id = a.owner_user_id
    LEFT JOIN ads_cache c ON c.act_id = a.act_id AND c.tenant_id = a.tenant_id
    WHERE a.tenant_id = 1 AND a.is_managed = true
    ORDER BY u.email, a.act_id
""")).fetchall()
from collections import defaultdict
by_owner = defaultdict(lambda: {"accounts": 0, "ads": 0, "names": []})
for r in rows:
    by_owner[r[0] or "无归属"]["accounts"] += 1
    by_owner[r[0] or "无归属"]["ads"] += int(r[3] or 0)
    if len(by_owner[r[0] or "无归属"]["names"]) < 3:
        by_owner[r[0] or "无归属"]["names"].append(r[2][:16])
for owner, d in sorted(by_owner.items()):
    print(f"{owner:26} 账户={d['accounts']:2} 广告数={d['ads']:3}  样本: {', '.join(d['names'])}")
db.close()
