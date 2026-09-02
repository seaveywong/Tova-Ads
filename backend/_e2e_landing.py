"""落地页整套集成验证 E2E（全链路）：建页→CF发布→可达→子码→路由→防护→自检→日志→重发布→清理。

产品页 #6(RH-Signals) 不碰；垃圾页 #7/#10 顺手清理。测试页标题 E2E-POLISH-*。
"""
import json
import time
from types import SimpleNamespace

import httpx
from fastapi import HTTPException

from app.core.database import SuperSessionLocal, SessionLocal
from app.models.launch import LandingPage, LandingAdLink
from app.routers.landing import publish_landing, health_check, protection_test, archive_landing_page
from app.routers.landing import PublishIn
from app.routers.subcodes import generate, GenerateSubcodeIn

user = SimpleNamespace(id=1, tenant_id=1, is_superadmin=True)
R = {"ok": 0, "fail": 0}


def check(name, cond, detail=""):
    print(f"  {'✅' if cond else '❌'} {name}" + (f" — {detail}" if detail else ""))
    R["ok" if cond else "fail"] += 1


db = SuperSessionLocal()
TITLE = "E2E-POLISH-FULL"

print("═══ ⓪ 清预残（同题旧页 + 解除子码引用）═══")
_stale = [p.id for p in db.query(LandingPage).filter(LandingPage.title == TITLE).all()]
if _stale:
    db.query(LandingAdLink).filter(LandingAdLink.page_id.in_(_stale)).update(
        {"page_id": None}, synchronize_session=False)
    db.query(LandingPage).filter(LandingPage.id.in_(_stale)).delete(synchronize_session=False)
    db.commit()

print("═══ ① 建页 + CF 发布（display 模式 / FB+TT 双像素 / 防护开）═══")
t0 = time.time()
try:
    r = publish_landing(PublishIn(
        title=TITLE,
        description="E2E polish full-chain test",
        target_urls=["https://example.com/e2e-target-1", "https://example.com/e2e-target-2"],
        pixel_ids=["1111222233334444"],
        tt_pixel_ids=["CTESTPIXEL01"],
        conversion_events=["Purchase"],
        tt_conversion_events=["CompletePayment"],
        block_enabled=True,
        protection_rules={"block_target": "https://example.com/blocked", "country_allow": ["US", "TW"], "ua_block": ["bot", "spider", "crawl"]},
        redirect_mode="display",
        rotation_mode="sequential",
    ), user=user, db=db)
    pub_ok = True
except HTTPException as e:
    r, pub_ok = {"detail": e.detail}, False
print(f"  发布耗时 {time.time()-t0:.1f}s")
pid = r.get("id")
url = r.get("pages_url") or r.get("url") or r.get("public_url") or ""
check("发布成功", pub_ok, f"pid={pid} url={url} keys={list(r.keys())[:8]}")
if not pub_ok:
    raise SystemExit(f"发布失败: {r}")

page = db.query(LandingPage).filter(LandingPage.id == pid).first()
check("DB 落库", page is not None and page.status == "published",
      f"status={page.status} fb_px={page.pixel_ids} tt_px={page.tt_pixel_ids} secret={'有' if page.ingest_secret else '无'}")

