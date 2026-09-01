# -*- coding: utf-8 -*-
"""#187 落地页整套集成验证：生产环境端到端 smoke。

矩阵：M1 建页发布 / M2 公开URL / M3 自检矩阵 / M4 子码链路 / M5 落地日志
      M6 防护 / M7 编辑重发布 / M8 FB屏蔽扫描 / M9 删除清理
"""
import json, time, base64, sys, traceback
import urllib.request, urllib.error
import http.client, ssl

BASE = "http://127.0.0.1:8000"
UA_PC = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
UA_MB = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 Version/17.4 Mobile/15E148 Safari/604.1"
UA_FB = "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)"
PIXEL = "4646550058958676"
ACT = "1371278438178043"
AD = "880187123456"
TITLE1 = "_verify187 E2E test page"
TITLE2 = "_verify187 E2E test page v2"
BLOCK_TARGET = "https://tovaads.com/company"
TARGET = "https://tovaads.com/company"

RESULTS = []


def record(item, ok, note=""):
    RESULTS.append((item, "PASS" if ok else "FAIL", str(note)))
    print("[%s] %s | %s" % (item, "PASS" if ok else "FAIL", note))


def section(name):
    print("\n" + "=" * 20 + " " + name + " " + "=" * 20)


def api(method, path, body=None, timeout=240, tok=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, method=method)
    req.add_header("Content-Type", "application/json")
    if tok:
        req.add_header("Authorization", "Bearer " + tok)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(raw or "{}")
            except Exception:
                return r.status, {"_raw": raw[:500]}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw or "{}")
        except Exception:
            return e.code, {"_raw": raw[:500]}


_CTX = ssl.create_default_context()


def pub(host, path, ua=UA_PC, timeout=25):
    """公网 HTTPS GET，不跟随重定向。ua=None 表示完全不带 UA 头。返回 (status, body, location)。"""
    conn = http.client.HTTPSConnection(host, timeout=timeout, context=_CTX)
    h = {"User-Agent": ua} if ua is not None else {}
    conn.request("GET", path, headers=h)
    r = conn.getresponse()
    body = r.read().decode("utf-8", "replace")
    st, loc = r.status, r.getheader("Location")
    conn.close()
    return st, body, loc


# ───────────────────────── 0. 铸 token ─────────────────────────
section("0. mint token")
from app.core.security import create_access_token
from app.core.database import SuperSessionLocal
from app.models.auth import User

_db = SuperSessionLocal()
_u = _db.query(User).filter(User.email == "seavey@tovaads.com").first()
TOK = create_access_token(user_id=_u.id, email=_u.email, tenant_id=1, role="owner", is_superadmin=_u.is_superadmin)
_db.close()
st, me = api("GET", "/auth/me", tok=TOK)
print("auth/me:", st, json.dumps({k: me.get(k) for k in ("email", "tenant_id", "role")}, ensure_ascii=False))
assert st == 200, "token mint failed"
record("M0", True, "token ok")

# ───────────────────────── M1 建页→发布 ─────────────────────────
section("M1. create + publish (worker mode)")
st, doms = api("GET", "/landing-lib/domains", tok=TOK)
if isinstance(doms, dict):
    doms = doms.get("items") or []
dom_list = [d.get("domain") for d in doms]
print("domain lib:", st, dom_list)
ROOT_DOMAIN = dom_list[0] if dom_list else ""
record("M1-pre", ROOT_DOMAIN != "", "域名库: %s" % dom_list)

pub_body = {
    "title": TITLE1,
    "description": "verify187 landing e2e",
    "target_urls": [TARGET],
    "pixel_ids": [PIXEL],
    "conversion_events": ["Contact"],
    "redirect_mode": "display",
    "rotation_mode": "first",
    "block_enabled": True,
    "protection_rules": {"block_target": BLOCK_TARGET, "query_block": ["v187block"]},
    "preview_enabled": True,
    "custom_domains": [ROOT_DOMAIN] if ROOT_DOMAIN else None,
    "dedup_enabled": False,
}
t0 = time.time()
st, res = api("POST", "/landing/publish", pub_body, timeout=300, tok=TOK)
print("publish:", st, "in %.1fs" % (time.time() - t0))
print(json.dumps(res, ensure_ascii=False, default=str)[:1200])
if st != 200:
    record("M1", False, "publish failed %s %s" % (st, res))
    print(json.dumps(RESULTS, ensure_ascii=False))
    sys.exit(1)
