"""阶段1：给 tovaads Pages 项目加自定义域 app.tovaads.com（CF 同帐号 zone 会自动建 CNAME）。"""
import json
import time
import urllib.request
import urllib.error

B = "https://api.cloudflare.com/client/v4"
T = [l.split("=", 1)[1].strip() for l in open("/opt/toveads/backend/.env") if l.startswith("CF_API_TOKEN=")][0]
A = "fb73c8b129b67f0e48d4bc80d6dd41fa"
H = {"Authorization": f"Bearer {T}", "Content-Type": "application/json"}


def call(method, path, body=None):
    data = json.dumps(body).encode() if body else None
    r = urllib.request.Request(f"{B}/{path}", data=data, method=method, headers=H)
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode()[:300])
        except Exception:
            return e.code, {}


# 1) 加域（幂等：已存在则 400 duplicate，视为成功）
s, b = call("POST", f"accounts/{A}/pages/projects/tovaads/domains", {"name": "app.tovaads.com"})
if b.get("success"):
    print(f"✅ 域已加: {json.dumps(b.get('result'), ensure_ascii=False)[:150]}")
elif any("exist" in str(e).lower() or "duplicate" in str(e).lower() for e in (b.get("errors") or [])) or s == 409:
    print("✅ 域已存在（幂等通过）")
else:
    print(f"❌ 加域失败 HTTP {s}: {json.dumps(b.get('errors'), ensure_ascii=False)[:200]}")
    raise SystemExit(1)

# 2) 等状态就绪（pending → active，证书签发一般 <1min）
for i in range(6):
    time.sleep(10)
    s, b = call("GET", f"accounts/{A}/pages/projects/tovaads/domains")
    dom = next((d for d in (b.get("result") or []) if d.get("name") == "app.tovaads.com"), None)
    if dom:
        print(f"  状态: {dom.get('status')} (第{(i+1)*10}秒)")
        if dom.get("status") == "active":
            break

# 3) 验证可达
try:
    req = urllib.request.Request("https://app.tovaads.com", method="HEAD")
    with urllib.request.urlopen(req, timeout=15) as resp:
        print(f"✅ https://app.tovaads.com HTTP {resp.status}")
except Exception as e:
    print(f"⚠️ 探测: {str(e)[:120]}（证书刚签发可能要等 1-2 分钟，不影响后续步骤）")