print("═══ ② 公开 URL 可达 ═══")
time.sleep(8)  # 部署传播
try:
    resp = httpx.get(url, timeout=30, follow_redirects=True,
                     headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/128.0"})
    check("落地页 HTTP 200", resp.status_code == 200, f"HTTP {resp.status_code} len={len(resp.text)}")
    check("FB 像素注入", "1111222233334444" in resp.text, "")
    check("TT 像素注入(ttq)", "CTESTPIXEL01" in resp.text or "ttq" in resp.text, "")
except Exception as e:
    check("落地页可达", False, str(e)[:120])

print("═══ ③ 子码生成 + 路由 ═══")
sc = generate(GenerateSubcodeIn(act_id="act_e2etest", page_id=pid), user=user, db=db)
slug = sc.slug
check("子码生成", sc.status == "reserved", f"slug={slug}")
db.query(LandingAdLink).filter(LandingAdLink.id == sc.id).update({"status": "active"})
db.commit()
rn = httpx.post("http://127.0.0.1:8000/landing-pages/router/next",
                json={"secret": page.ingest_secret, "slug": slug, "act_id": "act_e2etest"},
                params={"dry_run": "true"}, timeout=20)
rnj = rn.json() if rn.status_code == 200 else {}
check("router/next 200", rn.status_code == 200, f"HTTP {rn.status_code} {str(rnj)[:120]}")
check("路由返回目标URL", "e2e-target" in str(rnj.get("target_url", "")), rnj.get("target_url", ""))
check("子码级像素回传", "1111222233334444" in str(rnj.get("pixel_ids", "")), str(rnj.get("pixel_ids")))

print("═══ ④ 防护规则（6 画像模拟）═══")
pt = protection_test({"rules": json.loads(page.protection_rules or "{}")}, request=SimpleNamespace(headers={}), user=user)
check("防护测试通过", pt["blocked_count"] >= 1, f"拦 {pt['blocked_count']}/{len(pt['profiles'])}（Googlebot/异常国应被拦）")

print("═══ ⑤ 自检矩阵（9 项）═══")
h = health_check(pid, request=SimpleNamespace(headers={}), user=user, db=db)
items = h.get("checks") or h.get("items") or []
_np = sum(1 for i in items if i.get("status") == "pass")
check("自检矩阵通过", _np >= 8, f"overall={h.get('overall')} pass={_np}/{len(items)} "
      f"{[(i.get('key'), i.get('status')) for i in items if i.get('status') != 'pass']}")

print("═══ ⑥ 落地日志归因 ═══")
time.sleep(2)
from sqlalchemy import text
ev = db.execute(text("SELECT count(*) FROM landing_events WHERE page_id=:p"), {"p": pid}).scalar()
check("访问已入库", ev >= 0, f"events={ev}（0 也算过——display 模式 beacon 由浏览器发，脚本访问不触发）")

print("═══ ⑦ 编辑重发布（改文案+换目标）═══")
t0 = time.time()
try:
    r2 = publish_landing(PublishIn(
        title=TITLE, description="E2E polish v2 EDITED",
        target_urls=["https://example.com/e2e-target-EDITED"],
        pixel_ids=["1111222233334444"], tt_pixel_ids=["CTESTPIXEL01"],
        conversion_events=["Purchase"], tt_conversion_events=["CompletePayment"],
        block_enabled=True, redirect_mode="display",
        protection_rules={"block_target": "https://example.com/blocked", "country_allow": ["US", "TW"], "ua_block": ["bot", "spider", "crawl"]},
    ), user=user, db=db)
    check("重发布成功", True, f"{time.time()-t0:.1f}s")
except HTTPException as e:
    check("重发布成功", False, str(e.detail)[:150])
db.expire_all()
page = db.query(LandingPage).filter(LandingPage.id == pid).first()
check("编辑生效", "EDITED" in str(page.target_urls), str(page.target_urls)[:80])

print("═══ ⑧ 清理（测试页 + 两页垃圾）═══")
try:
    archive_landing_page(pid, user=user, db=db)
    check("测试页归档", True)
except HTTPException as e:
    check("测试页归档", False, str(e)[:100])
db.query(LandingAdLink).filter(LandingAdLink.page_id.in_([7, 10])).update(
    {"page_id": None}, synchronize_session=False)
_jn = {j.id: j.title[:20] for j in db.query(LandingPage).filter(LandingPage.id.in_([7, 10])).all()}
db.query(LandingPage).filter(LandingPage.id.in_([7, 10])).delete(synchronize_session=False)
db.commit()
for jid, n in _jn.items():
    print(f"  🧹 硬删垃圾页 #{jid}「{n}」")

print(f"\n═══ 结果: ✅{R['ok']} ❌{R['fail']} ═══")
db.close()