PID = res.get("id")
PAGES_DEV = "tovaads-landing-%d.pages.dev" % PID
sc = res.get("self_check") or {}
record("M1", res.get("status") == "published" and PID is not None,
       "page id=%s pages.dev=%s subdomains=%s self_check=%s(%s)" % (
           PID, PAGES_DEV, res.get("subdomains"), sc.get("overall"), sc.get("summary")))

st, detail = api("GET", "/landing/pages/%d" % PID, tok=TOK)
PUB_HOST = (detail.get("public_url") or "").replace("https://", "").rstrip("/")
PV_TOKEN = detail.get("preview_token") or ""
print("public_url:", detail.get("public_url"), "| bound_subdomains:", detail.get("bound_subdomains"),
      "| ingest_secret set:", bool(detail.get("ingest_secret")), "| preview_token set:", bool(PV_TOKEN))
record("M1b", bool(PUB_HOST) and bool(detail.get("ingest_secret")) and bool(PV_TOKEN),
       "detail ok public=%s preview_token=%d chars" % (PUB_HOST, len(PV_TOKEN)))

# ───────────────────────── M2 公开 URL 可达 ─────────────────────────
section("M2. public URL reachable")


def fetch_root_with_retry(host, tries=8, delay=5, ua=UA_PC, path="/"):
    last = None
    for i in range(tries):
        try:
            st, body, loc = pub(host, path, ua=ua)
            if st < 500:
                return st, body, loc
            last = (st, body[:100], loc)
        except Exception as e:
            last = ("ERR", str(e)[:120], "")
        time.sleep(delay)
    return (last if last else ("ERR", "no attempt", ""))


st_pd, body_pd, _ = fetch_root_with_retry(PAGES_DEV, tries=3, delay=4)
ok_pd = st_pd == 200 and TITLE1 in body_pd and "__LP_" not in body_pd
record("M2-pages.dev", ok_pd, "HTTP %s title_in_html=%s placeholder_leftover=%s len=%d" % (
    st_pd, TITLE1 in body_pd, "__LP_" in body_pd, len(body_pd)))

st_cd, body_cd, _ = fetch_root_with_retry(PUB_HOST, tries=8, delay=6)
ok_cd = st_cd == 200 and TITLE1 in body_cd
record("M2-custom-domain", ok_cd, "https://%s/ HTTP %s title_in_html=%s" % (PUB_HOST, st_cd, TITLE1 in (body_cd or "")))

st_h, _, _ = pub(PUB_HOST if st_cd == 200 else PAGES_DEV, "/__health")
record("M2-worker-health", st_h == 200, "/__health HTTP %s" % st_h)

st_pv, body_pv, _ = pub(PUB_HOST if st_cd == 200 else PAGES_DEV, "/?_pv=" + PV_TOKEN)
record("M2-preview", st_pv == 200 and TITLE1 in (body_pv or ""), "?_pv=token HTTP %s title=%s" % (st_pv, TITLE1 in (body_pv or "")))

HOST = PUB_HOST if st_cd == 200 else PAGES_DEV
print("主验证域名:", HOST)

# ───────────────────────── M4 子码链路（先于 health，让 fb_subcode 有样本）─────────────────
section("M4. subcode pipeline")
st, sub = api("POST", "/subcodes/generate", {"page_id": PID, "act_id": ACT}, tok=TOK)
print("generate:", st, json.dumps(sub, ensure_ascii=False))
SLUG = sub.get("slug", "")
SID = sub.get("id")
record("M4-generate", st == 200 and bool(SLUG), "slug=%s id=%s status=%s" % (SLUG, SID, sub.get("status")))

