# 批次I smoke（断言式，遵循 bare-except-silent-failure 铁律）：FB 对齐——
# 词表归一(custom_event_type 真实生效)/conv_location 校验/版位 payload/WhatsApp promoted_object/
# CBO+lifetime 树排期守卫/自动建链(建/查/回滚清理)/2 个部署 bug 回归/树 smoke 回归。
# 不真部署 FB 广告（预检/CRUD/直调函数均零消耗）；自动建链断言用真实 DB 行 + 末尾清理。
import json, sys
import httpx

BASE = "http://127.0.0.1:8000"
FAILS = []

def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f" | {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)

from app.core.database import SuperSessionLocal as _S
from app.models.auth import User
from app.core.security import create_access_token
_db = _S()
try:
    _u = _db.query(User).filter(User.email == "seavey@tovaads.com").first()
    TOK = create_access_token(user_id=_u.id, email=_u.email, tenant_id=1, role="owner", is_superadmin=_u.is_superadmin)
    from sqlalchemy import text as _t
    row = _db.execute(_t("SELECT act_id FROM accounts WHERE tenant_id=1 AND is_managed=true "
                         "AND platform='fb' AND act_id<>'' ORDER BY id LIMIT 1")).first()
    ACT = row[0]
    # 迁移 0092 落库断言：列 + GRANT
    col = _db.execute(_t("SELECT column_name FROM information_schema.columns "
                         "WHERE table_name='launch_templates' AND column_name='whatsapp_phone_number'")).first()
    check("0092 column launch_templates.whatsapp_phone_number", col is not None)
    grants = _db.execute(_t("SELECT has_table_privilege('toveads_app','launch_templates','UPDATE'), "
                            "has_table_privilege('toveads_super','launch_templates','SELECT')")).fetchone()
    check("0092 GRANT both roles", bool(grants[0]) and bool(grants[1]), str(grants))
finally:
    _db.close()
H = {"Authorization": f"Bearer {TOK}"}

# ═══ 1. 词表归一：conversion_goal（UI 转化事件词表）→ custom_event_type 真实生效 ═══
base = {
    "name": "SMOKE-I", "platform": "fb", "objective": "OUTCOME_SALES",
    "budget_mode": "ABO", "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
    "budget_usd": 15, "name_prefix": "SmokeI",
    "landing_url": "https://example.com/lp",
}
r = httpx.post(f"{BASE}/launch-templates", headers=H,
               json={**base, "conversion_goal": "AddToCart", "pixel_id": "9999"}, timeout=30)
check("create flat SALES + conversion_goal=AddToCart 200", r.status_code == 200, r.text[:150])
TID = r.json().get("id") if r.status_code == 200 else None
if TID:
    r = httpx.post(f"{BASE}/launch-templates/{TID}/preflight", headers=H,
                   json={"act_id": ACT, "pixel_id": "9999"}, timeout=60)
    pf = r.json() if r.status_code == 200 else {}
    check("preflight AddToCart 200", r.status_code == 200, r.text[:150])
    po = ((pf.get("adset") or {}).get("promoted_object") or {})
    check("custom_event_type=ADD_TO_CART（不再恒 PURCHASE）", po.get("custom_event_type") == "ADD_TO_CART", str(po))
    check("pixel carried", po.get("pixel_id") == "9999", str(po))
    check("optimization_goal=OFFSITE_CONVERSIONS", (pf.get("adset") or {}).get("optimization_goal") == "OFFSITE_CONVERSIONS")

    # 旧词表 key（offsite_conversions）兼容归一：目标推断照旧 + 事件回默认 PURCHASE
    httpx.put(f"{BASE}/launch-templates/{TID}", headers=H,
              json={**base, "conversion_goal": "offsite_conversions", "pixel_id": "9999"}, timeout=30)
    r = httpx.post(f"{BASE}/launch-templates/{TID}/preflight", headers=H,
                   json={"act_id": ACT, "pixel_id": "9999"}, timeout=60)
    pf = r.json() if r.status_code == 200 else {}
    po = ((pf.get("adset") or {}).get("promoted_object") or {})
    check("legacy key offsite_conversions → OFFSITE_CONVERSIONS",
          (pf.get("adset") or {}).get("optimization_goal") == "OFFSITE_CONVERSIONS")
    check("legacy key → default PURCHASE", po.get("custom_event_type") == "PURCHASE", str(po))
    # 空值 → 默认 PURCHASE
    httpx.put(f"{BASE}/launch-templates/{TID}", headers=H,
              json={**base, "conversion_goal": "", "pixel_id": "9999"}, timeout=30)
    r = httpx.post(f"{BASE}/launch-templates/{TID}/preflight", headers=H,
                   json={"act_id": ACT, "pixel_id": "9999"}, timeout=60)
    po = ((r.json().get("adset") or {}).get("promoted_object") or {})
    check("empty conversion_goal → PURCHASE", po.get("custom_event_type") == "PURCHASE", str(po))
    httpx.delete(f"{BASE}/launch-templates/{TID}", headers=H, timeout=30)

