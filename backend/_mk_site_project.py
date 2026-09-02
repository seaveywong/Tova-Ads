"""建 tovaads-site Pages 项目。"""
import json
import urllib.request
import urllib.error

B = "https://api.cloudflare.com/client/v4"
T = [l.split("=", 1)[1].strip() for l in open("/opt/toveads/backend/.env") if l.startswith("CF_API_TOKEN=")][0]
A = "fb73c8b129b67f0e48d4bc80d6dd41fa"
H = {"Authorization": "Bearer " + T, "Content-Type": "application/json"}
req = urllib.request.Request(f"{B}/accounts/{A}/pages/projects",
                             data=json.dumps({"name": "tovaads-site", "production_branch": "main"}).encode(),
                             method="POST", headers=H)
try:
    b = json.loads(urllib.request.urlopen(req, timeout=20).read())
    print("项目创建:", "OK" if b.get("success") else json.dumps(b.get("errors"), ensure_ascii=False)[:200])
except urllib.error.HTTPError as e:
    print("HTTP", e.code, e.read().decode()[:200])