sub_path = "/a/%s?ad=%s&act=%s&fbclid=IwAR187verify" % (SLUG, AD, ACT)
st_r, body_r, loc_r = pub(HOST, sub_path, ua=UA_MB)
print("visit /a/ ->", st_r, "Location:", (loc_r or "")[:160])
_d = ""
if loc_r and "_d=" in loc_r:
    _d = loc_r.split("_d=")[1].split("&")[0]
info = {}
try:
    info = json.loads(base64.b64decode(_d).decode("utf-8", "replace"))
except Exception as e:
    print("_d decode fail:", e)
print("_d decoded:", json.dumps(info, ensure_ascii=False))
ok_d = (st_r == 302 and "/?_d=" in (loc_r or "")
        and info.get("p") == PIXEL and info.get("s") == SLUG
        and info.get("a") == AD and info.get("t") == TARGET)
record("M4-route", ok_d, "302->/?_d= pixel=%s slug=%s ad=%s target=%s conv=%s" % (
    info.get("p"), info.get("s"), info.get("a"), info.get("t"), info.get("c")))

# 中间页(带 _d)可达
inner_path = "/?_d=" + _d + "&fbclid=IwAR187verify"
st_i, body_i, _ = pub(HOST, inner_path, ua=UA_MB)
record("M4-inner-page", st_i == 200 and TITLE1 in (body_i or ""), "/?_d=.. HTTP %s title=%s len=%d" % (st_i, TITLE1 in (body_i or ""), len(body_i or "")))

# 子码自动绑：访问带 ad_id → active
time.sleep(4)
st, sub_list = api("GET", "/subcodes?page_id=%d" % PID, tok=TOK)
_bound = next((i for i in sub_list.get("items", []) if i.get("slug") == SLUG), {})
record("M4-autobind", _bound.get("status") == "active" and _bound.get("ad_id") == AD,
       "subcode status=%s ad_id=%s visit_count=%s" % (_bound.get("status"), _bound.get("ad_id"), _bound.get("visit_count")))

# ───────────────────────── M5 落地日志 ─────────────────────────
section("M5. landing logs")
time.sleep(3)
st, logs = api("GET", "/landing/logs?page_id=%d&limit=50" % PID, tok=TOK)
ev_visit = next((i for i in logs.get("items", []) if i.get("event_type") == "visit" and i.get("slug") == SLUG), None)
print("logs total:", logs.get("total"))
if ev_visit:
    print("visit event:", json.dumps({k: ev_visit.get(k) for k in (
        "event_type", "slug", "ad_id", "act_id", "fired_pixel_ids", "target_url", "decision",
        "device_type", "browser", "source_type", "source_platform", "asn", "country")}, ensure_ascii=False))
record("M5-visit-event", bool(ev_visit) and ev_visit.get("fired_pixel_ids") == PIXEL
       and ev_visit.get("ad_id") == AD and ev_visit.get("decision") == "display",
       "event=%s fired_pixel=%s act=%s device=%s source_type=%s" % (
           bool(ev_visit), (ev_visit or {}).get("fired_pixel_ids"), (ev_visit or {}).get("act_id"),
           (ev_visit or {}).get("device_type"), (ev_visit or {}).get("source_type")))
st, stats = api("GET", "/landing/logs/source-stats?page_id=%d" % PID, tok=TOK)
print("source-stats:", st, json.dumps(stats, ensure_ascii=False)[:300])

# ───────────────────────── M6 防护 ─────────────────────────
section("M6. protection")
# ① 爬虫 UA -> 拦截(302 block_target)，且 block 事件不记录（crawler 噪音跳过）
st_c, _, loc_c = pub(HOST, "/a/%s?ad=%s" % (SLUG, AD), ua=UA_FB)
blocked_crawler = st_c == 302 and (loc_c or "").startswith(BLOCK_TARGET)
time.sleep(3)
st, logs2 = api("GET", "/landing/logs?page_id=%d&event_type=block&limit=50" % PID, tok=TOK)
crawler_blocks = [i for i in logs2.get("items", []) if "externalhit" in (i.get("user_agent") or "")]
record("M6-crawler", blocked_crawler and not crawler_blocks,
       "FB爬虫UA -> HTTP %s loc=%s | block事件记录数=%d(期望0,爬虫不记)" % (st_c, (loc_c or "")[:50], len(crawler_blocks)))

