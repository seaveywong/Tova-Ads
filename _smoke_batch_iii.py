# 批次III smoke（断言式，遵循 bare-except-silent-failure 铁律）：清理与低频补齐——
# 细分版位(白名单/校验/build_adset targeting/树预检透出)/redirect 模式 fire 像素(worker 桥页
# node 实跑)/TT event_id(浏览器 track 带 id + route_next 同 UUID 进 S2S)/link.ad_id last-wins 守卫。
# 全部 in-process 直调（加载磁盘新代码）+ node 子进程跑 worker——零真部署、零 CF 副作用；
# DB 断言用真实行 + 末尾清理（批次I/II 同口径）。
import json
import subprocess
import sys
import tempfile
import time
import uuid as _uuid
from types import SimpleNamespace

FAILS = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f" | {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


# ═══ 1. 细分版位：_validate_structure 白名单 + 校验 + 归一 ═══
import pydantic
from app.routers.launch_templates import TemplateIn, _PLACEMENT_POSITIONS, _node_placements
from app.core.ad_builder import build_adset

def _struct(group_over: dict) -> str:
    g = {"name": "G1", "ads": [{"name": "a1"}], "placement_mode": "manual",
         "publisher_platforms": ["facebook", "instagram"], "device_platforms": ["mobile"]}
    g.update(group_over)
    return json.dumps({"adsets": [g]})

# 1a. 合法：facebook/instagram 各勾细分位置 → 规范化保留
ok = TemplateIn(name="SMOKE-III", objective="OUTCOME_SALES", budget_usd=15, structure=_struct({
    "facebook_positions": ["feed", "facebook_reels", "feed"],   # 重复值应去重
    "instagram_positions": ["stream"],
    "messenger_positions": [],                                   # 空=省略=该平台全位置
}))
_g = ok.structure and json.loads(ok.structure)["adsets"][0]
check("版位: 合法位置保留+去重", _g["facebook_positions"] == ["feed", "facebook_reels"]
      and _g["instagram_positions"] == ["stream"] and _g["messenger_positions"] == [],
      str(_g.get("facebook_positions")) + "/" + str(_g.get("instagram_positions")))

# 1b. 非法值 → 422 带可用清单
try:
    TemplateIn(name="SMOKE-III", objective="OUTCOME_SALES", budget_usd=15, structure=_struct({
        "facebook_positions": ["feed", "bogus_pos"]}))
    check("版位: 非法位置被拒", False, "未抛 ValidationError")
except pydantic.ValidationError as e:
    check("版位: 非法位置被拒+带清单", "bogus_pos" in str(e) and "facebook_reels" in str(e), str(e)[:120])

# 1c. 位置给了但平台未勾 → 矛盾组合拒绝
try:
    TemplateIn(name="SMOKE-III", objective="OUTCOME_SALES", budget_usd=15, structure=json.dumps({"adsets": [{
        "name": "G1", "ads": [{"name": "a1"}], "placement_mode": "manual",
        "publisher_platforms": ["instagram"], "facebook_positions": ["feed"]}]}))
    check("版位: 平台未勾但给了位置被拒", False, "未抛 ValidationError")
except pydantic.ValidationError as e:
    check("版位: 平台未勾但给了位置被拒", "未勾选 facebook" in str(e), str(e)[:120])

# 1d. auto 模式残留位置清空（Advantage+ 省略全部版位键）
ok2 = TemplateIn(name="SMOKE-III", objective="OUTCOME_SALES", budget_usd=15, structure=json.dumps({"adsets": [{
    "name": "G1", "ads": [{"name": "a1"}], "placement_mode": "auto",
    "publisher_platforms": ["facebook"], "facebook_positions": ["feed"] }]}))
_g2 = json.loads(ok2.structure)["adsets"][0]
check("版位: auto 模式清残留位置", _g2["facebook_positions"] == [] and _g2["publisher_platforms"] == [])

# 1e. _node_placements：平台勾了才带位置键；空数组=省略（该平台全位置）
_np = _node_placements({"placement_mode": "manual", "publisher_platforms": ["facebook"],
                        "device_platforms": [], "facebook_positions": ["feed"],
                        "instagram_positions": ["stream"], "messenger_positions": ["story"]})
check("版位: _node_placements 只带已勾平台的位置",
      _np.get("facebook_positions") == ["feed"] and "instagram_positions" not in _np
      and "messenger_positions" not in _np, str(_np))