# ═══ 2. conv_location 校验（保存门 422）+ 树预检 payload 派生 ═══
def _node(**ov):
    n = {"key": "as_1", "name": "组I", "enabled": False, "budget_usd": 10,
         "audience_id": 0, "audience_json": "", "optimization_goal": "", "billing_event": "",
         "advanced_config": "", "conv_location": "", "placement_mode": "",
         "publisher_platforms": [], "device_platforms": [],
         "ads": [{"key": "ad_1", "name": "", "enabled": False, "asset_ids": [], "headline": "",
                  "body": "", "cta_type": "", "ad_language": "", "landing_page_id": 0,
                  "landing_url": "", "subcode_slug": "", "message_template_id": 0,
                  "lead_form_template_id": 0, "pixel_id": "", "post_source": "new",
                  "reuse_post_ref": "", "link_description": ""}]}
    n.update(ov)
    return n

def _tree_tpl(name, objective, node, **ov):
    return {**base, "name": name, "objective": objective,
            "structure": json.dumps({"adsets": [node]}, ensure_ascii=False), **ov}

# 2a. 非法枚举值 → 422
r = httpx.post(f"{BASE}/launch-templates", headers=H,
               json=_tree_tpl("SMOKE-I-loc-bad", "OUTCOME_SALES", _node(conv_location="foo")), timeout=30)
check("reject unknown conv_location", r.status_code == 422 and "转化位置" in r.text, f"{r.status_code} {r.text[:120]}")
# 2b. objective×conv_location 不兼容（AWARENESS 无转化位置）→ 422
r = httpx.post(f"{BASE}/launch-templates", headers=H,
               json=_tree_tpl("SMOKE-I-loc-mis", "OUTCOME_AWARENESS", _node(conv_location="website")), timeout=30)
check("reject conv_location vs objective mismatch", r.status_code == 422 and "不适用" in r.text,
      f"{r.status_code} {r.text[:120]}")
# 2c. 优化目标×objective 不兼容（TRAFFIC 组选 VALUE）→ 422
r = httpx.post(f"{BASE}/launch-templates", headers=H,
               json=_tree_tpl("SMOKE-I-og-mis", "OUTCOME_TRAFFIC", _node(optimization_goal="VALUE")), timeout=30)
check("reject optimization_goal vs objective", r.status_code == 422 and "不兼容" in r.text,
      f"{r.status_code} {r.text[:120]}")
# 2d. conv_location×optimization_goal 交叉不兼容（website 下选 LEAD_GENERATION）→ 422
r = httpx.post(f"{BASE}/launch-templates", headers=H,
               json=_tree_tpl("SMOKE-I-cross", "OUTCOME_SALES",
                              _node(conv_location="website", optimization_goal="LEAD_GENERATION")), timeout=30)
check("reject conv_location x optimization_goal", r.status_code == 422, f"{r.status_code} {r.text[:120]}")

# 2e. 合法 messenger（SALES）→ 200 + 树预检 destination_type=MESSENGER + promoted_object=page
r = httpx.post(f"{BASE}/launch-templates", headers=H,
               json=_tree_tpl("SMOKE-I-msg", "OUTCOME_SALES",
                              _node(conv_location="messenger"), page_id="1122334455"), timeout=30)
