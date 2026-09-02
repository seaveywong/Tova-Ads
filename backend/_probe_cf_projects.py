"""查 tovaads-landing-14/15 项目实况：存在性/production_branch/deployments + 删除400真因。"""
import json
import urllib.request
import urllib.error

B = "https://api.cloudflare.com/client/v4"
T = [l.split("=", 1)[1].strip() for l in open("/opt/toveads/backend/.env") if l.startswith("CF_API_TOKEN=")][0]
A = "fb73c8b129b67f0e48d4bc80d6dd41fa"
H = {"Authorization": "Bearer " + T}


def call(method, path):
    req = urllib.request.Request(f"{B}/{path}", method=method, headers=H)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode()[:400])
        except Exception:
            return e.code, {}


print("═══ 全部 Pages 项目 ═══")
s, b = call("GET", f"accounts/{A}/pages/projects")
for p in (b.get("result") or []):
    print(f"  {p['name']:28} prod_branch={p.get('production_branch')} domains={[d for d in (p.get('domains') or [])][:2]}")

for proj in ("tovaads-landing-14", "tovaads-landing-15"):
    print(f"\n═══ {proj} ═══")
    s, b = call("GET", f"accounts/{A}/pages/projects/{proj}")
    if s == 200:
        print(f"  存在 ✅ prod_branch={b['result'].get('production_branch')}")
        s2, b2 = call("GET", f"accounts/{A}/pages/projects/{proj}/deployments?per_page=3")
        for d in (b2.get("result") or []):
            print(f"  deployment: {str(d.get('id'))[:10]} branch={d.get('deployment_trigger',{}).get('metadata',{}).get('branch')} "
                  f"env={d.get('env_status') or d.get('environment')} latest={d.get('is_skew') is not None and '' or ''}{d.get('modified_on','')[:19]}")
    else:
        print(f"  GET HTTP {s}: {json.dumps(b.get('errors'), ensure_ascii=False)[:150]}")
    s3, b3 = call("DELETE", f"accounts/{A}/pages/projects/{proj}")
    print(f"  DELETE: HTTP {s3} {json.dumps(b3.get('errors') if not b3.get('success') else 'OK', ensure_ascii=False)[:200]}")
