"""隔离 insights code100：逐字段二分定位非法参数。"""
import httpx
from app.core.database import SuperSessionLocal
from app.core.encryption import decrypt
from app.core.fb_client import FbClient, GRAPH_BASE
from app.models.fb import FbCredential

db = SuperSessionLocal()
cred = db.query(FbCredential).order_by(FbCredential.id.desc()).first()
tok = decrypt(cred.access_token_enc)
fb = FbClient(tok)
accts = fb.get_paged("me/adaccounts", {"fields": "account_id,amount_spent", "limit": 30})
act = next((a["account_id"] for a in accts if float(a.get("amount_spent", 0) or 0) > 0), None)
print(f"测试账户: act_{act}")

CASES = {
    "全字段+date_preset": {"fields": "ad_id,ad_name,campaign_id,campaign_name,adset_id,adset_name,spend,impressions,clicks,ctr,cpc,reach,frequency,actions,purchase_roas,effective_status", "level": "ad", "date_preset": "last_7d"},
    "全字段+time_range":  {"fields": "ad_id,ad_name,campaign_id,campaign_name,adset_id,adset_name,spend,impressions,clicks,ctr,cpc,reach,frequency,actions,purchase_roas,effective_status", "level": "ad", "time_range": '{"since":"2026-08-28","until":"2026-09-03"}'},
    "去effective_status": {"fields": "ad_id,ad_name,campaign_id,campaign_name,adset_id,adset_name,spend,impressions,clicks,ctr,cpc,reach,frequency,actions,purchase_roas", "level": "ad", "date_preset": "last_7d"},
    "最小集+actions":     {"fields": "ad_id,spend,actions", "level": "ad", "date_preset": "last_7d"},
    "最小集today":        {"fields": "ad_id,spend,actions", "level": "ad", "date_preset": "today"},
}
for name, params in CASES.items():
    r = httpx.get(f"{GRAPH_BASE}/act_{act}/insights", params={**params, "access_token": tok, "limit": 10}, timeout=30)
    b = r.json()
    err = b.get("error", {})
    n = len(b.get("data", [])) if "data" in b else "-"
    print(f"  {name:20} → HTTP {r.status_code} {'OK ' + str(n) + ' 行' if not err else 'ERR code=' + str(err.get('code')) + ' ' + str(err.get('message'))[:100]}")
db.close()
