# 批次II smoke（断言式，遵循 bare-except-silent-failure 铁律）：P1 资金与断层——
# 出价双管道剥离(美分不覆盖本币换算)/AI随机文案不覆盖手填/落地URL跟随(public_url回退链+
# 部署实时base+死链禁兜底)/TT三级像素动态解析/optimization_goal 422 兜底。
# 全部 in-process 直调函数（加载的是磁盘上的新代码）——不依赖服务重启、零 HTTP 副作用、
# 不真部署 FB 广告；DB 断言用真实行 + 末尾清理（同批次I口径）。
import json
import sys
from types import SimpleNamespace

FAILS = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f" | {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


# ═══ 1. 出价双管道剥离（G2②，资金安全）═══
from app.routers.launch_templates import _strip_adv_bid
_adv = {"bid_amount": "500", "attribution_spec": [{"window_days": 7}], "is_dynamic_creative": True}
_stripped = _strip_adv_bid(_adv, 12345)
check("strip: bid_amount 剥离", "bid_amount" not in _stripped, str(_stripped))
check("strip: 其余 adv 键保留", _stripped.get("attribution_spec") == [{"window_days": 7}]
      and _stripped.get("is_dynamic_creative") is True)
check("strip: 不动调用方 dict（跨 item 共享）", "bid_amount" in _adv)
check("strip: bid_fb=None 时原样直通（旧行为）", _strip_adv_bid(_adv, None) is _adv)
check("strip: adv 无 bid_amount 时原对象直通", _strip_adv_bid({"attribution_spec": []}, 999) == {"attribution_spec": []})
check("strip: None adv 安全", _strip_adv_bid(None, 999) is None)

# build_adset 语义基线：未剥离的 extra 仍会覆盖 bid_amount 形参（这就是 G2② 的根因），
# 剥离后换算值生效——证明修复靠的是部署链统一过 _strip_adv_bid
from app.core.ad_builder import build_adset
_base = dict(name="g", campaign_id="c1", daily_budget=1500, objective="OUTCOME_SALES",
             conversion_goal="", page_id="111", pixel_id="999",
             landing_url="https://lp.example.com/x", bid_strategy="LOWEST_COST_WITHOUT_CAP",
             budget_mode="ABO", optimization_goal="OFFSITE_CONVERSIONS")
_p_raw = build_adset(**_base, extra={"bid_amount": "500"}, bid_amount=12345)
check("基线复现：未剥离时 adv.bid_amount(美分原始值)覆盖换算值", _p_raw.get("bid_amount") == "500",
      str(_p_raw.get("bid_amount")))
_p_fix = build_adset(**_base, extra=_strip_adv_bid({"bid_amount": "500"}, 12345), bid_amount=12345)
check("修复后：bid_amount=本币换算值", _p_fix.get("bid_amount") == "12345", str(_p_fix.get("bid_amount")))

# deploy_one_account 端到端（fake FB）：平铺/批量/重试三链共用的单点剥离
class _FakeFb:
    def __init__(self):
        self.posts = []

    def post(self, path, payload=None):
        self.posts.append((path, payload or {}))
        return {"id": f"fake_{len(self.posts)}"}

    def get(self, path, params=None):
        return {}


from app.core.ad_ops import deploy_one_account
_fb = _FakeFb()
_link = SimpleNamespace()
_adv_shared = {"bid_amount": "500", "attribution_spec": [{"event_type": "OMNI_PURCHASE", "window_days": 7}]}
_r = deploy_one_account(
    _fb, act_id="act_123", objective="OUTCOME_SALES", conversion_goal="",
    page_id="111", pixel_id="999", landing_url="https://lp.example.com/x",
    daily_budget=1500, budget_mode="ABO", bid_strategy="LOWEST_COST_WITHOUT_CAP",
    name_prefix="SmokeII", headline="h", body="b", cta_type="SHOP_NOW", image_hash="HASHX",
    subcode_slug="smokeii", subcode_link=_link,
    optimization_goal="OFFSITE_CONVERSIONS",
    advanced_config=_adv_shared,
    bid_amount=12345, special_ad_categories=[])
_adset_payload = next(p for path, p in _fb.posts if path.endswith("/adsets"))
check("deploy_one_account: adsets payload bid_amount=换算值(12345)非美分原始(500)",
      _adset_payload.get("bid_amount") == "12345", str(_adset_payload.get("bid_amount")))
check("deploy_one_account: adv 其他键(attribution_spec)仍深合并",
      _adset_payload.get("attribution_spec") == [{"event_type": "OMNI_PURCHASE", "window_days": 7}])
