"""E2E 收尾：①项目URL复测(浏览器UA) ②清测试子码 ③删测试CF项目(14/15)。"""
import json
import urllib.request

import httpx
from sqlalchemy import text

from app.core.database import SuperSessionLocal

print("═══ ① 项目 URL 复测（部署传播+证书就绪后）═══")
for u in ("https://tovaads-landing-15.pages.dev", "https://a12a2ec9.tovaads-landing-15.pages.dev"):
    try:
        r = httpx.get(u, timeout=30, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/128.0"})
        has_fb = "1111222233334444" in r.text
        has_tt = "CTESTPIXEL01" in r.text
        print(f"  {'✅' if r.status_code == 200 else '❌'} {u} → HTTP {r.status_code} FB像素注入={has_fb} TT像素注入={has_tt}")
    except Exception as e:
        print(f"  ❌ {u} → {str(e)[:80]}")

print("═══ ② 清测试子码 ═══")
db = SuperSessionLocal()
n = db.execute(text("DELETE FROM landing_ad_links WHERE act_id = 'act_e2etest'")).rowcount
db.commit()
print(f"  🧹 删除测试子码 {n} 条")
ev = db.execute(text("DELETE FROM landing_events WHERE page_id IN (14, 15)")).rowcount
db.commit()
print(f"  🧹 删除测试事件 {ev} 条")
pages = db.execute(text("SELECT id, title, status FROM landing_pages ORDER BY id")).fetchall()
for p in pages:
    print(f"  剩余page#{p[0]}「{str(p[1])[:24]}」 {p[2]}")
db.close()

print("═══ ③ 删测试 CF 项目（tovaads-landing-14/15）═══")
B = "https://api.cloudflare.com/client/v4"
T = [l.split("=", 1)[1].strip() for l in open("/opt/toveads/backend/.env") if l.startswith("CF_API_TOKEN=")][0]
A = "fb73c8b129b67f0e48d4bc80d6dd41fa"
H = {"Authorization": "Bearer " + T}
for proj in ("tovaads-landing-14", "tovaads-landing-15"):
    req = urllib.request.Request(f"{B}/accounts/{A}/pages/projects/{proj}", method="DELETE", headers=H)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            b = json.loads(resp.read().decode() or "{}")
            print(f"  🧹 {proj}: {'已删' if b.get('success') else b.get('errors')}")
    except Exception as e:
        print(f"  ⚠️ {proj}: {str(e)[:80]}（不存在=已干净）")