# 1f. build_adset：位置进 targeting（extra 深合并前）
_pa = build_adset(name="g", campaign_id="c1", daily_budget=1500, objective="OUTCOME_SALES",
                  conversion_goal="", page_id="111", pixel_id="9999",
                  landing_url="https://lp.example.com/x",
                  bid_strategy="LOWEST_COST_WITHOUT_CAP", budget_mode="ABO",
                  placements={"publisher_platforms": ["facebook", "messenger"],
                              "facebook_positions": ["feed"], "messenger_positions": ["sponsored_messages"]})
_tg = _pa["targeting"]
check("版位: build_adset targeting 带位置键",
      _tg.get("facebook_positions") == ["feed"] and _tg.get("messenger_positions") == ["sponsored_messages"],
      str({k: v for k, v in _tg.items() if k.endswith("_positions")}))
_pb = build_adset(name="g", campaign_id="c1", daily_budget=1500, objective="OUTCOME_SALES",
                  conversion_goal="", page_id="111", pixel_id="9999",
                  landing_url="https://lp.example.com/x",
                  bid_strategy="LOWEST_COST_WITHOUT_CAP", budget_mode="ABO",
                  placements={"publisher_platforms": ["facebook"]})
check("版位: 省略位置=不带位置键（该平台全位置）",
      not any(k.endswith("_positions") for k in _pb["targeting"]),
      str(list(_pb["targeting"].keys())))

# 1g. 树预检透出（真实 DB 行：模板+受管账户 → _preflight_tree_fb 直调）
from app.core.database import SuperSessionLocal as _S
from app.models.launch_template import LaunchTemplate
from app.models.launch import LandingPage
from app.models.auth import User
from sqlalchemy import text as _t
_db = _S()
TPL_ID = None
try:
    _u = _db.query(User).filter(User.email == "seavey@tovaads.com").first()
    row = _db.execute(_t("SELECT act_id FROM accounts WHERE tenant_id=1 AND is_managed=true "
                         "AND platform='fb' AND act_id<>'' ORDER BY id LIMIT 1")).first()
    ACT = row[0]
    _tpl = LaunchTemplate(tenant_id=1, name="SMOKE-III-PF", platform="fb", objective="OUTCOME_SALES",
                          budget_mode="ABO", bid_strategy="LOWEST_COST_WITHOUT_CAP",
                          budget_usd=15, name_prefix="SmokeIII", landing_url="https://example.com/lp",
                          pixel_id="9999", page_id="111",
                          structure=json.dumps({"adsets": [{
                              "key": "g1", "name": "G1", "enabled": False, "budget_usd": 2,
                              "conv_location": "website",
                              "placement_mode": "manual", "publisher_platforms": ["facebook"],
                              "device_platforms": ["mobile"], "facebook_positions": ["feed"],
                              "ads": [{"key": "a1", "name": "a1", "headline": "h", "body": "b",
                                       "cta_type": "SHOP_NOW"}]}]}))
    _db.add(_tpl)
    _db.flush()
    TPL_ID = _tpl.id
    _db.commit()
    from app.routers.launch_templates import _preflight_tree_fb, PreflightIn
    pf = _preflight_tree_fb(_db, _tpl, json.loads(_tpl.structure)["adsets"],
                            PreflightIn(act_id=ACT, pixel_id="9999"), 1)
    _tree0 = (pf.get("tree") or [{}])[0]
    check("树预检: tree 概览透出细分位置",
          _tree0.get("facebook_positions") == ["feed"] and _tree0.get("conv_location") == "website",
          str({k: _tree0.get(k) for k in ("facebook_positions", "conv_location")}))
    _pf_tg = ((pf.get("adset") or {}).get("targeting") or {})
    check("树预检: adset payload targeting 带 facebook_positions",
          _pf_tg.get("facebook_positions") == ["feed"] and _pf_tg.get("publisher_platforms") == ["facebook"],
          str({k: _pf_tg.get(k) for k in ("facebook_positions", "publisher_platforms")}))
    check("树预检: 全 PAUSED → will_spend 空", pf.get("will_spend") == [], str(pf.get("will_spend")))
