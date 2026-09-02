"""tovaads.com 域名现状调研：DNS 全量 + Pages 项目/域名绑定 + Worker 路由。只读。"""
import json
import urllib.request
import urllib.error

B = "https://api.cloudflare.com/client/v4"
import os


def read_env_token():
    for line in open("/opt/toveads/backend/.env"):
        if line.startswith("CF_API_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("no token")


T = read_env_token()
A = "fb73c8b129b67f0e48d4bc80d6dd41fa"
Z = "c56b4d20555141837fe2e3de5d9da306"


def g(path):
    r = urllib.request.Request(f"{B}/{path}", headers={"Authorization": "Bearer " + T})
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            b = json.loads(resp.read().decode() or "{}")
            return b.get("result") if b.get("success") else f"ERR {b.get('errors')}"
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}"


print("═══ 1. DNS 记录（tovaads.com zone）═══")
recs = g(f"zones/{Z}/dns_records?per_page=100")
if isinstance(recs, list):
    for r in sorted(recs, key=lambda x: (x["type"], x["name"])):
        proxied = "🟠代理" if r.get("proxied") else "⚪仅DNS"
        content = (r.get("content") or "")[:60]
        print(f"  {r['type']:6} {r['name']:32} → {content:60} {proxied}")
    print(f"  共 {len(recs)} 条")
else:
    print(" ", recs)

print("\n═══ 2. Pages 项目 + 绑定的自定义域 ═══")
projects = g(f"accounts/{A}/pages/projects")
if isinstance(projects, list):
    for p in projects:
        doms = [d.get("name") for d in (p.get("domains") or [])]
        print(f"  项目 {p['name']:24} 域名: {doms}  (prod_branch={p.get('production_branch')})")
else:
    print(" ", projects)

print("\n═══ 3. Workers 路由（落地页相关）═══")
routes = g(f"zones/{Z}/workers/routes")
if isinstance(routes, list):
    for r in routes[:15]:
        print(f"  {r.get('pattern'):40} → {r.get('script')}")
    print(f"  共 {len(routes)} 条")
else:
    print(" ", routes)

print("\n═══ 4. Zone 级 DNS 设置（只看关键项）═══")
for name in ("", "lp5", "api", "www", "app"):
    recs2 = g(f"zones/{Z}/dns_records?name={'tovaads.com' if not name else name + '.tovaads.com'}&per_page=20")
    if isinstance(recs2, list) and recs2:
        types = {(r["type"], (r.get("content") or "")[:40], r.get("proxied")) for r in recs2}
        print(f"  {name or '@':6} {types}")
