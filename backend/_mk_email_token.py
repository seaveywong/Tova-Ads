"""v4：zone_id 从帐内 tovaads Tunnel token 的 policy 提取（权威），修缓存 → 建 token → 实测。"""
import json
import urllib.request
import urllib.error
from sqlalchemy import text
from app.core.database import SuperSessionLocal

ACCOUNT = "fb73c8b129b67f0e48d4bc80d6dd41fa"
BASE = "https://api.cloudflare.com/client/v4"
GROUPS = {
    "addr": "e4589eb09e63436686cd64252a3aebeb",   # Email Routing Addresses Write (account)
    "rules": "79b3ec0d10ce4148a8f8bdc0cc5f97f2",  # Email Routing Rules Write (zone)
    "dns": "4755a26eedb94da69e1066d98aa820be",    # DNS Write (zone)
}

db = SuperSessionLocal()
boot = (db.execute(text("SELECT value FROM system_settings WHERE key='cf_email_token'")).fetchone() or [""])[0].strip().strip('"').strip("'")
db.close()


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


# 1) 从 tovaads Tunnel token 提取权威 zone_id
s, b = req(boot, "GET", "user/tokens")
ZONE = None
for t in (b.get("result") or []):
    if "tovaads" not in (t.get("name") or "").lower() or t.get("status") != "active":
        continue
    s2, d = req(boot, "GET", f"user/tokens/{t['id']}")
    for p in ((d.get("result") or {}).get("policies") or []):
        for rk in (p.get("resources") or {}):
            if rk.startswith("com.cloudflare.api.account.zone."):
                ZONE = rk.split("com.cloudflare.api.account.zone.", 1)[1]
                break
    if ZONE:
        print(f"zone_id 来源: 「{t.get('name')}」→ {ZONE} (len={len(ZONE)})")
        break
if not ZONE or len(ZONE) != 32:
    raise SystemExit(f"zone_id 提取失败或不合法: {ZONE}")

# 2) 修缓存
db = SuperSessionLocal()
db.execute(text("INSERT INTO system_settings (key, value) VALUES ('cf_zone_id_tovaads.com', :v) "
                "ON CONFLICT (key) DO UPDATE SET value=:v"), {"v": ZONE})
db.commit()
db.close()
print("缓存 cf_zone_id_tovaads.com 已修正 ✓")

# 3) 建 token（幂等）
s, b = req(boot, "GET", "user/tokens")
for t in (b.get("result") or []):
    if t.get("name") == "tovaads-email-routing" and t.get("status") == "active":
        req(boot, "DELETE", f"user/tokens/{t['id']}")
        print("已删旧同名 token", t["id"])

body = {
    "name": "tovaads-email-routing",
    "policies": [
        {"effect": "allow",
         "resources": {f"com.cloudflare.api.account.zone.{ZONE}": "*"},
         "permission_groups": [{"id": GROUPS["rules"]}, {"id": GROUPS["dns"]}]},
        {"effect": "allow",
         "resources": {f"com.cloudflare.api.account.{ACCOUNT}": "*"},
         "permission_groups": [{"id": GROUPS["addr"]}]},
    ],
}
s, b = req(boot, "POST", "user/tokens", body)
if s not in (200, 201) or not (isinstance(b, dict) and b.get("success")):
    print(f"创建失败: HTTP {s} | {json.dumps(b.get('errors') if isinstance(b, dict) else b, ensure_ascii=False)[:400]}")
    raise SystemExit(1)
new_tok = (b.get("result") or {}).get("token") or ""
print("token 创建成功:", (b.get("result") or {}).get("id"))
if not new_tok:
    raise SystemExit("响应无明文")

db = SuperSessionLocal()
db.execute(text("UPDATE system_settings SET value=:v WHERE key='cf_email_token'"), {"v": new_tok})
db.commit()
db.close()
print("已写入系统设置 ✓")

# 4) 实测（用权威 zone_id）
for lbl, p in [("verify", "user/tokens/verify"),
               ("Email Routing 状态", f"zones/{ZONE}/email/routing"),
               ("目的地邮箱列表", f"zones/{ZONE}/email/routing/addresses"),
               ("规则列表", f"zones/{ZONE}/email/routing/rules"),
               ("DNS 读取", f"zones/{ZONE}/dns_records?per_page=1")]:
    s2, b2 = req(new_tok, "GET", p)
    ok = isinstance(b2, dict) and b2.get("success")
    n = f" {len(b2.get('result') or [])} 条" if ok and isinstance(b2.get("result"), list) else ""
    err = "" if ok else " | " + json.dumps(b2.get("errors") if isinstance(b2, dict) else b2, ensure_ascii=False)[:140]
    print(f"{lbl}: {'✅' if ok else '❌'} HTTP {s2}{n}{err}")
print(f"\n新 token(脱敏): {new_tok[:8]}...{new_tok[-4:]}")
