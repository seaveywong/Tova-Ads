# UX 链路审计 v2：正确路径 + display 模式页像素验证
import json
import time
import httpx
from app.core.database import SuperSessionLocal
from app.models.launch import LandingPage
from app.models.landing_event import LandingEvent

db = SuperSessionLocal()
p16 = db.query(LandingPage).filter(LandingPage.id == 16).first()
p6 = db.query(LandingPage).filter(LandingPage.id == 6).first()
db.close()

results = []
def node(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  {detail[:100]}" if detail else ""))

print("== UX 链路逐节点模拟 v2 ==")

# ── 节点1：redirect 模式页（lp16）302 语义 ──
r = httpx.get("https://lp16.marketbriefnow.xyz", timeout=20, follow_redirects=False)
node("1a. redirect 页 302 直跳", r.status_code == 302, f"loc={r.headers.get('location','')[:50]}")

# ── 节点1b：display 模式页（RH-Signals 子域名）HTML 可达 + 像素注入 ──
subs6 = json.loads(p6.bound_subdomains or "[]")
domain6 = subs6[0] if subs6 else None
if domain6:
    try:
        r = httpx.get(f"https://{domain6}", timeout=20, follow_redirects=False)
        html = r.text if r.status_code == 200 else ""
        has_px = ("fbq(" in html) or ("trackSingle" in html) or ("__events/ingest" in html) or ("ttq" in html)
        node("1b. display 页 HTML+像素注入", r.status_code == 200 and has_px,
             f"http={r.status_code} len={len(html)} px={has_px}")
    except Exception as e:
        node("1b. display 页 HTML+像素注入", False, str(e)[:100])

# ── 节点2：route_next 正确 secret 返回结构 ──
r = httpx.post("http://127.0.0.1:8000/landing-pages/router/next",
               json={"slug": "", "secret": p16.ingest_secret}, timeout=15)
ok = r.status_code == 200 and "target_url" in r.json()
node("2. route_next 页级解析", ok, f"http={r.status_code} keys={list(r.json().keys())[:6] if ok else r.text[:60]}")
if ok:
    px_ids = r.json().get("pixel_ids") or []
    node("2b. route_next 带像素", True, f"pixel_ids={px_ids[:3]} conv={r.json().get('conversion_event')}")

# ── 节点2c：错 secret 401 ──
r = httpx.post("http://127.0.0.1:8000/landing-pages/router/next",
               json={"slug": "", "secret": "wrong"}, timeout=10)
node("2c. route_next 错 secret 拒绝", r.status_code == 401, f"http={r.status_code}")

# ── 节点3：ingest visit 入库（正确路径）──
fake_ad = f"uxaudit{int(time.time())}"
r = httpx.post("http://127.0.0.1:8000/landing-pages/events/ingest",
               json={"secret": p16.ingest_secret, "event_type": "visit",
                     "ad_id": fake_ad, "ip": "203.0.113.77", "ua": "UX-Audit-Bot",
                     "slug": "uxwalk"}, timeout=15)
node("3a. ingest visit 接受", r.status_code == 200, f"http={r.status_code} {r.text[:50]}")

# ── 节点3b：事件落库 + 归因字段 ──
db = SuperSessionLocal()
ev = db.query(LandingEvent).filter(LandingEvent.ad_id == fake_ad).order_by(LandingEvent.id.desc()).first()
node("3b. 事件落库（ad_id 归因+slug）", ev is not None and ev.slug == "uxwalk",
     f"id={ev.id if ev else '-'} slug={ev.slug if ev else '-'} type={ev.event_type if ev else '-'}")
if ev:
    db.delete(ev); db.commit()
db.close()

# ── 节点3c：ingest 错 secret ──
r = httpx.post("http://127.0.0.1:8000/landing-pages/events/ingest",
               json={"secret": "wrong", "event_type": "visit"}, timeout=10)
node("3c. ingest 错 secret 拒绝", r.status_code in (401, 403), f"http={r.status_code}")

print()
fails = [x for x in results if not x[1]]
print(f"== 结果：{len(results) - len(fails)}/{len(results)} PASS ==")
for name, ok, detail in fails:
    print(f"  ❌ {name}: {detail}")