finally:
    try:
        if TPL_ID:
            _db.query(LaunchTemplate).filter(LaunchTemplate.id == TPL_ID).delete()
            _db.commit()
    except Exception as e:
        print(f"CLEANUP FAIL(pf): {e}")
        FAILS.append("cleanup_pf")

# ═══ 2. redirect 模式 fire 像素（B11）：worker 桥页 node 实跑 ═══
from app.routers.landing import WORKER_SOURCE

def _build_worker(cfg: dict) -> str:
    return "const LP_CONFIG = " + json.dumps(cfg) + ";\n" + WORKER_SOURCE

_RD_CFG = {
    "secret": "sk_test_iii", "target": "https://example.com/offer",
    "redirect_mode": "redirect",
    "pixel_ids": ["111222333"], "tt_pixel_ids": ["CFTT1"],
    "conversion_events": ["Purchase"], "tt_conversion_events": ["CompletePayment"],
    "block_enabled": False, "rules": {}, "preview_enabled": False, "preview_token": "",
}
_HARNESS = r"""
const path = process.argv[2]; const expectMode = process.argv[3];
let worker; try { worker = (await import('file://' + path)).default } catch (e) { console.error('IMPORT_ERR:' + e.message); process.exit(2) }
globalThis.fetch = async (url, opts) => {
  const u = typeof url === 'string' ? url : (url && url.url) || '';
  if (u.includes('/router/next')) return new Response(JSON.stringify({pixel_ids:[],target_url:'https://example.com/x',conversion_events:[]}),{status:200,headers:{'Content-Type':'application/json'}});
  return new Response('{"ok":true}', {status:200});
};
const env = { ASSETS: { fetch: async () => new Response('assets', {status:200}) } };
const ctx = { waitUntil: (p) => { try { if (p && p.catch) p.catch(()=>{}) } catch(e){} } };
const resp = await worker.fetch(new Request('https://example.com/a/rdtest?ad=123&utm_src=smoke', {headers:{'user-agent':'Mozilla/5.0 (Linux; Android 10) Chrome/120 Mobile','cf-connecting-ip':'1.2.3.4'}}), env, ctx);
const out = {status: resp.status, ctype: (resp.headers.get('content-type')||''), location: (resp.headers.get('location')||''), body: '' };
if (expectMode === 'redirect') out.body = await resp.text();
console.log('RESULT:' + JSON.stringify(out));
process.exit(0);
"""
with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False, encoding="utf-8") as _f:
    _f.write(_build_worker(_RD_CFG))
    _rd_worker = _f.name
with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False, encoding="utf-8") as _f:
    _f.write(_HARNESS)
    _harness = _f.name
try:
    # 语法门（与发布门同口径）
    _r0 = subprocess.run(["node", "--check", _rd_worker], capture_output=True, text=True, timeout=20)
    check("redirect worker: node --check 语法过", _r0.returncode == 0, _r0.stderr[:150])
    _r = subprocess.run(["node", _harness, _rd_worker, "redirect"], capture_output=True, text=True, timeout=30)
    _out = {}
    for _ln in (_r.stdout or "").splitlines():
        if _ln.startswith("RESULT:"):
            _out = json.loads(_ln[7:])
    check("redirect worker: 返回 200 HTML 桥页（不再是裸 302）",
          _out.get("status") == 200 and "text/html" in str(_out.get("ctype")), str(_out)[:150])
    _body = _out.get("body") or ""
    check("redirect worker: FB 像素+PageView+转化事件注入",
          "111222333" in _body and "PageView" in _body and "Purchase" in _body)
    check("redirect worker: TT 像素+转化事件注入（同口径）",
          "CFTT1" in _body and "CompletePayment" in _body)
    check("redirect worker: 跳转不阻塞（300ms location.replace + meta refresh + 可见链接）",
          "location.replace" in _body and "http-equiv=\"refresh\"" in _body and "id=\"cta\"" in _body)
    check("redirect worker: 目标带合并 query（utm_src 透传）", "utm_src=smoke" in _body)
    # display 模式回归：仍走 route_next → 302 /?_d=
    _dp = dict(_RD_CFG, redirect_mode="display")
    with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False, encoding="utf-8") as _f2:
        _f2.write(_build_worker(_dp))
        _dp_worker = _f2.name
    _r2 = subprocess.run(["node", _harness, _dp_worker, "display"], capture_output=True, text=True, timeout=30)
    _out2 = {}
    for _ln in (_r2.stdout or "").splitlines():
        if _ln.startswith("RESULT:"):
            _out2 = json.loads(_ln[7:])
    check("display 回归: 仍 302 到 /?_d= 桥（route_next 链不动）",
          _out2.get("status") in (301, 302) and "_d=" in str(_out2.get("location")), str(_out2)[:150])