# ② 真人 UA 命中 query_block -> 拦截 + block 事件记录
st_q, _, loc_q = pub(HOST, "/a/%s?v187block=1&ad=%s" % (SLUG, AD), ua=UA_PC)
blocked_query = st_q == 302 and (loc_q or "").startswith(BLOCK_TARGET)
time.sleep(3)
st, logs3 = api("GET", "/landing/logs?page_id=%d&event_type=block&limit=50" % PID, tok=TOK)
q_blocks = [i for i in logs3.get("items", []) if i.get("reason") == "query_block"]
record("M6-query-block", blocked_query and len(q_blocks) >= 1,
       "query_block -> HTTP %s loc=%s | 事件数=%d reason=%s" % (st_q, (loc_q or "")[:50], len(q_blocks), [i.get("reason") for i in q_blocks[:3]]))

# ③ 根路径防护（直访不带 _d 不带 _pv）
st_rt, _, loc_rt = pub(HOST, "/?v187block=1", ua=UA_PC)
record("M6-root-protect", st_rt == 302 and (loc_rt or "").startswith(BLOCK_TARGET),
       "root /?v187block=1 -> HTTP %s loc=%s" % (st_rt, (loc_rt or "")[:50]))

# ④ 预览 token 跳过防护：爬虫 UA + 正确 _pv -> 不拦（302 到 /?_d=）
st_pv2, _, loc_pv2 = pub(HOST, "/a/%s?ad=%s&_pv=%s" % (SLUG, AD, PV_TOKEN), ua=UA_FB)
record("M6-preview-bypass", st_pv2 == 302 and "_d=" in (loc_pv2 or ""),
       "爬虫UA+_pv -> HTTP %s loc=%s" % (st_pv2, (loc_pv2 or "")[:60]))

# ⑤ 无 UA：观察行为（不判 fail，记录）
st_n, _, loc_n = pub(HOST, "/a/%s?ad=%s" % (SLUG, AD), ua=None)
print("no-UA visit -> HTTP %s loc=%s (desktop 兜底,不拦是 by-design)" % (st_n, (loc_n or "")[:60]))
RESULTS.append(("M6-no-UA", "INFO", "HTTP %s -> %s" % (st_n, "放行" if st_n == 302 and "_d=" in (loc_n or "") else (loc_n or "")[:40])))

# ───────────────────────── M3+M8 自检矩阵 + FB 屏蔽 ─────────────────────────
section("M3/M8. self-check matrix + FB ban probe")
t0 = time.time()
st, health = api("GET", "/landing/pages/%d/health" % PID, timeout=280, tok=TOK)
print("health:", st, "in %.1fs" % (time.time() - t0))
checks = health.get("checks") or []
for c in checks:
    print("  [%s] %-12s %s" % (c.get("status"), c.get("key"), c.get("detail")))
non_pass = {c.get("key"): (c.get("status"), c.get("detail")) for c in checks if c.get("status") != "pass"}
fails = [k for k, (s, _) in non_pass.items() if s == "fail"]
fb_keys = {k: v for k, v in non_pass.items() if k in ("fb_ban", "fb_subcode")}
non_fb_fails = [k for k in fails if k not in ("fb_ban", "fb_subcode")]
record("M3", st == 200 and not non_fb_fails,
       "overall=%s non_pass=%s" % (health.get("overall"), json.dumps(non_pass, ensure_ascii=False)))
if fb_keys:
    RESULTS.append(("M8", "INFO" if all(s != "fail" for s, _ in fb_keys.values()) else "WARN",
                    json.dumps(fb_keys, ensure_ascii=False)))
else:
    record("M8", True, "fb_ban/fb_subcode 均 pass")

