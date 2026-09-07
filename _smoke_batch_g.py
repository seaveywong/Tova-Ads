# 批G smoke（断言式）：排期/总预算/投放方式/出价/特殊类别/描述 全链
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
finally:
    _db.close()
H = {"Authorization": f"Bearer {TOK}"}

base = {
    "name": "SMOKE-G", "platform": "fb", "objective": "OUTCOME_TRAFFIC",
    "budget_mode": "ABO", "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
    "budget_usd": 15, "name_prefix": "SmokeG", "budget_type": "lifetime",
    "lifetime_budget_usd": 90, "schedule_start": "2026-09-10 08:00",
    "schedule_end": "2026-09-15 22:00", "pacing": "accelerated",
    "bid_amount_usd": 1.5, "minimum_roas": 1.2,
    "special_ad_categories": json.dumps(["CREDIT"]),
    "link_description": "smoke desc",
}

# ---- 1. 合法创建（lifetime+排期+加速+出价+ROAS+类别+描述）----
r = httpx.post(f"{BASE}/launch-templates", headers=H, json=base, timeout=30)
check("create G template 200", r.status_code == 200, r.text[:150])
t = r.json() if r.status_code == 200 else {}
TID = t.get("id")
check("echo budget_type=lifetime", t.get("budget_type") == "lifetime")
check("echo schedule", t.get("schedule_start") == "2026-09-10 08:00" and t.get("schedule_end") == "2026-09-15 22:00")
check("echo pacing/special cats", t.get("pacing") == "accelerated" and t.get("special_ad_categories") == '["CREDIT"]')
check("echo desc/bid/roas", t.get("link_description") == "smoke desc"
      and abs((t.get("bid_amount_usd") or 0) - 1.5) < 1e-6 and abs((t.get("minimum_roas") or 0) - 1.2) < 1e-6)

# ---- 2. 校验门 ----
def bad(name, **over):
    b = {**base, "name": f"SMOKE-G-bad-{name}", **over}
    r = httpx.post(f"{BASE}/launch-templates", headers=H, json=b, timeout=30)
    check(f"reject {name}", r.status_code in (400, 422), f"{r.status_code} {r.text[:100]}")

bad("lifetime over cap", lifetime_budget_usd=99999)
bad("bad schedule fmt", schedule_start="2026/09/10")
bad("bad category", special_ad_categories=json.dumps(["FOO"]))
# pacing/budget_type 非法值走白名单回落（安全侧），应 200 且规范化
r = httpx.post(f"{BASE}/launch-templates", headers=H, json={**base, "name": "SMOKE-G-norm", "pacing": "turbo", "budget_type": "weekly"}, timeout=30)
check("normalize pacing/budget_type", r.status_code == 200 and r.json().get("pacing") == "" and r.json().get("budget_type") == "daily", r.text[:100])
if r.status_code == 200:
    httpx.delete(f"{BASE}/launch-templates/{r.json()['id']}", headers=H, timeout=30)

# ---- 3. 平铺预检：payload 含新字段 ----
r = httpx.post(f"{BASE}/launch-templates/{TID}/preflight", headers=H,
               json={"act_id": ACT}, timeout=60)
check("flat preflight 200", r.status_code == 200, r.text[:150])
pf = r.json() if r.status_code == 200 else {}
check("pf budget_type/lifetime_fb", pf.get("budget_type") == "lifetime" and (pf.get("lifetime_budget_fb") or 0) > 0,
      f"lifetime_fb={pf.get('lifetime_budget_fb')}")
if (pf.get("currency") or "USD") == "USD" and pf.get("lifetime_budget_usd"):
    check("USD: 90 -> 9000 minor", pf.get("lifetime_budget_fb") == 9000, str(pf.get("lifetime_budget_fb")))
    check("USD: bid 1.5 -> 150 minor", pf.get("bid_amount_fb") == 150, str(pf.get("bid_amount_fb")))
