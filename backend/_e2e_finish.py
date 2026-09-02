"""E2E 终章：①preview_enabled=True 重发布+预览令牌验证 ②归档 ③清 5 个孤儿CF项目(11-15)+DNS。"""
import json
import time
import urllib.request
import urllib.error
from types import SimpleNamespace

import httpx

from app.core.database import SuperSessionLocal
from app.models.launch import LandingPage
from app.routers.landing import publish_landing, archive_landing_page, PublishIn

B = "https://api.cloudflare.com/client/v4"
T = [l.split("=", 1)[1].strip() for l in open("/opt/toveads/backend/.env") if l.startswith("CF_API_TOKEN=")][0]
A = "fb73c8b129b67f0e48d4bc80d6dd41fa"
H = {"Authorization": "Bearer " + T}
user = SimpleNamespace(id=1, tenant_id=1, is_superadmin=True)
RULES = {"block_target": "https://example.com/blocked", "country_allow": ["US", "TW"],
         "ua_block": ["bot", "spider", "crawl"]}
db = SuperSessionLocal()

print("═══ ① 重发布（preview_enabled=True）═══")
r = publish_landing(PublishIn(
    title="E2E-POLISH-FULL", description="preview verify",
    target_urls=["https://example.com/e2e-target-EDITED"],
    pixel_ids=["1111222233334444"], tt_pixel_ids=["CTESTPIXEL01"],
    conversion_events=["Purchase"], tt_conversion_events=["CompletePayment"],
    block_enabled=True, redirect_mode="display", protection_rules=RULES,
    preview_enabled=True,
), user=user, db=db)
pid = r.get("id")
db.expire_all()
page = db.query(LandingPage).filter(LandingPage.id == pid).first()
url = f"https://tovaads-landing-{pid}.pages.dev"
print(f"  pid={pid} preview_enabled={page.preview_enabled} token={str(page.preview_token)[:8]}…")
time.sleep(20)

print("═══ ② 预览令牌验证 ═══")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/128.0"}
rp = httpx.get(f"{url}?_pv={page.preview_token}", headers=UA, timeout=30, follow_redirects=True)
fb = "1111222233334444" in rp.text
tt = "CTESTPIXEL01" in rp.text or "ttq" in rp.text
print(f"  {'✅' if rp.status_code == 200 and fb else '❌'} 预览模式: HTTP {rp.status_code} FB像素={fb} TT像素={tt}")
rno = httpx.get(url, headers=UA, timeout=30, follow_redirects=False)
print(f"  {'✅' if rno.status_code == 302 else '❌'} 无令牌仍被拦: HTTP {rno.status_code} → {rno.headers.get('location','')[:40]}")

print("═══ ③ 归档测试页 ═══")
archive_landing_page(pid, user=user, db=db)
print(f"  ✅ page#{pid} archived")

print("═══ ④ 清孤儿 CF 项目（11-15）═══")
def call(method, path):
    req = urllib.request.Request(f"{B}/{path}", method=method, headers=H)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode()[:300])
        except Exception:
            return e.code, {}

for n in (11, 12, 13, 14, 15):
    proj = f"tovaads-landing-{n}"
    s, b = call("GET", f"accounts/{A}/pages/projects/{proj}/domains")
    doms = [d.get("name") for d in (b.get("result") or []) if d.get("name") and not d["name"].endswith("pages.dev")]
    for d in doms:
        call("DELETE", f"accounts/{A}/pages/projects/{proj}/domains/{d}")
    s, b = call("DELETE", f"accounts/{A}/pages/projects/{proj}")
    print(f"  🧹 {proj}: {'已删' if b.get('success') else '不存在/已清'} (域名 {doms or '无'})")

print("═══ ⑤ 清 lp11-15 DNS 记录（marketbriefnow.xyz zone）═══")
s, b = call("GET", "zones?name=marketbriefnow.xyz")
zid = (b.get("result") or [{}])[0].get("id")
if zid:
    for n in (11, 12, 13, 14, 15):
        name = f"lp{n}.marketbriefnow.xyz"
        s, b = call("GET", f"zones/{zid}/dns_records?name={name}")
        for rec in (b.get("result") or []):
            call("DELETE", f"zones/{zid}/dns_records/{rec['id']}")
            print(f"  🧹 DNS {name} 已删")
else:
    print("  zone 未找到（跳过 DNS 清理）")

print("\n═══ 最终状态 ═══")
for p in db.query(LandingPage).order_by(LandingPage.id).all():
    print(f"  page#{p.id}「{str(p.title)[:24]}」 {p.status}")
db.close()
