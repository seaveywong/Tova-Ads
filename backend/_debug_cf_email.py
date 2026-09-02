"""CF Token 深挖：主 Token 补测 + cf_email_token 存储值形状检查（strip 前后对比）。"""
import json
import urllib.request
import urllib.error
from sqlalchemy import text
from app.core.database import SuperSessionLocal
from app.core.config import settings

ZONE = "c56b4d20555141837fe2e3de5da306"
BASE = "https://api.cloudflare.com/client/v4"


def call(tok, path):
    req = urllib.request.Request(f"{BASE}/{path}", headers={"Authorization": f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode()[:400]
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw
    except Exception as e:
        return -1, str(e)[:150]


def shape(v):
    """值的形状（不泄密）：长度 + 前后字符 + 是否含空白/引号"""
    return (f"len={len(v)} head={v[:6]!r} tail={v[-4:]!r} "
            f"含空格={' ' in v} 含换行={chr(10) in v or chr(13) in v} 含引号={chr(34) in v or chr(39) in v}")


db = SuperSessionLocal()
etok = (db.execute(text("SELECT value FROM system_settings WHERE key='cf_email_token'")).fetchone() or [""])[0]
db.close()

print("== cf_email_token 存储值形状 ==")
print(shape(etok))
etok_stripped = etok.strip()
if etok_stripped != etok:
    print("strip 后形状:", shape(etok_stripped))

for label, tok in [("原始值", etok), ("strip后", etok_stripped)]:
    if not tok:
        continue
    s, b = call(tok, "user/tokens/verify")
    ok = isinstance(b, dict) and b.get("success")
    status = b.get("result", {}).get("status") if ok else json.dumps(b.get("errors", b), ensure_ascii=False)[:120]
    print(f"verify[{label}]: HTTP {s} {'✅ ' + str(status) if ok else '❌ ' + str(status)}")

print("\n== 主 Token (.env, 经 settings 加载) ==")
main = settings.cf_api_token or ""
print(shape(main) if main else "(空)")
if main.strip():
    s, b = call(main.strip(), "user/tokens/verify")
    ok = isinstance(b, dict) and b.get("success")
    print(f"verify[主Token]: HTTP {s} {'✅' if ok else '❌ ' + json.dumps(b.get('errors', b), ensure_ascii=False)[:150]}")
    for lbl, p in [("Email Routing 状态", f"zones/{ZONE}/email/routing"),
                   ("目的地邮箱列表", f"zones/{ZONE}/email/routing/addresses"),
                   ("规则列表", f"zones/{ZONE}/email/routing/rules")]:
        s, b = call(main.strip(), p)
        ok = isinstance(b, dict) and b.get("success")
        extra = f" {len(b.get('result') or [])} 条" if ok and isinstance(b.get("result"), list) else ""
        errs = "" if ok else " | " + "; ".join(f"code={e.get('code')} {e.get('message','')}" for e in (b.get("errors") or []))[:160] if isinstance(b, dict) else str(b)[:120]
        print(f"{lbl}: {'✅' if ok else '❌'} HTTP {s}{extra}{errs}")

# strip 后的邮箱 token 再试一次 zone 端点（若 verify 过了才有意义）
if etok_stripped:
    s, b = call(etok_stripped, f"zones/{ZONE}/email/routing")
    ok = isinstance(b, dict) and b.get("success")
    errs = "" if ok else " | " + json.dumps(b.get("errors", b), ensure_ascii=False)[:200]
    print(f"\nstrip后邮箱Token → Email Routing 状态: {'✅' if ok else '❌'} HTTP {s}{errs}")