check("deploy_one_account: 调用方 advanced_config dict 未被篡改（跨 item 共享）", "bid_amount" in _adv_shared)
_ads_payload = next(p for path, p in _fb.posts if path.endswith("/ads"))
_creative_str = json.dumps(_ads_payload.get("creative") or {})
check("deploy_one_account: effective_url=base/a/{slug}+{{ad.id}} 宏",
      "/a/smokeii?ad=" in _creative_str and "{{ad.id}}" in _creative_str, _creative_str[:120])

# 死链禁兜底（B5 残留）：slug+link 但无可用 landing_url → 快失败，绝不再拼 tovaads.com
from app.core.fb_client import FbApiError
_fb2 = _FakeFb()
_banned = False
try:
    deploy_one_account(
        _fb2, act_id="act_123", objective="OUTCOME_SALES", conversion_goal="",
        page_id="111", pixel_id="999", landing_url="",
        daily_budget=1500, budget_mode="ABO", bid_strategy="LOWEST_COST_WITHOUT_CAP",
        name_prefix="SmokeII", headline="h", body="b", cta_type="SHOP_NOW", image_hash="HASHX",
        subcode_slug="smokeii", subcode_link=SimpleNamespace(),
        optimization_goal="OFFSITE_CONVERSIONS", special_ad_categories=[])
except FbApiError as e:
    _banned = True
    _err = str(e.friendly or e)
    check("死链禁兜底: 报错文案指明缺落地 URL", "落地" in _err, _err[:100])
check("死链禁兜底: 无 base 时 raise（不再 tovaads.com）", _banned)
check("死链禁兜底: 全部 POST payload 无 tovaads.com/a/ 死链",
      all("tovaads.com/a/" not in json.dumps(p) for _, p in _fb2.posts))

# ═══ 2. AI 随机文案不覆盖手填（A3）═══
from app.core.ad_ops import pick_ad_copy
_asset = SimpleNamespace(ai_copy_json=json.dumps(
    {"headlines": ["AI-H1", "AI-H2"], "bodies": ["AI-B1", "AI-B2"]}))
_h, _b = pick_ad_copy(_asset, "手填标题", "手填正文", "模板标题", "模板正文")
check("文案: 手填优先（AI 不覆盖）", _h == "手填标题" and _b == "手填正文", f"{_h}/{_b}")
_h, _b = pick_ad_copy(_asset, "", "  ", "模板标题", "模板正文")
check("文案: 手填空白时 AI 随机填充（模板兜底其后）", _h.startswith("AI-H") and _b.startswith("AI-B"), f"{_h}/{_b}")
_h, _b = pick_ad_copy(None, "", "", "模板标题", "模板正文")
check("文案: 无素材无AI时模板兜底", _h == "模板标题" and _b == "模板正文")
_h, _b = pick_ad_copy(_asset, "手填标题", "", "", "")
check("文案: 仅标题手填时正文仍可用AI", _h == "手填标题" and _b.startswith("AI-B"))

# ═══ 3. 落地页 URL 跟随（B5/B9）═══
from app.routers.landing import _page_to_dict
from app.models.launch import LandingPage
# 3a. public_url 回退链（不落库，纯序列化）：custom_domain > bound_subdomains[0] > pages.dev
_p1 = SimpleNamespace(id=880001, title="t", custom_domain="https://lp880001.a.com", custom_domains=None,
                      bound_subdomains=None, target_urls=None, rotation_mode="first", pixel_ids=None,
                      tt_pixel_ids=None, pixel_id=None, conversion_event=None, conversion_events=None,
                      tt_conversion_events=None, redirect_mode="display", block_enabled=False,
                      preview_enabled=False, preview_token="tok", subdomain_prefix="",
                      dedup_enabled=False, dedup_window_hours=24, protection_rules=None,
                      ingest_secret="s", template_id=None, status="published",
                      created_at=None, last_health_status=None, last_health_summary=None,
                      last_health_checked_at=None, last_fb_status=None, last_fb_checked_at=None)
_d1 = _page_to_dict(_p1)
check("public_url: custom_domain 直接用", _d1["public_url"] == "https://lp880001.a.com", _d1["public_url"])
_p2 = SimpleNamespace(**{**_p1.__dict__, "id": 880002, "custom_domain": None,
                        "bound_subdomains": json.dumps(["lp880002.b.com", "old.c.com"])})
check("public_url: 无自定义域回退绑定子域名", _page_to_dict(_p2)["public_url"] == "https://lp880002.b.com",
      _page_to_dict(_p2)["public_url"])
_p3 = SimpleNamespace(**{**_p1.__dict__, "id": 880003, "custom_domain": None,
                        "bound_subdomains": None, "custom_domains": None})