finally:
    import os as _os
    for _p in (_rd_worker, _harness, _dp_worker if "_dp_worker" in dir() else None):
        try:
            if _p:
                _os.unlink(_p)
        except Exception:
            pass

# ═══ 3. TT event_id（B8 收口）：浏览器 track 带 id + route_next 同 UUID 进 S2S ═══
import inspect as _insp
from app.routers import landing as _landing
check("TT event_id: 默认页模板 trackConversion TT 分支带 event_id",
      "ttq.track(evt,_eid?{event_id:_eid}" in _landing.LANDING_TEMPLATE)
check("TT event_id: _d 注入脚本（_d_decode_tt）带 event_id（回归）",
      "event_id:_eid" in _insp.getsource(_landing._do_publish))
check("TT event_id: worker _d 注 eid 契约（回归）", "eid:(rd.tt_event_id" in _landing.WORKER_SOURCE)

# route_next 同 UUID 进 S2S + FB CAPI（monkeypatch 捕获，dry_run=False 但不打网络）
from app.routers import landing_events as _le
from app.models.landing_lib import LandingPixel
_PAGE_ID = None
try:
    _lp = LandingPage(tenant_id=1, title="SMOKE-III-TT", status="published",
                      target_urls=json.dumps(["https://example.com/t"]), pixel_ids=json.dumps(["8888"]),
                      tt_pixel_ids=json.dumps(["CFTT1"]), tt_conversion_events=json.dumps(["CompletePayment"]),
                      conversion_events=json.dumps(["Purchase"]), redirect_mode="display",
                      ingest_secret="sk_smoke_iii_tt")
    _db.add(_lp)
    _db.flush()
    _PAGE_ID = _lp.id
    _px_fb = LandingPixel(tenant_id=1, act_id="act_smoke_iii", pixel_id="8888",
                          platform="fb", status="active", fb_capi_enabled=True)
    _db.add(_px_fb)
    _db.commit()
    _cap = {}
    _orig_tt = _le.send_tt_s2s_for_visit if hasattr(_le, "send_tt_s2s_for_visit") else None
    import app.core.tk_events as _tke
    _tke_send = _tke.send_tt_s2s_for_visit
    _tke_fb = _tke.send_fb_capi_for_visit

    def _fake_tt(db, tenant_id, pixel_ids, events, event_id, **kw):
        _cap["tt"] = {"pixels": list(pixel_ids), "events": list(events), "eid": event_id}

    def _fake_fb(db, tenant_id, pixel_ids, events, event_id, **kw):
        _cap["fb"] = {"pixels": list(pixel_ids), "events": list(events), "eid": event_id}
    # route_next 内部 from ..core.tk_events import ... 局部导入 → patch 模块属性即可
    _tke.send_tt_s2s_for_visit = _fake_tt
    _tke.send_fb_capi_for_visit = _fake_fb
    try:
        _rn = _le.route_next(_le.RouteNextIn(secret="sk_smoke_iii_tt", slug="", ad_id="", act_id=""))
        _eid = _rn.get("tt_event_id") or ""
        check("TT event_id: route_next 生成 UUID（TT 像素在即生成）",
              bool(_eid) and len(_eid.split("-")) == 5, _eid)
        check("TT event_id: TT S2S 收到同一 event_id",
              _cap.get("tt", {}).get("eid") == _eid and _cap["tt"]["pixels"] == ["CFTT1"]
              and _cap["tt"]["events"] == ["CompletePayment"], str(_cap.get("tt")))
        check("TT event_id: FB CAPI 收到同一 UUID（跨平台共用、各平台各自去重）",
              _cap.get("fb", {}).get("eid") == _eid and _cap["fb"]["pixels"] == ["8888"], str(_cap.get("fb")))
    finally:
        _tke.send_tt_s2s_for_visit = _tke_send
        _tke.send_fb_capi_for_visit = _tke_fb