check("create tree SALES+messenger 200", r.status_code == 200, r.text[:150])
TID = r.json().get("id") if r.status_code == 200 else None
if TID:
    r = httpx.post(f"{BASE}/launch-templates/{TID}/preflight", headers=H,
                   json={"act_id": ACT, "page_id": "1122334455"}, timeout=60)
    pf = r.json() if r.status_code == 200 else {}
    ad = pf.get("adset") or {}
    check("tree pf messenger 200", r.status_code == 200, r.text[:150])
    check("destination_type=MESSENGER", ad.get("destination_type") == "MESSENGER", str(ad.get("destination_type")))
    check("promoted_object={page_id}", (ad.get("promoted_object") or {}).get("page_id") == "1122334455",
          str(ad.get("promoted_object")))
    check("optimization_goal=MESSAGING_PURCHASE_CONVERSION", ad.get("optimization_goal") == "MESSAGING_PURCHASE_CONVERSION",
          str(ad.get("optimization_goal")))
    check("MESSENGER 版位自动并入 publisher_platforms",
          (ad.get("targeting") or {}).get("publisher_platforms") == ["messenger"],
          str((ad.get("targeting") or {}).get("publisher_platforms")))
    check("tree overview carries conv_location",
          (pf.get("tree") or [{}])[0].get("conv_location") == "messenger")

# ═══ 3. 版位 auto/manual payload 断言（树预检）═══
# 3a. manual：平台+设备进 targeting
r = httpx.put(f"{BASE}/launch-templates/{TID}", headers=H,
              json=_tree_tpl("SMOKE-I-msg", "OUTCOME_SALES",
                             _node(conv_location="messenger", placement_mode="manual",
                                   publisher_platforms=["facebook", "messenger"],
                                   device_platforms=["mobile"]), page_id="1122334455"), timeout=30)
check("update tree manual placements 200", r.status_code == 200, r.text[:150])
r = httpx.post(f"{BASE}/launch-templates/{TID}/preflight", headers=H,
               json={"act_id": ACT, "page_id": "1122334455"}, timeout=60)
ad = (r.json().get("adset") or {}) if r.status_code == 200 else {}
tg = ad.get("targeting") or {}
check("manual publisher_platforms carried", tg.get("publisher_platforms") == ["facebook", "messenger"],
      str(tg.get("publisher_platforms")))
check("manual device_platforms carried", tg.get("device_platforms") == ["mobile"], str(tg.get("device_platforms")))
# 3b. auto（placement_mode 空）= 省略全部版位键（非消息目的地）
r = httpx.put(f"{BASE}/launch-templates/{TID}", headers=H,
              json=_tree_tpl("SMOKE-I-msg", "OUTCOME_TRAFFIC",
                             _node(conv_location="website", placement_mode="auto",
                                   publisher_platforms=[], device_platforms=[]),
                             page_id="1122334455"), timeout=30)
check("update tree auto placements 200", r.status_code == 200, r.text[:150])
r = httpx.post(f"{BASE}/launch-templates/{TID}/preflight", headers=H,
               json={"act_id": ACT, "page_id": "1122334455"}, timeout=60)
tg = ((r.json().get("adset") or {}).get("targeting") or {})
check("auto placement = omit keys", "publisher_platforms" not in tg and "device_platforms" not in tg,
      str(sorted(k for k in tg if "platform" in k)))
# 3c. manual 但空平台 → 422
r = httpx.post(f"{BASE}/launch-templates", headers=H,
               json=_tree_tpl("SMOKE-I-manual-empty", "OUTCOME_TRAFFIC",
                              _node(placement_mode="manual", publisher_platforms=[])), timeout=30)
check("reject manual placement without platforms", r.status_code == 422 and "至少" in r.text,
      f"{r.status_code} {r.text[:120]}")

