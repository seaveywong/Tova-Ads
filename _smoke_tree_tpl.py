# 1:1 FB 三层结构模板 smoke（断言式，遵循 bare-except-silent-failure 铁律）。
# 覆盖：0088 迁移列/GRANT、structure 校验门（合法+5 类非法）、平铺双写、复制、
# 部署守卫（tt 拒/叠加批量拒/ABO 求和超限拒/无预算拒）、树预检（mode/tree/will_spend/本币换算）。
# 只建一个 smoke 模板最后归档清理；不真部署（真部署花钱，需用户授权另行做）。
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
finally:
    _db.close()
r = httpx.get(f"{BASE}/auth/me", headers={"Authorization": f"Bearer {TOK}"}, timeout=30)
check("token minted + auth/me", r.status_code == 200, r.text[:100])
H = {"Authorization": f"Bearer {TOK}"}

# ---- 0. 迁移落库：列存在 + GRANT ----
from sqlalchemy import text as _t
_db = _S()
try:
    col = _db.execute(_t("SELECT column_name FROM information_schema.columns "
                         "WHERE table_name='launch_templates' AND column_name='structure'")).first()
    check("0088 column launch_templates.structure", col is not None)
    grants = _db.execute(_t("SELECT has_table_privilege('toveads_app','launch_templates','UPDATE'), "
                            "has_table_privilege('toveads_super','launch_templates','SELECT')")).fetchone()
    check("0088 GRANT both roles", bool(grants[0]) and bool(grants[1]), str(grants))
    # 拿一个 managed 账户（预检用）+ 两个真素材（FK 校验）
    row = _db.execute(_t("SELECT act_id, currency FROM accounts WHERE tenant_id=1 AND is_managed=true "
                         "AND platform='fb' AND act_id <> '' ORDER BY id LIMIT 1")).first()
    arow = _db.execute(_t("SELECT id FROM assets WHERE tenant_id=1 ORDER BY id LIMIT 2")).fetchall()
    A1, A2 = (arow[0][0], arow[1][0]) if len(arow) >= 2 else (0, 0)
finally:
    _db.close()
check("managed fb account exists", row is not None)
if not row:
    print("FATAL: no managed account, cannot run preflight part"); sys.exit(1)
ACT, CUR = row[0], row[1]
check("2 real assets exist (for FK-safe tree)", A1 > 0 and A2 > 0, f"{A1},{A2}")
if not (A1 and A2):
    print("FATAL: need 2 assets"); sys.exit(1)

# ---- 1. structure 校验门：合法结构 200 + 规范化回显 ----
good_adsets = [
    {"key": "as_1", "name": "组A", "enabled": False, "budget_usd": 20,
     "audience_id": 0, "audience_json": "", "optimization_goal": "", "billing_event": "", "advanced_config": "",
     "ads": [
        {"key": "ad_1", "name": "", "enabled": False, "asset_ids": [A1, A1, A2], "headline": "h",
         "body": "b", "cta_type": "", "ad_language": "", "landing_page_id": 0, "landing_url": "",
         "subcode_slug": "", "message_template_id": 0, "lead_form_template_id": 0, "pixel_id": "",
         "post_source": "new", "reuse_post_ref": ""},
        {"key": "ad_2", "name": "跟帖位", "enabled": True, "asset_ids": [], "headline": "", "body": "",
         "cta_type": "", "ad_language": "", "landing_page_id": 0, "landing_url": "",
         "subcode_slug": "", "message_template_id": 0, "lead_form_template_id": 0, "pixel_id": "",
         "post_source": "reuse", "reuse_post_ref": "123456_999"},
     ]},
]
base_body = {
    "name": "SMOKE-树模板", "description": "smoke", "platform": "fb",
    "objective": "OUTCOME_TRAFFIC", "conversion_goal": "", "budget_mode": "ABO",
    "bid_strategy": "LOWEST_COST_WITHOUT_CAP", "budget_usd": 15, "name_prefix": "SmokeTree",
    "page_id": "", "pixel_id": "", "beneficiary": "", "payer": "", "landing_url": "",
    "structure": json.dumps({"adsets": good_adsets}, ensure_ascii=False),
}
r = httpx.post(f"{BASE}/launch-templates", headers=H, json=base_body, timeout=30)
check("create tree template 200", r.status_code == 200, r.text[:150])
tpl = r.json() if r.status_code == 200 else {}
TID = tpl.get("id")
check("structure echoed back", bool(tpl.get("structure")))
try:
    st = json.loads(tpl["structure"])
    ad1 = st["adsets"][0]["ads"][0]
    check("asset_ids deduped kept order", ad1["asset_ids"] == [A1, A2], str(ad1["asset_ids"]))
    check("enabled normalized (ad_2 true kept)", st["adsets"][0]["ads"][1]["enabled"] is True)
