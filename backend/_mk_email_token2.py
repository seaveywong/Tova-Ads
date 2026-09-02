"""v5：删掉无明文的孤儿 token → 重建 → 完整 dump 响应结构找明文。"""
import json
import urllib.request
import urllib.error
from sqlalchemy import text
from app.core.database import SuperSessionLocal

ACCOUNT = "fb73c8b129b67f0e48d4bc80d6dd41fa"
BASE = "https://api.cloudflare.com/client/v4"
GROUPS = {
    "addr": "e4589eb09e63436686cd64252a3aebeb",
    "rules": "79b3ec0d10ce4148a8f8bdc0cc5f97f2",
    "dns": "4755a26eedb94da69e1066d98aa820be",
}

db = SuperSessionLocal()
boot = (db.execute(text("SELECT value FROM system_settings WHERE key='cf_email_token'")).fetchone() or [""])[0].strip().strip('"').strip("'")
ZONE = (db.execute(text("SELECT value FROM system_settings WHERE key='cf_zone_id_tovaads.com'")).fetchone() or [""])[0].strip().strip('"').strip("'")
db.close()
print("zone:", ZONE)


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


def mask(v):
    v = str(v)
    return v if len(v) < 12 else f"{v[:6]}…{v[-4:]}(len{len(v)})"


# 删所有同名（含上轮孤儿）
s, b = req(boot, "GET", "user/tokens")
for t in (b.get("result") or []):
    if t.get("name") == "tovaads-email-routing":
        print("删除:", t["id"], t.get("status"))
        req(boot, "DELETE", f"user/tokens/{t['id']}")

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
print("HTTP", s, "success:", b.get("success") if isinstance(b, dict) else b)


def walk(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            walk(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            walk(v, f"{path}[{i}]")
    else:
        sval = str(obj)
        if len(sval) >= 20:  # 只显示像密钥的长字段
            print(f"  {path} = {mask(sval)}")


walk(b, "$")

# 猜常见键位
cand = ""
for key in ("token", "value", "secret"):
    v = (b.get("result") or {}).get(key) if isinstance(b, dict) else None
    if v and len(str(v)) >= 30:
        cand = str(v)
        print(f"明文在 result.{key}")
        break
if not cand:
    raise SystemExit("仍未定位明文（看上面 dump 判断）")

db = SuperSessionLocal()
db.execute(text("UPDATE system_settings SET value=:v WHERE key='cf_email_token'"), {"v": cand})
db.commit()
db.close()
print("已写入系统设置 ✓")

for lbl, p in [("verify", "user/tokens/verify"),
               ("Email Routing 状态", f"zones/{ZONE}/email/routing"),
               ("目的地邮箱列表", f"zones/{ZONE}/email/routing/addresses"),
               ("规则列表", f"zones/{ZONE}/email/routing/rules"),
               ("DNS 读取", f"zones/{ZONE}/dns_records?per_page=1")]:
    s2, b2 = req(cand, "GET", p)
    ok = isinstance(b2, dict) and b2.get("success")
    n = f" {len(b2.get('result') or [])} 条" if ok and isinstance(b2.get("result"), list) else ""
    err = "" if ok else " | " + json.dumps(b2.get("errors") if isinstance(b2, dict) else b2, ensure_ascii=False)[:140]
    print(f"{lbl}: {'✅' if ok else '❌'} HTTP {s2}{n}{err}")
print("新 token:", mask(cand))