# ═══ 4. WhatsApp promoted_object 断言 ═══
# 4a. ENGAGEMENT+whatsapp + 显式号码 → promoted_object 带号码
r = httpx.post(f"{BASE}/launch-templates", headers=H,
               json=_tree_tpl("SMOKE-I-wa", "OUTCOME_ENGAGEMENT",
                              _node(conv_location="whatsapp"), page_id="1122334455",
                              whatsapp_phone_number="+85512345678"), timeout=30)
check("create ENGAGEMENT+whatsapp 200", r.status_code == 200, r.text[:150])
WA_TID = r.json().get("id") if r.status_code == 200 else None
if WA_TID:
    check("wa number echoed/normalized", (r.json().get("whatsapp_phone_number") or "") == "+85512345678",
          str(r.json().get("whatsapp_phone_number")))
    r = httpx.post(f"{BASE}/launch-templates/{WA_TID}/preflight", headers=H,
                   json={"act_id": ACT, "page_id": "1122334455"}, timeout=60)
    ad = (r.json().get("adset") or {}) if r.status_code == 200 else {}
    po = ad.get("promoted_object") or {}
    check("WHATSAPP dest + page + explicit number",
          ad.get("destination_type") == "WHATSAPP" and po.get("page_id") == "1122334455"
          and po.get("whatsapp_phone_number") == "+85512345678", str(po))
    check("optimization_goal=CONVERSATIONS", ad.get("optimization_goal") == "CONVERSATIONS")
# 4b. TRAFFIC+whatsapp + 显式号码 → 随主页（不传号码）
r = httpx.post(f"{BASE}/launch-templates", headers=H,
               json=_tree_tpl("SMOKE-I-wa2", "OUTCOME_TRAFFIC",
                              _node(conv_location="whatsapp"), page_id="1122334455",
                              whatsapp_phone_number="+85512345678"), timeout=30)
WA2 = r.json().get("id") if r.status_code == 200 else None
if WA2:
    r = httpx.post(f"{BASE}/launch-templates/{WA2}/preflight", headers=H,
                   json={"act_id": ACT, "page_id": "1122334455"}, timeout=60)
    po = ((r.json().get("adset") or {}).get("promoted_object") or {})
    check("TRAFFIC whatsapp = page only (number NOT sent)",
          po.get("page_id") == "1122334455" and "whatsapp_phone_number" not in po, str(po))
# 4c. 号码格式校验 → 422
r = httpx.post(f"{BASE}/launch-templates", headers=H,
               json=_tree_tpl("SMOKE-I-wa3", "OUTCOME_ENGAGEMENT", _node(), page_id="1",
                              whatsapp_phone_number="123"), timeout=30)
check("reject bad whatsapp number format", r.status_code == 422 and "WhatsApp" in r.text,
      f"{r.status_code} {r.text[:120]}")

# ═══ 5. Leads 组合位枚举可用（保存+派生）═══
r = httpx.post(f"{BASE}/launch-templates", headers=H,
               json=_tree_tpl("SMOKE-I-combo", "OUTCOME_LEADS",
                              _node(conv_location="on_ad_messenger"), page_id="1122334455"), timeout=30)
check("create LEADS combo on_ad_messenger 200", r.status_code == 200, r.text[:150])
CB = r.json().get("id") if r.status_code == 200 else None
if CB:
    r = httpx.post(f"{BASE}/launch-templates/{CB}/preflight", headers=H,
                   json={"act_id": ACT, "page_id": "1122334455"}, timeout=60)
    ad = (r.json().get("adset") or {}) if r.status_code == 200 else {}
    check("combo → ON_AD + LEAD_GENERATION + page",
          ad.get("destination_type") == "ON_AD" and ad.get("optimization_goal") == "LEAD_GENERATION"
          and (ad.get("promoted_object") or {}).get("page_id") == "1122334455",
          f"{ad.get('destination_type')}/{ad.get('optimization_goal')}/{ad.get('promoted_object')}")

# ═══ 6. CBO+lifetime 树模式排期守卫（审计 C1）═══
from types import SimpleNamespace
from app.routers.launch_templates import _budget_guard_400
from fastapi import HTTPException as _HTTPEx
def _g(structure, sched=("","")):
    return SimpleNamespace(budget_type="lifetime", budget_usd=15, daily_budget=0,
                           lifetime_budget_usd=100, schedule_start=sched[0], schedule_end=sched[1],
                           budget_mode="CBO", structure=structure)