except Exception as e:
    check("structure parse", False, str(e))

# ---- 2. 平铺双写：第一组第一广告回写平铺列 ----
check("flat sync budget_usd", abs((tpl.get("budget_usd") or 0) - 20) < 0.01, str(tpl.get("budget_usd")))
# headline 回写（节点 headline='h'）
from app.core.database import SuperSessionLocal as _S2
_db = _S2()
try:
    from app.models.launch_template import LaunchTemplate as _LT
    t = _db.query(_LT).filter(_LT.id == TID).first()
    check("flat sync headline", (t.headline or "") == "h", t.headline)
finally:
    _db.close()

# ---- 3. 校验门：5 类非法结构 422/400 ----
def bad(name, mutate):
    b = dict(base_body)
    b["name"] = f"SMOKE-bad-{name}"
    b["structure"] = json.dumps(mutate(json.loads(base_body["structure"])), ensure_ascii=False)
    r = httpx.post(f"{BASE}/launch-templates", headers=H, json=b, timeout=30)
    check(f"reject {name}", r.status_code in (400, 422), f"{r.status_code} {r.text[:100]}")

bad("empty adsets", lambda s: {"adsets": []})
bad("no ads in adset", lambda s: {"adsets": [{**s["adsets"][0], "ads": []}]})
bad("budget over cap", lambda s: {"adsets": [{**s["adsets"][0], "budget_usd": 99999}]})
bad("reuse multi assets", lambda s: {"adsets": [{**s["adsets"][0],
    "ads": [{**s["adsets"][0]["ads"][1], "asset_ids": [1, 2]}]}]})
bad("bad placeholder", lambda s: {"adsets": [{**s["adsets"][0],
    "ads": [{**s["adsets"][0]["ads"][0], "landing_url": "https://x.com/?u={{ad.id}}"}]}]})
bad("over 200 expanded", lambda s: {"adsets": [
    {**s["adsets"][0], "ads": [{**s["adsets"][0]["ads"][0], "asset_ids": list(range(1, 51))} for _ in range(5)]}]})

# ---- 4. 复制模板带 structure ----
r = httpx.post(f"{BASE}/launch-templates/{TID}/copy", headers=H, timeout=30)
check("copy carries structure", r.status_code == 200 and bool(r.json().get("structure")), r.text[:100])
if r.status_code == 200:
    httpx.delete(f"{BASE}/launch-templates/{r.json()['id']}", headers=H, timeout=30)

# ---- 5. 部署守卫 ----
# 5a. ABO 启用组预算求和超上限（组A 20 + 组B 启用 4990 = 5010 > 5000）
r = httpx.put(f"{BASE}/launch-templates/{TID}", headers=H, json={
    **base_body, "structure": json.dumps({"adsets": [
        {**good_adsets[0], "enabled": True},
        {**good_adsets[0], "key": "as_2", "name": "组B", "enabled": True, "budget_usd": 4990},
    ]}, ensure_ascii=False)}, timeout=30)
check("update to over-cap ABO sum 200", r.status_code == 200, r.text[:120])
r = httpx.post(f"{BASE}/launch-templates/{TID}/deploy", headers=H,
               json={"items": [{"act_id": ACT}]}, timeout=30)
check("deploy rejected: ABO sum over cap", r.status_code == 400 and "求和" in r.text, r.text[:150])
# 5b. 恢复合规树 + 叠加批量 400
ok_struct = json.dumps({"adsets": [
    {**good_adsets[0], "enabled": False},
    {**good_adsets[0], "key": "as_2", "name": "组B", "enabled": False, "budget_usd": 30},
]}, ensure_ascii=False)
r = httpx.put(f"{BASE}/launch-templates/{TID}", headers=H, json={**base_body, "structure": ok_struct}, timeout=30)
check("update back to compliant 200", r.status_code == 200, r.text[:120])
r = httpx.post(f"{BASE}/launch-templates/{TID}/deploy", headers=H,
               json={"items": [{"act_id": ACT}], "asset_ids": [1]}, timeout=30)
