"""v6：把 Addresses 组挪进 zone policy + 加 Zone Read → 重探。PUT 不改密文；若返回新 value 一并更新存储。"""
import json
import urllib.request
import urllib.error
from sqlalchemy import text
from app.core.database import SuperSessionLocal

ACCOUNT = "fb73c8b129b67f0e48d4bc80d6dd41fa"
BASE = "https://api.cloudflare.com/client/v4"

db = SuperSessionLocal()
boot = (db.execute(text("SELECT value FROM system_settings WHERE key='cf_email_token'")).fetchone() or [""])[0].strip().strip('"').strip("'")
cur = (db.execute(text("SELECT value FROM system_settings WHERE key='cf_email_token'")).fetchone() or [""])[0]
db.close()
if boot == cur:
    raise SystemExit("boot==当前token，说明上轮新token没存上，先排查")


def req(tok, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(f"{BASE}/{path}", data=data, method=method,
                               headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode()[:400]
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


# 权限组 id 全量解析
s, b = req(boot, "GET", "user/tokens/permission_groups")
G = {}
for g in (b.get("result") or []):
    n = g.get("name", "")
    if n == "Email Routing Addresses Write":
        G["addr"] = g["id"]
    elif n == "Email Routing Rules Write":
        G["rules"] = g["id"]
    elif n == "DNS Write":
        G["dns"] = g["id"]
    elif n == "Zone Read":
        G["zread"] = g["id"]
print("组:", {k: v[:8] for k, v in G.items()})
assert len(G) == 4, G

# 找 tovaads-email-routing 的 id + zone
db = SuperSessionLocal()
ZONE = (db.execute(text("SELECT value FROM system_settings WHERE key='cf_zone_id_tovaads.com'")).fetchone() or [""])[0].strip().strip('"').strip("'")
db.close()
s, b = req(boot, "GET", "user/tokens")
tid = next(t["id"] for t in (b.get("result") or []) if t.get("name") == "tovaads-email-routing" and t.get("status") == "active")
print("token id:", tid)

body = {
    "name": "tovaads-email-routing",
    "policies": [
        {"effect": "allow",
         "resources": {f"com.cloudflare.api.account.zone.{ZONE}": "*"},
         "permission_groups": [{"id": G[k]} for k in ("rules", "dns", "addr", "zread")]},
        {"effect": "allow",
         "resources": {f"com.cloudflare.api.account.{ACCOUNT}": "*"},
         "permission_groups": [{"id": G["addr"]}]},
    ],
}
s, b = req(boot, "PUT", f"user/tokens/{tid}", body)
print("PUT:", s, b.get("success") if isinstance(b, dict) else b)
if not (isinstance(b, dict) and b.get("success")):
    print(json.dumps(b.get("errors") if isinstance(b, dict) else b, ensure_ascii=False)[:300])
    raise SystemExit(1)
newval = (b.get("result") or {}).get("value") or ""
if newval and newval != cur:
    db = SuperSessionLocal()
    db.execute(text("UPDATE system_settings SET value=:v WHERE key='cf_email_token'"), {"v": newval})
    db.commit(); db.close()
    print("PUT 换了 value，已更新存储")
    cur = newval

for lbl, p in [("Email Routing 状态", f"zones/{ZONE}/email/routing"),
               ("目的地邮箱列表", f"zones/{ZONE}/email/routing/addresses"),
               ("规则列表", f"zones/{ZONE}/email/routing/rules"),
               ("DNS 读取", f"zones/{ZONE}/dns_records?per_page=1")]:
    s2, b2 = req(cur, "GET", p)
    ok = isinstance(b2, dict) and b2.get("success")
    n = f" {len(b2.get('result') or [])} 条" if ok and isinstance(b2.get("result"), list) else ""
    err = "" if ok else " | " + json.dumps(b2.get("errors") if isinstance(b2, dict) else b2, ensure_ascii=False)[:130]
    print(f"{lbl}: {'✅' if ok else '❌'} HTTP {s2}{n}{err}")
