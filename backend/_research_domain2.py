"""tovaads.com 调研 v2：Pages 项目域名（domains 是字符串列表）+ Worker 路由。只读。"""
import json
import urllib.request

B = "https://api.cloudflare.com/client/v4"
T = [l.split("=", 1)[1].strip() for l in open("/opt/toveads/backend/.env") if l.startswith("CF_API_TOKEN=")][0]
A = "fb73c8b129b67f0e48d4bc80d6dd41fa"
Z = "c56b4d20555141837fe2e3de5d9da306"


def g(path):
    r = urllib.request.Request(f"{B}/{path}", headers={"Authorization": "Bearer " + T})
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            b = json.loads(resp.read().decode() or "{}")
            return b.get("result") if b.get("success") else f"ERR {b.get('errors')}"
    except Exception as e:
        return f"HTTPERR {str(e)[:80]}"


print("═══ Pages 项目 + 域名 ═══")
projects = g(f"accounts/{A}/pages/projects")
if isinstance(projects, list):
    for p in projects:
        doms = p.get("domains") or []
        doms = [d if isinstance(d, str) else d.get("name") for d in doms]
        print(f"  {p['name']:28} 域名={doms} prod_branch={p.get('production_branch')}")
else:
    print(" ", projects)

print("\n═══ Worker 路由（tovaads.com zone）═══")
routes = g(f"zones/{Z}/workers/routes")
if isinstance(routes, list):
    for r in routes:
        print(f"  {r.get('pattern'):44} → {r.get('script')}")
    print(f"  共 {len(routes)} 条")
else:
    print(" ", routes)

print("\n═══ Worker 脚本清单 ═══")
scripts = g(f"accounts/{A}/workers/scripts")
if isinstance(scripts, list):
    for s in scripts[:20]:
        print(f"  {s.get('id')}")
else:
    print(" ", scripts)

print("\n═══ www 现在实际返回什么 ═══")
import urllib.request as u2
for host in ("https://www.tovaads.com", "https://tovaads.com", "https://random9x.tovaads.com"):
    try:
        req = u2.Request(host, method="HEAD", headers={"User-Agent": "probe"})
        with u2.urlopen(req, timeout=10) as resp:
            print(f"  {host:36} HTTP {resp.status} server={resp.headers.get('server')} loc={resp.headers.get('location','')}")
    except Exception as e:
        print(f"  {host:36} {str(e)[:80]}")
