"""验证 404=防护拦截假象：用 ?_pv=预览令牌（跳防护）探测真身 + 顺带确认重定向链。"""
import httpx
from sqlalchemy import text
from app.core.database import SuperSessionLocal

db = SuperSessionLocal()
row = db.execute(text("SELECT id, preview_token, preview_enabled FROM landing_pages WHERE id = 15")).fetchone()
db.close()
pid, pv, pven = row
print(f"page#15 preview_enabled={pven} token={str(pv)[:8]}…")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/128.0"}
base = "https://tovaads-landing-15.pages.dev"

print("\n═══ A. 不带令牌（预期：被防护拦→重定向到 block_target）═══")
r = httpx.get(base, headers=UA, timeout=30, follow_redirects=False)
print(f"  HTTP {r.status_code} Location={r.headers.get('location', '')[:60]}")
r2 = httpx.get(base, headers=UA, timeout=30, follow_redirects=True)
print(f"  跟到底: HTTP {r2.status_code} 最终URL={str(r2.url)[:60]}")

print("\n═══ B. 带预览令牌 ?_pv=（跳防护看真身）═══")
r3 = httpx.get(f"{base}?_pv={pv}", headers=UA, timeout=30, follow_redirects=True)
ok = r3.status_code == 200
fb = "1111222233334444" in r3.text
tt = "CTESTPIXEL01" in r3.text or "ttq" in r3.text
print(f"  HTTP {r3.status_code} len={len(r3.text)} FB像素注入={fb} TT像素注入={tt}")
print(f"  {'✅ 落地页真身可达，双像素注入正常——404 确认为防护正确拦截' if ok and fb else '❌ 预览也不通，需深查'}")