_grp_ok = json.dumps({"adsets": [{**_node(), "enabled": True,
    "schedule_start": "2026-09-10 08:00", "schedule_end": "2026-09-15 22:00"}]}, ensure_ascii=False)
_grp_no = json.dumps({"adsets": [_node()]}, ensure_ascii=False)   # 组停用且无排期
try:
    _budget_guard_400(_g(_grp_ok)); ok1 = True
except _HTTPEx:
    ok1 = False
check("CBO+lifetime + 组级排期 → 守卫放行", ok1)
try:
    _budget_guard_400(_g(_grp_no)); ok2 = False
except _HTTPEx as e:
    ok2 = e.status_code == 400 and "排期" in str(e.detail)
check("CBO+lifetime 无任何排期 → 400", ok2, "")
# 模板级排期仍走原路（平铺）
try:
    _budget_guard_400(_g(_grp_no, sched=("2026-09-10 08:00", "2026-09-15 22:00"))); ok3 = True
except _HTTPEx:
    ok3 = False
check("模板级排期满足（平铺路径不变）", ok3)

# ═══ 7. 自动建链（建/查/碰撞/门/回滚清理）═══
from app.routers.launch_templates import (_create_auto_subcode, _auto_slug_base,
                                          _auto_landing_gate, _flat_auto_subcode)
from app.models.launch import LandingPage, LandingAdLink
db = _S()
_lp = LandingPage(tenant_id=1, title="SMOKE-I-LP", status="draft", redirect_mode="display")
db.add(_lp); db.flush()
LPID = _lp.id
_created = []
try:
    # 7a. 门：未发布 → 400
    try:
        _auto_landing_gate(db, [{"ads": [{"landing_page_id": LPID, "subcode_slug": ""}]}], 1)
        check("auto gate: unpublished page rejected", False)
    except _HTTPEx as e:
        check("auto gate: unpublished page rejected", e.status_code == 400 and "未发布" in str(e.detail),
              str(e.detail)[:100])
    # 7b. 门：发布后放行
    _lp.status = "published"; db.commit()
    try:
        _auto_landing_gate(db, [{"ads": [{"landing_page_id": LPID, "subcode_slug": ""}]}], 1)
        check("auto gate: published page passes", True)
    except _HTTPEx as e:
        check("auto gate: published page passes", False, str(e.detail)[:100])
    # 7c. slug 基底形状（lt{tpl}-node-{asset|s}-{act尾4}）
    sb = _auto_slug_base(999, "ad_1", None, "act_123456")
    import re as _re
    check("slug base shape", _re.match(r"^lt999-ad_1-s-3456$", sb) is not None, sb)
    sb2 = _auto_slug_base(999, "广告节点/杂key!", None, "1234567890")
    check("slug base charset sanitized", _re.match(r"^[A-Za-z0-9_-]+$", sb2) is not None and "lt999-" in sb2, sb2)
    # 7d. 建链：reserved + 归属（page/act）；碰撞加后缀
    l1 = _create_auto_subcode(db, 1, LPID, "act_123456", sb)
    db.commit(); _created.append(l1.id)
    row = db.query(LandingAdLink).filter(LandingAdLink.id == l1.id).first()
    check("auto link created reserved", row.status == "reserved" and row.slug == sb
          and row.page_id == LPID and row.act_id == "act_123456",
          f"{row.slug}/{row.status}/{row.page_id}/{row.act_id}")
    l2 = _create_auto_subcode(db, 1, LPID, "act_123456", sb)
    db.commit(); _created.append(l2.id)
    check("collision suffix -1", l2.slug == f"{sb}-1", l2.slug)
    # 7e. 平铺 helper：tpl 绑页未选子码 → 建链返 base（SimpleNamespace 代替 LaunchTemplate/item）
    _ftpl = SimpleNamespace(subcode_slug="", landing_page_id=LPID, tenant_id=1, id=999,
                            platform="fb")
    _fitem = SimpleNamespace(act_id="act_123456", subcode_slug="")
    slug3, link3, base3, warn3 = _flat_auto_subcode(db, _ftpl, _fitem, None)
    if link3:
        _created.append(link3.id)
    check("flat auto subcode created", bool(slug3) and bool(base3) and warn3 == ""
          and base3.startswith("https://"), f"{slug3}|{base3}|{warn3}")
    check("flat helper records item.subcode_slug", _fitem.subcode_slug == slug3)
    # 7f. redirect 页 → 降级 warn（不静默）
    _lp.redirect_mode = "redirect"; db.commit()
    slug4, link4, base4, warn4 = _flat_auto_subcode(db, _ftpl, _fitem, None)
    check("redirect page → degrade with warn", slug4 == "" and base4 == "" and "降级" in warn4, warn4[:120])
    db.rollback()   # 弃掉降级路径的 write_log（smoke 不留日志噪音）