# ───────────────────────── M7 编辑→重发布 ─────────────────────────
section("M7. edit + republish")
t0 = time.time()
st, upd = api("PUT", "/landing/pages/%d" % PID, {"title": TITLE2}, timeout=300, tok=TOK)
print("PUT:", st, "in %.1fs" % (time.time() - t0), json.dumps({k: upd.get(k) for k in ("status", "id", "pages_url")}, ensure_ascii=False))
time.sleep(4)
found_new = False
for i in range(6):
    st_u, body_u, _ = pub(HOST, "/", ua=UA_PC)
    found_new = st_u == 200 and TITLE2 in (body_u or "") and TITLE1 not in (body_u or "").replace(TITLE2, "")
    if found_new:
        break
    time.sleep(6)
record("M7", st == 200 and found_new, "PUT=%s 公开页新标题生效=%s (HTTP %s)" % (st, found_new, st_u))

st, pages = api("GET", "/landing/pages", tok=TOK)
v187_pages = [p for p in pages if "_verify187" in (p.get("title") or "")]
record("M7b", len(v187_pages) == 1 and v187_pages[0].get("id") == PID and v187_pages[0].get("title") == TITLE2,
       "列表仅1个 _verify187 页: %s" % [(p.get("id"), p.get("title")) for p in v187_pages])

# ───────────────────────── M9 删除清理 ─────────────────────────
section("M9. delete + cleanup")
st, dele = api("DELETE", "/landing/pages/%d" % PID, tok=TOK)
print("DELETE page:", st, json.dumps(dele, ensure_ascii=False))
st, pages2 = api("GET", "/landing/pages", tok=TOK)
still = [p for p in pages2 if p.get("id") == PID]
record("M9-archive", st == 200 and not still, "DELETE=%s 列表已移除=%s" % (st, not still))

# 子码/日志保留行为
st, sub_after = api("GET", "/subcodes?page_id=%d" % PID, tok=TOK)
st, logs_after = api("GET", "/landing/logs?page_id=%d&limit=5" % PID, tok=TOK)
record("M9-retain", len(sub_after.get("items", [])) >= 1 and logs_after.get("total", 0) >= 1,
       "删页后子码保留=%d条 日志保留=%d条(by-design历史保留)" % (len(sub_after.get("items", [])), logs_after.get("total")))

# 归档页的 /a/ 仍可路由（worker 未解绑 + DB 行保留）——记录行为
st_a, _, loc_a = pub(HOST, "/a/%s?ad=%s" % (SLUG, AD), ua=UA_PC)
RESULTS.append(("M9-archived-route", "INFO",
                "归档后 /a/ -> HTTP %s %s (worker+DB 未解绑, by-design)" % (st_a, "仍路由" if st_a == 302 and "_d=" in (loc_a or "") else (loc_a or "")[:40])))

# 清理：硬删测试子码
st, ds = api("DELETE", "/subcodes/%d?hard=1" % SID, tok=TOK)
print("hard-delete subcode:", st, json.dumps(ds, ensure_ascii=False))
st, sub_check = api("GET", "/subcodes?page_id=%d&status=deleted" % PID, tok=TOK)
record("M9-cleanup", st == 200, "测试子码硬删=%s (deleted 列表 %d 条)" % (ds.get("status") == "deleted", len(sub_check.get("items", []))))

# ───────────────────────── M2 补测：自定义子域名 SSL 传播终检 ─────────────────────────
if PUB_HOST and st_cd != 200:
    section("M2-recheck. custom domain after warm-up")
    time.sleep(20)
    st_cd2, body_cd2, _ = fetch_root_with_retry(PUB_HOST, tries=4, delay=10)
    RESULTS.append(("M2-custom-domain-recheck", "PASS" if (st_cd2 == 200) else "INFO",
                    "https://%s/ HTTP %s (CF 新子域 SSL/DNS 传播)" % (PUB_HOST, st_cd2)))

# ───────────────────────── 总结 ─────────────────────────
section("SUMMARY")
for item, s, note in RESULTS:
    print("%-22s %-5s %s" % (item, s, note[:120]))
n_fail = sum(1 for _, s, _ in RESULTS if s == "FAIL")
print("\nFAIL 数:", n_fail)