check("deploy rejected: tree + batch assets", r.status_code == 400 and "树内" in r.text, r.text[:150])
# 5c. TT 模板带 structure → deploy 400（直接建 tt 结构模板）
r = httpx.post(f"{BASE}/launch-templates", headers=H, json={
    **base_body, "name": "SMOKE-tt-tree", "platform": "tt"}, timeout=30)
tt_id = r.json().get("id") if r.status_code == 200 else None
if tt_id:
    r2 = httpx.post(f"{BASE}/launch-templates/{tt_id}/deploy", headers=H,
                    json={"items": [{"act_id": "tt-fake"}]}, timeout=30)
    # tt-fake 账户不存在本应先 400 账户校验——为构造确定路径，守卫顺序在账户循环前？核实：
    # deploy_template 里 tt+structure 守卫在账户校验之前（_is_tree 检查在 items 循环前）→ 期待 400 结构提示
    check("deploy rejected: tt + structure", r2.status_code == 400, f"{r2.status_code} {r2.text[:120]}")
    httpx.delete(f"{BASE}/launch-templates/{tt_id}", headers=H, timeout=30)
else:
    check("create tt tree template (for guard test)", False, r.text[:120])

# ---- 6. 树预检（不花钱）----
r = httpx.post(f"{BASE}/launch-templates/{TID}/preflight", headers=H,
               json={"act_id": ACT, "account_count": 3}, timeout=60)
check("preflight tree 200", r.status_code == 200, r.text[:200])
pf = r.json() if r.status_code == 200 else {}
check("preflight mode=tree", pf.get("mode") == "tree")
check("preflight adset_count=2", pf.get("adset_count") == 2, str(pf.get("adset_count")))
check("preflight ad_total expanded=6 (每組 2素材+1跟帖)", pf.get("ad_total") == 6, str(pf.get("ad_total")))
check("preflight will_spend empty (all disabled)", pf.get("will_spend") == [], str(pf.get("will_spend"))[:100])
tree0 = (pf.get("tree") or [{}])[0]
check("preflight per-adset budget_local_fb int>0", isinstance(tree0.get("budget_local_fb"), int) and tree0["budget_local_fb"] > 0,
      f"cur={pf.get('currency')} local={tree0.get('budget_local_fb')}")
check("preflight abo_total_usd=0 (两组全停用不消耗)", (pf.get("abo_total_usd") or 0) == 0, str(pf.get("abo_total_usd")))
check("preflight campaign payload present", bool(pf.get("campaign")))
# currency 断言：账户本币换算真的走了汇率管道（USD 账户 rate=1 → local=2000 = $20 minor）
if (pf.get("currency") or "USD") == "USD":
    check("USD acct: 20 -> 2000 minor", tree0.get("budget_local_fb") == 2000, str(tree0.get("budget_local_fb")))

# ---- 7. will_spend 路径：开一组一广告链 → 预检横幅列出 ----
r = httpx.put(f"{BASE}/launch-templates/{TID}", headers=H, json={
    **base_body, "structure": json.dumps({"adsets": [
        {**good_adsets[0], "enabled": True, "ads": [
            {**good_adsets[0]["ads"][0], "enabled": True}]},
    ]}, ensure_ascii=False)}, timeout=30)
check("update enable chain 200", r.status_code == 200, r.text[:120])
r = httpx.post(f"{BASE}/launch-templates/{TID}/preflight", headers=H,
               json={"act_id": ACT}, timeout=60)
pf2 = r.json() if r.status_code == 200 else {}
check("will_spend lists enabled chain", isinstance(pf2.get("will_spend"), list) and len(pf2["will_spend"]) >= 1,
      str(pf2.get("will_spend"))[:120])

# ---- 清理：归档 smoke 模板 ----
r = httpx.delete(f"{BASE}/launch-templates/{TID}", headers=H, timeout=30)
check("cleanup archive smoke template", r.status_code == 200, r.text[:80])

print()
if FAILS:
    print(f"RESULT: {len(FAILS)} FAILED -> {FAILS}"); sys.exit(1)
print("RESULT: ALL PASS")