finally:
    # 回滚清理（零残留）
    if _created:
        db.query(LandingAdLink).filter(LandingAdLink.id.in_(_created)).delete(synchronize_session=False)
    db.query(LandingPage).filter(LandingPage.id == LPID).delete(synchronize_session=False)
    db.commit(); db.close()
    check("auto-link smoke rows cleaned", True)

# ═══ 8. 2 个部署 bug 回归（直调 build_adset）═══
from app.core.ad_builder import build_adset
# 8a. 隐患A：destination_type_override 不再顶掉矩阵派生值
p = build_adset(name="t", campaign_id="c", daily_budget=1000, objective="OUTCOME_ENGAGEMENT",
                page_id="111", conv_location="messenger", destination_type_override="ON_PAGE")
check("bugA: override ignored when conv_location set", p["destination_type"] == "MESSENGER",
      str(p.get("destination_type")))
check("bugA: messenger union placement", p["targeting"].get("publisher_platforms") == ["messenger"])
# 8b. 隐患A 反向：conv_location 空 → override 仍生效（存量行为）
p2 = build_adset(name="t", campaign_id="c", daily_budget=1000, objective="OUTCOME_ENGAGEMENT",
                 page_id="111", optimization_goal="PAGE_LIKES", destination_type_override="ON_PAGE")
check("legacy override still applies when no conv_location", p2["destination_type"] == "ON_PAGE",
      str(p2.get("destination_type")))
# 8c. 隐患B：SALES+非转化优化目标 → promoted_object 兜底 / 缺 page_id 400
p3 = build_adset(name="t", campaign_id="c", daily_budget=1000, objective="OUTCOME_SALES",
                 page_id="222", optimization_goal="CONVERSATIONS")
check("bugB: SALES+CONVERSATIONS promoted_object={page_id}",
      p3.get("promoted_object") == {"page_id": "222"} and p3.get("destination_type") == "MESSENGER",
      f"{p3.get('promoted_object')}/{p3.get('destination_type')}")
try:
    build_adset(name="t", campaign_id="c", daily_budget=1000, objective="OUTCOME_SALES",
                optimization_goal="CONVERSATIONS")
    check("bugB: SALES without pixel/page → ValueError", False)
except ValueError as e:
    check("bugB: SALES without pixel/page → ValueError", "page_id" in str(e), str(e)[:100])

# ═══ 9. 旧树 smoke 回归（0088 链路没被批次I改坏）═══
import subprocess
cp = subprocess.run([sys.executable, "/tmp/_smoke_tree_tpl.py"], capture_output=True, text=True)
check("0088 tree smoke regression ALL PASS", cp.returncode == 0,
      cp.stdout.strip().split("\n")[-1] if cp.stdout else cp.stderr[:150])

# ---- 清理 ----
for tid in filter(None, (TID, WA_TID, WA2, CB)):
    httpx.delete(f"{BASE}/launch-templates/{tid}", headers=H, timeout=30)

print()
if FAILS:
    print(f"RESULT: {len(FAILS)} FAILED -> {FAILS}"); sys.exit(1)
print("RESULT: ALL PASS")
