# 批I smoke：成效口径按组优化目标（生产真实数据：系列 Te / BSCH-TD-O324，2026-09-09 实拉 acts）
# 只读断言，无任何写操作。
import sys
sys.path.insert(0, "/opt/toveads/backend")
from dotenv import load_dotenv; load_dotenv("/opt/toveads/backend/.env")
from app.core.database import SuperSessionLocal
from app.services.kpi_resolver import resolve_kpi
from app.services.guard_engine import _adset_optgoals

ok = fail = 0
def check(name, cond, detail=""):
    global ok, fail
    if cond: ok += 1; print("PASS", name)
    else: fail += 1; print("FAIL", name, detail)

CID = "120250602446160305"   # 系列 Te
ACTS_AD2 = [   # 今天 spend=11.81 那条广告的原始 actions（link_click=3，会话=1）
    {"action_type": "link_click", "value": "3"},
    {"action_type": "onsite_conversion.total_messaging_connection", "value": "1"},
    {"action_type": "post_engagement", "value": "3"},
    {"action_type": "page_engagement", "value": "3"},
    {"action_type": "onsite_conversion.messaging_user_depth_2_message_send", "value": "1"},
    {"action_type": "onsite_conversion.messaging_first_reply", "value": "1"},
    {"action_type": "onsite_conversion.messaging_user_depth_3_message_send", "value": "1"},
    {"action_type": "onsite_conversion.messaging_user_depth_5_message_send", "value": "3"},
    {"action_type": "onsite_conversion.messaging_conversation_started_7d", "value": "1"},
]
ACTS_AD1 = [{"action_type": "link_click", "value": "2"}, {"action_type": "post_engagement", "value": "3"}]
ACTS_AD3 = [{"action_type": "link_click", "value": "1"}, {"action_type": "post_engagement", "value": "1"}]

s = SuperSessionLocal()
# 1. 组=CONVERSATIONS → 数会话（FB 对话广告成效口径）= 1，不再数 3 个点击
k = resolve_kpi(s, 1, CID, "OUTCOME_TRAFFIC", "CONVERSATIONS", ACTS_AD2)
check("CONVERSATIONS counts sessions", k["conversions"] == 1, f"{k}")
check("CONVERSATIONS field", k["kpi_field"] == "onsite_conversion.messaging_conversation_started_7d", k.get("kpi_field"))
# 2. og 空（查不到组）→ 行为与旧版一致（TRAFFIC 系列维度，数点击）
k_old = resolve_kpi(s, 1, CID, "OUTCOME_TRAFFIC", "", ACTS_AD2)
check("og empty = old series behavior", k_old["conversions"] == 3, f"{k_old}")
# 3. og=LINK_CLICKS → 点击
k = resolve_kpi(s, 1, CID, "OUTCOME_TRAFFIC", "LINK_CLICKS", ACTS_AD2)
check("LINK_CLICKS counts clicks", k["conversions"] == 3, f"{k}")
# 4. 三条广告按组优化目标汇总 = 1（FB 系列行成效），不再是 6
og_map = _adset_optgoals(s, 1, "1810272139982142", "fb")
check("og map has Te adsets", og_map.get("120250602446170305") == "CONVERSATIONS", str(og_map)[:120])
total = 0
for acts in (ACTS_AD1, ACTS_AD2, ACTS_AD3):
    k = resolve_kpi(s, 1, CID, "OUTCOME_TRAFFIC", og_map.get("120250602446170305", ""), acts)
    total += k["results_fb"]
check("campaign total = FB parity (1)", total == 1, f"total={total}")
# 5. SALES purchase 回归不受影响
k = resolve_kpi(s, 1, "x", "OUTCOME_SALES", "",
                [{"action_type": "offsite_conversion.fb_pixel_purchase", "value": "5"}])
check("regress SALES purchase", k["conversions"] == 5, f"{k}")
# 6. PAGE_LIKES → like
k = resolve_kpi(s, 1, "x", "OUTCOME_ENGAGEMENT", "PAGE_LIKES",
                [{"action_type": "like", "value": "19"}, {"action_type": "link_click", "value": "7"}])
check("PAGE_LIKES counts likes", k["conversions"] == 19, f"{k}")
s.close()
print(f"SMOKE_RESULT: {'ALL_PASS' if fail == 0 else 'FAIL'} ({ok}/{ok+fail})")
sys.exit(0 if fail == 0 else 1)