check("public_url: 全无时回退 pages.dev（不再空串）",
      _page_to_dict(_p3)["public_url"] == "https://tovaads-landing-880003.pages.dev",
      _page_to_dict(_p3)["public_url"])

# 3b-3d 用真实 DB 行（创建→断言→清理）
from app.core.database import SuperSessionLocal
from app.models.landing_lib import LandingPixel
from app.models.ads_cache import AdsCache
from app.models.launch_template import LaunchTemplate
from app.routers.launch_templates import _resolve_landing_base, _preflight_tree_fb, TemplateIn, PreflightIn
from app.routers.landing_events import _resolve_tt_pixel_ids
from sqlalchemy import text as _t

_db = SuperSessionLocal()
_created_ids = {"page": [], "pixel": [], "cache": [], "tpl": []}
try:
    row = _db.execute(_t("SELECT act_id FROM accounts WHERE tenant_id=1 AND is_managed=true "
                         "AND platform='fb' AND act_id<>'' ORDER BY id LIMIT 1")).first()
    ACT = row[0]
    TENANT = 1

    # 3b. _resolve_landing_base：无自定义域页 → pages.dev base（部署可用，非空）
    lp = LandingPage(tenant_id=TENANT, title="SMOKE-II-LP", status="published",
                     redirect_mode="display", tt_pixel_ids='["CFPAGE9"]')
    _db.add(lp); _db.flush()
    _created_ids["page"].append(lp.id)
    _base, _lprow = _resolve_landing_base(_db, TENANT, lp.id)
    check("resolve base: 无自定义域页回退 pages.dev",
          _base == f"https://tovaads-landing-{lp.id}.pages.dev", str(_base))
    _db.commit()

    # 3c. 树预检 URL 跟随 + 出价镜像（预检=所见即所发）：节点绑落地页 → creative 用页行 base
    # 而非编辑时快照 https://stale.example.com/old；adv.bid_amount 美分值被剥离
    acc = _db.execute(_t("SELECT currency FROM accounts WHERE tenant_id=1 AND act_id=:a"),
                      {"a": ACT}).first()
    from app.models.perf import CurrencyRate
    _cur = (acc[0] if acc else "USD") or "USD"
    _cr = _db.query(CurrencyRate).filter(CurrencyRate.code == _cur.upper()).first()
    from app.core.ad_ops import usd_to_fb_amount
    _exp_bid = usd_to_fb_amount(0.5, _cur, _cr.rate if _cr else 1.0)

    tpl = LaunchTemplate(tenant_id=TENANT, name="SMOKE-II", platform="fb",
                         objective="OUTCOME_SALES", budget_mode="ABO",
                         bid_strategy="LOWEST_COST_WITHOUT_CAP", budget_usd=5,
                         pixel_id="999", landing_page_id=lp.id,
                         landing_url="https://stale.example.com/old",
                         bid_amount_usd=0.5,
                         advanced_config=json.dumps({"bid_amount": "500"}),
                         structure=json.dumps({"adsets": [{
                             "key": "g1", "name": "G1", "enabled": True, "budget_usd": 5,
                             "ads": [{"key": "a1", "name": "A1", "enabled": True,
                                      "landing_page_id": lp.id,
                                      "landing_url": "https://stale.example.com/old",
                                      "asset_ids": []}]}]}))
    _db.add(tpl); _db.flush()
    _created_ids["tpl"].append(tpl.id)
    _db.commit()
    _struct = json.loads(tpl.structure)["adsets"]
    _pf = _preflight_tree_fb(_db, tpl, _struct, PreflightIn(act_id=ACT, pixel_id="999"), TENANT)
    _creative_str = json.dumps(_pf.get("creative") or {}, ensure_ascii=False)
    check("树预检: creative URL=页行实时 base（pages.dev）", f"tovaads-landing-{lp.id}.pages.dev" in _creative_str,
          _creative_str[:160])
    check("树预检: 不再用编辑时快照 URL", "stale.example.com" not in _creative_str)
    check("树预检: adset bid_amount=换算值（镜像部署 runner）",
          (_pf.get("adset") or {}).get("bid_amount") == str(_exp_bid),
          f"{(_pf.get('adset') or {}).get('bid_amount')} vs {_exp_bid}")

    # 3d. TT 三级像素（B6）：ads_cache 反查 act > 显式 act > 页级；fb 像素不串台
    pix1 = LandingPixel(tenant_id=TENANT, pixel_id="CFACT1", platform="tt",
                        act_id="act_smoke_ii_tt_1", status="active")
    pix2 = LandingPixel(tenant_id=TENANT, pixel_id="CFACT2", platform="tt",
                        act_id="act_smoke_ii_tt_2", status="active")
    pix_fb = LandingPixel(tenant_id=TENANT, pixel_id="999888", platform="fb",
                          act_id="act_smoke_ii_tt_3", status="active")
    _db.add_all([pix1, pix2, pix_fb]); _db.flush()
    _created_ids["pixel"] += [pix1.id, pix2.id, pix_fb.id]
    cache = AdsCache(tenant_id=TENANT, act_id="act_smoke_ii_tt_2", platform="fb",
                     ads_json=json.dumps([{"id": "990002", "adset_id": "77"}]))
    _db.add(cache); _db.flush()
    _created_ids["cache"].append(cache.id)
    _db.commit()
    check("TT像素: 显式 act 命中账户级 tt 像素",
          _resolve_tt_pixel_ids(_db, lp, None, "", "act_smoke_ii_tt_1") == ["CFACT1"])
    check("TT像素: ads_cache 反查广告所在账户优先于页级",
          _resolve_tt_pixel_ids(_db, lp, None, "990002", "") == ["CFACT2"],
          str(_resolve_tt_pixel_ids(_db, lp, None, "990002", "")))
    check("TT像素: link.act_id 候选（第三级）",
          _resolve_tt_pixel_ids(_db, lp, SimpleNamespace(act_id="act_smoke_ii_tt_1"), "", "") == ["CFACT1"])
    check("TT像素: 无账户命中回退页级 tt_pixel_ids",
          _resolve_tt_pixel_ids(_db, lp, None, "", "") == ["CFPAGE9"],
          str(_resolve_tt_pixel_ids(_db, lp, None, "", "")))
    check("TT像素: 同 act 的 fb 像素不串进 TT 解析",
          _resolve_tt_pixel_ids(_db, lp, None, "", "act_smoke_ii_tt_3") == ["CFPAGE9"])
