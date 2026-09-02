"""列出帐户现有 tokens 的 policy 资源格式（学正确写法用）。"""
import json
import urllib.request
import urllib.error
from sqlalchemy import text
from app.core.database import SuperSessionLocal

BASE = "https://api.cloudflare.com/client/v4"

db = SuperSessionLocal()
row = db.execute(text("SELECT value FROM system_settings WHERE key='cf_email_token'")).fetchone()
db.close()
tok = (row[0] if row else "").strip().strip('"').strip("'")


def req(method, path):
    r = urllib.request.Request(f"{BASE}/{path}", method=method,
                               headers={"Authorization": f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


s, b = req("GET", "user/tokens")
for t in (b.get("result") or []):
    s2, d = req("GET", f"user/tokens/{t['id']}")
    pols = (d.get("result") or {}).get("policies") or []
    print(f"- {t.get('name')} (status={t.get('status')})")
    for p in pols:
        groups = ",".join(g.get("name", "?") for g in (p.get("permission_groups") or []))
        for rk, rv in (p.get("resources") or {}).items():
            print(f"    资源: {rk} = {rv}  | 组: {groups}")
