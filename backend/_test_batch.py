"""v25 ?ids= 批量调用变体测试。"""
import httpx
from app.core.database import SuperSessionLocal
from app.core.encryption import decrypt
from app.core.fb_client import FbClient, GRAPH_BASE
from app.models.fb import FbCredential

db = SuperSessionLocal()
cred = db.query(FbCredential).order_by(FbCredential.id.desc()).first()
fb = FbClient(decrypt(cred.access_token_enc))
accts = fb.get_paged("me/adaccounts", {"fields": "account_id,amount_spent", "limit": 30})
act = next((a["account_id"] for a in accts if float(a.get("amount_spent", 0) or 0) > 0), None)
camps = fb.get_paged(f"act_{act}/campaigns", {"fields": "id", "limit": 5})
ids = ",".join(c["id"] for c in camps)
print(f"ids={ids[:60]}…")

for name, url, params in [
    ("GET /?ids=（现用）", f"{GRAPH_BASE}/", {"ids": ids, "fields": "id,objective"}),
    ("GET /（无路径）root", f"{GRAPH_BASE}", {"ids": ids, "fields": "id,objective"}),
    ("POST /ids=batch（v25 推荐）", f"{GRAPH_BASE}/", None),
]:
    try:
        if name.startswith("POST"):
            r = httpx.post(f"{GRAPH_BASE}/", params={"ids": ids}, json={"fields": "id,objective,optimization_goal", "access_token": decrypt(cred.access_token_enc)}, timeout=30)
        else:
            r = httpx.get(url, params={**params, "access_token": decrypt(cred.access_token_enc)}, timeout=30)
        b = r.json()
        err = b.get("error", {})
        print(f"  {name:26} → HTTP {r.status_code} {'OK ' + str(len(b)) + ' 条' if not err else 'ERR ' + str(err.get('message'))[:90]}")
    except Exception as e:
        print(f"  {name:26} → {str(e)[:80]}")
db.close()