finally:
    # 清理（真实生产库，测试行全部回收）
    try:
        for pid in _created_ids["pixel"]:
            _db.query(LandingPixel).filter(LandingPixel.id == pid).delete()
        for cid in _created_ids["cache"]:
            _db.query(AdsCache).filter(AdsCache.id == cid).delete()
        for tid in _created_ids["tpl"]:
            _db.query(LaunchTemplate).filter(LaunchTemplate.id == tid).delete()
        for pgid in _created_ids["page"]:
            _db.query(LandingPage).filter(LandingPage.id == pgid).delete()
        _db.commit()
        print("cleanup done")
    except Exception as e:
        print(f"CLEANUP FAIL: {e}")
        FAILS.append("cleanup")
    _db.close()

# ═══ 4. optimization_goal 422 兜底（C4 残留侧）═══
import pydantic
try:
    TemplateIn(name="SMOKE-II", objective="OUTCOME_TRAFFIC", optimization_goal="VALUE")
    check("og 兜底: TRAFFIC+VALUE 应被拒", False, "未抛 ValidationError")
except pydantic.ValidationError as e:
    _msg = str(e)
    check("og 兜底: TRAFFIC+VALUE 被 422 拒", "不兼容" in _msg, _msg[:120])
    check("og 兜底: detail 带可用清单", "可用" in _msg and "LINK_CLICKS" in _msg, _msg[:200])
try:
    _ok = TemplateIn(name="SMOKE-II", objective="OUTCOME_SALES",
                     optimization_goal="OFFSITE_CONVERSIONS", structure="")
    check("og 兜底: 合法组合照常通过", _ok.optimization_goal == "OFFSITE_CONVERSIONS")
except pydantic.ValidationError as e:
    check("og 兜底: 合法组合照常通过", False, str(e)[:120])
# 组级覆盖回归（批次I 已有，此处防回归）：structure 内组 og 非法仍拦
_bad_struct = json.dumps({"adsets": [{"name": "坏组", "ads": [{"name": "a"}],
                                      "optimization_goal": "VALUE"}]})
try:
    TemplateIn(name="SMOKE-II", objective="OUTCOME_TRAFFIC", structure=_bad_struct)
    check("og 兜底: 组级非法 og 仍被拦（防回归）", False, "未抛 ValidationError")
except pydantic.ValidationError as e:
    check("og 兜底: 组级非法 og 仍被拦（防回归）", "坏组" in str(e) and "不兼容" in str(e), str(e)[:150])

print()
print(f"{'ALL PASS' if not FAILS else 'FAILURES: ' + ', '.join(FAILS)} ({len(FAILS)} fail)")
sys.exit(1 if FAILS else 0)
