"""测帐户级路径的 Email Routing 端点（现 token 已有 account 级 Addresses Write）。"""
import json
import urllib.request
import urllib.error
from sqlalchemy import text
from app.core.database import SuperSessionLocal

ACCOUNT = "fb73c8b129b67f0e48d4bc80d6dd41fa"
BASE = "https://api.cloudflare.com/client/v4"

db = SuperSessionLocal()
tok = (db.execute(text("SELECT value FROM system_settings WHERE key='cf_email_token'")).fetchone() or [""])[0].strip()
ZONE = (db.execute(text("SELECT value FROM system_settings WHERE key='cf_zone_id_tovaads.com'")).fetchone() or [""])[0].strip().strip('"').strip("'")
db.close()


def req(path):
    r = urllib.request.Request(f"{BASE}/{path}", headers={"Authorization": f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode()[:300]
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


for lbl, p in [
    ("帐户级·目的地列表", f"accounts/{ACCOUNT}/email/routing/addresses"),
    ("帐户级·路由状态", f"accounts/{ACCOUNT}/email/routing"),
    ("zone级·规则(对照)", f"zones/{ZONE}/email/routing/rules"),
]:
    s, b = req(p)
    ok = isinstance(b, dict) and b.get("success")
    n = f" {len(b.get('result') or [])} 条" if ok and isinstance(b.get("result"), list) else ""
    err = "" if ok else " | " + json.dumps(b.get("errors") if isinstance(b, dict) else b, ensure_ascii=False)[:160]
    print(f"{lbl}: {'✅' if ok else '❌'} HTTP {s}{n}{err}")
