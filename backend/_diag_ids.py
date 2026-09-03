"""①ids 批量调用 v25 实测 ②AI 纠偏 max_tokens=800 复测。"""
import json
from app.core.database import SuperSessionLocal
from app.core.encryption import decrypt
from app.core.fb_client import FbClient
from app.models.fb import FbCredential

db = SuperSessionLocal()
cred = db.query(FbCredential).order_by(FbCredential.id.desc()).first()
fb = FbClient(decrypt(cred.access_token_enc))
accts = fb.get_paged("me/adaccounts", {"fields": "account_id,amount_spent", "limit": 30})
act = next((a["account_id"] for a in accts if float(a.get("amount_spent", 0) or 0) > 0), None)

# 拿该账户的 campaigns（结构接口）
camps = fb.get_paged(f"act_{act}/campaigns", {"fields": "id,objective,optimization_goal", "limit": 10})
print(f"账户 act_{act}: {len(camps)} campaigns（结构接口 OK）")
if camps:
    ids = ",".join(c["id"] for c in camps[:5])
    print(f"  样例 objective: {camps[0].get('objective')} / og: {camps[0].get('optimization_goal')}")
    # ids 批量调用（照抄 _campaign_objectives）
    try:
        data = fb.get("", {"ids": ids, "fields": "id,objective,optimization_goal"})
        n = sum(1 for cid, c in (data or {}).items() if isinstance(c, dict) and c.get("objective"))
        print(f"  ?ids= 批量: 返回 {len(data or {})} 条, 有 objective 的 {n} 条 → {'✅ 正常' if n else '❌ 全空'}")
        if data:
            k0 = next(iter(data))
            print(f"    样例: {json.dumps(data[k0], ensure_ascii=False)[:120]}")
    except Exception as e:
        print(f"  ?ids= 批量: ❌ {str(e)[:120]}")

# AI 纠偏 max_tokens 复测
from app.core.ai_client import text_client
c = text_client()
try:
    r = c.chat_json([{"role": "user", "content": '从这些 actions 里选核心转化字段，只返回 JSON {"field":"...","reason":"..."}：offsite_conversion.fb_pixel_purchase: 5, link_click: 300'}],
                    temperature=0.1, max_tokens=800)
    print(f"  AI纠偏 max_tokens=800: ✅ {json.dumps(r, ensure_ascii=False)[:100]}")
except Exception as e:
    print(f"  AI纠偏 max_tokens=800: ❌ {str(e)[:100]}")
db.close()