finally:
    try:
        _db.query(LandingPixel).filter(LandingPixel.act_id == "act_smoke_iii").delete(synchronize_session=False)
        if _PAGE_ID:
            _db.query(LandingPage).filter(LandingPage.id == _PAGE_ID).delete()
        _db.commit()
    except Exception as e:
        print(f"CLEANUP FAIL(tt): {e}")
        FAILS.append("cleanup_tt")

# ═══ 4. link.ad_id last-wins 守卫（B7 收口）═══
from app.core.ad_ops import bind_link_ad_id
_lk = SimpleNamespace(ad_id="", status="reserved")
check("last-wins: 空链接首绑成功", bind_link_ad_id(_lk, "111") is True and _lk.ad_id == "111"
      and _lk.status == "active")
check("last-wins: 同 ad_id 重绑（重试/重部署）照常", bind_link_ad_id(_lk, "111") is True)
check("last-wins: 不同 ad_id 不覆盖（1:1 台账保住）",
      bind_link_ad_id(_lk, "222") is False and _lk.ad_id == "111")
check("last-wins: None 链接/空 ad_id 安全", bind_link_ad_id(None, "1") is False
      and bind_link_ad_id(SimpleNamespace(ad_id="", status="reserved"), "") is False)
# 部署调用点已收口（无绕过守卫的直写；bind_link_ad_id 函数体本身除外）
import inspect as _inspect
from app.routers import launch_templates as _lt
import app.core.ad_ops as _ops_mod

def _strip_helper(src: str) -> str:
    """剔除 bind_link_ad_id 函数体（守卫本体的合法直写）。"""
    _i = src.find("def bind_link_ad_id")
    if _i < 0:
        return src
    _j = src.find("\ndef ", _i + 10)
    return src[:_i] + (src[_j + 1:] if _j > 0 else "")
_src_lt = _inspect.getsource(_lt)
_src_ops = _inspect.getsource(_ops_mod)
_bad_lt = [ln.strip()[:90] for ln in _strip_helper(_src_lt).splitlines()
           if ".ad_id = ad_id" in ln and "def " not in ln]
_bad_ops = [ln.strip()[:90] for ln in _strip_helper(_src_ops).splitlines()
            if ".ad_id = ad_id" in ln and "def " not in ln]
check("last-wins: bind_link_ad_id 守卫存在", _i_ok := ("def bind_link_ad_id" in _src_ops))
check("last-wins: 部署链无绕过守卫的直写（树 runner/平铺/TT 全走 bind_link_ad_id）",
      not _bad_lt and not _bad_ops, str(_bad_lt + _bad_ops))
# ingest 首绑路径回归：已绑不同广告的子码不被 ingest 覆盖（并发场景）
_EVID = []
try:
    from app.models.launch import LandingAdLink
    _db.query(LandingAdLink).filter(LandingAdLink.slug.like("smokeiii-%")).delete(synchronize_session=False)
    _lk2 = LandingAdLink(tenant_id=1, slug="smokeiii-lw", act_id="act_smoke_iii_2",
                         page_id=None, status="active", ad_id="111")
    _db.add(_lk2)
    _lp2 = LandingPage(tenant_id=1, title="SMOKE-III-LW", status="published",
                       target_urls=json.dumps(["https://example.com/t2"]), redirect_mode="display",
                       ingest_secret="sk_smoke_iii_lw")
    _db.add(_lp2)
    _db.flush()
    _lk2.page_id = _lp2.id
    _db.commit()
    class _Req:
        headers = {}
    _le.ingest_event(_le.EventIngestIn(secret="sk_smoke_iii_lw", event_type="visit",
                                       slug="smokeiii-lw", ad_id="999"), _Req())
    _db.refresh(_lk2)
    check("last-wins: ingest 首绑不覆盖已绑的不同 ad_id（并发回归）", _lk2.ad_id == "111", str(_lk2.ad_id))
finally:
    try:
        _db.query(LandingAdLink).filter(LandingAdLink.slug == "smokeiii-lw").delete()
        _db.query(LandingPage).filter(LandingPage.ingest_secret == "sk_smoke_iii_lw").delete()
        _db.commit()
        print("cleanup done")
    except Exception as e:
        print(f"CLEANUP FAIL(lw): {e}")
        FAILS.append("cleanup_lw")
    _db.close()

print()
print(f"{'ALL PASS' if not FAILS else 'FAILURES: ' + ', '.join(FAILS)} ({len(FAILS)} fail)")
sys.exit(1 if FAILS else 0)