check("pf adset start_time ISO T", (pf.get("adset") or {}).get("start_time") == "2026-09-10T08:00",
      str((pf.get("adset") or {}).get("start_time")))
check("pf adset pacing no_pacing", (pf.get("adset") or {}).get("pacing_type") == ["no_pacing"])
check("pf adset lifetime_budget", (pf.get("adset") or {}).get("lifetime_budget") == str(pf.get("lifetime_budget_fb")))
check("pf adset bid_amount", (pf.get("adset") or {}).get("bid_amount") == str(pf.get("bid_amount_fb")))
check("pf adset minimum_roas", (pf.get("adset") or {}).get("minimum_roas") == "1.2")
check("pf campaign special cats", (pf.get("campaign") or {}).get("special_ad_categories") == ["CREDIT"])

# ---- 4. lifetime 无排期 → 部署/预检 400 ----
r = httpx.put(f"{BASE}/launch-templates/{TID}", headers=H,
              json={**base, "schedule_start": "", "schedule_end": ""}, timeout=30)
check("clear schedule ok(draft allowed)", r.status_code == 200, r.text[:100])
r = httpx.post(f"{BASE}/launch-templates/{TID}/preflight", headers=H,
               json={"act_id": ACT}, timeout=60)
check("preflight reject: lifetime no schedule", r.status_code == 400 and "排期" in r.text, r.text[:120])

# ---- 5. 树节点 lifetime：带排期 OK / 不带 422 ----
good_node = {"key": "as_1", "name": "组LT", "enabled": False, "budget_usd": None,
             "budget_type": "lifetime", "lifetime_budget_usd": 50,
             "schedule_start": "2026-09-11 09:00", "schedule_end": "2026-09-14 21:00",
             "audience_id": 0, "audience_json": "", "optimization_goal": "",
             "billing_event": "", "advanced_config": "",
             "ads": [{"key": "ad_1", "name": "", "enabled": False, "asset_ids": [],
                      "headline": "", "body": "", "cta_type": "", "ad_language": "",
                      "landing_page_id": 0, "landing_url": "", "subcode_slug": "",
                      "message_template_id": 0, "lead_form_template_id": 0, "pixel_id": "",
                      "post_source": "new", "reuse_post_ref": "", "link_description": ""}]}
r = httpx.post(f"{BASE}/launch-templates", headers=H, json={
    **base, "name": "SMOKE-G-tree", "budget_type": "daily",
    "structure": json.dumps({"adsets": [good_node]}, ensure_ascii=False)}, timeout=30)
check("tree node lifetime+schedule 200", r.status_code == 200, r.text[:150])
if r.status_code == 200:
    httpx.delete(f"{BASE}/launch-templates/{r.json()['id']}", headers=H, timeout=30)
bad_node = {**good_node, "schedule_start": "", "schedule_end": ""}
r = httpx.post(f"{BASE}/launch-templates", headers=H, json={
    **base, "name": "SMOKE-G-tree-bad", "budget_type": "daily",
    "structure": json.dumps({"adsets": [bad_node]}, ensure_ascii=False)}, timeout=30)
check("tree node lifetime no schedule 422", r.status_code == 422 and "排期" in r.text, f"{r.status_code} {r.text[:120]}")

# ---- 6. 旧树 smoke 回归（0088 链路没被批G改坏）----
import subprocess
cp = subprocess.run([sys.executable, "/tmp/_smoke_tree_tpl.py"], capture_output=True, text=True)
check("0088 tree smoke regression ALL PASS", cp.returncode == 0, cp.stdout.strip().split("\n")[-1] if cp.stdout else cp.stderr[:100])

# ---- 清理 ----
r = httpx.delete(f"{BASE}/launch-templates/{TID}", headers=H, timeout=30)
check("cleanup", r.status_code == 200)

print()
if FAILS:
    print(f"RESULT: {len(FAILS)} FAILED -> {FAILS}"); sys.exit(1)
print("RESULT: ALL PASS")
