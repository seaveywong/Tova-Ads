# 批H smoke：转化位置矩阵对齐官方 + 细分维度（纯函数级，无外部写）
import sys
sys.path.insert(0, "/opt/toveads/backend")
from app.core.ad_builder import (CONV_LOCATIONS_BY_OBJECTIVE, _CONV_MATRIX,
                                 OPT_GOALS_BY_OBJECTIVE, OPT_GOALS_BY_LOCATION,
                                 resolve_adset_destination, build_adset)
ok = fail = 0
def check(name, cond, detail=""):
    global ok, fail
    if cond: ok += 1; print("PASS", name)
    else: fail += 1; print("FAIL", name, detail)

# 1 销量不再有单独「通话」位（官方矩阵：销量无 Calls 单选）
try:
    build_adset(name="t", campaign_id="1", daily_budget=1000, objective="OUTCOME_SALES",
                conv_location="phone_call", page_id="111")
    check("SALES phone_call rejected", False, "no error raised")
except ValueError:
    check("SALES phone_call rejected", True)

# 2 流量的 Instagram 位不再是 IG 私信（改为 Instagram 主页）
try:
    build_adset(name="t", campaign_id="1", daily_budget=1000, objective="OUTCOME_TRAFFIC",
                conv_location="instagram_direct", page_id="111")
    check("TRAFFIC instagram_direct rejected", False, "no error raised")
except ValueError:
    check("TRAFFIC instagram_direct rejected", True)

# 3 TRAFFIC instagram_profile → INSTAGRAM_PROFILE / VISIT_INSTAGRAM_PROFILE / promoted page
p = build_adset(name="t", campaign_id="1", daily_budget=1000, objective="OUTCOME_TRAFFIC",
                conv_location="instagram_profile", page_id="111")
check("TRAFFIG instagram_profile dest", p.get("destination_type") == "INSTAGRAM_PROFILE", p.get("destination_type"))
check("TRAFFIC instagram_profile opt", p.get("optimization_goal") == "VISIT_INSTAGRAM_PROFILE", p.get("optimization_goal"))
check("TRAFFIC instagram_profile promoted", p.get("promoted_object") == {"page_id": "111"}, p.get("promoted_object"))

# 4 LEADS instagram_direct → LEAD_FROM_IG_DIRECT（IG 私信收线索）
p = build_adset(name="t", campaign_id="1", daily_budget=1000, objective="OUTCOME_LEADS",
                conv_location="instagram_direct", page_id="111")
check("LEADS ig_direct opt", p.get("optimization_goal") == "LEAD_FROM_IG_DIRECT", p.get("optimization_goal"))

# 5 LEADS phone_call → QUALITY_CALL（Call Ads 指南口径）
p = build_adset(name="t", campaign_id="1", daily_budget=1000, objective="OUTCOME_LEADS",
                conv_location="phone_call", page_id="111")
check("LEADS phone_call opt", p.get("optimization_goal") == "QUALITY_CALL", p.get("optimization_goal"))

# 6 resolve_adset_destination 与矩阵一致
dt, og = resolve_adset_destination("OUTCOME_TRAFFIC", "instagram_profile")
check("resolve instagram_profile", dt == "INSTAGRAM_PROFILE" and og == "VISIT_INSTAGRAM_PROFILE", f"{dt}/{og}")

# 7 矩阵自洽：每个默认 goal 同时在 objective 表和 location 表里
for (obj, loc), (dt, og, kind) in _CONV_MATRIX.items():
    check(f"matrix goal legal {obj}/{loc}",
          og in OPT_GOALS_BY_OBJECTIVE.get(obj, set()) and og in OPT_GOALS_BY_LOCATION.get(loc, set()), og)

# 8 合法值集合与矩阵键一致
locs = {loc for s in CONV_LOCATIONS_BY_OBJECTIVE.values() for loc in s}
check("loc sets match", locs == {k[1] for k in _CONV_MATRIX}, str(locs ^ {k[1] for k in _CONV_MATRIX}))

# 9 细分端点维度表含转化位置
from app.routers.ads import _BREAKDOWN_DIMS
check("breakdown dims conv", _BREAKDOWN_DIMS.get("conversion_location") == "conversion_destination")

# 10 既有组合回归：SALES whatsapp / LEADS on_ad / ENGAGEMENT on_page 不变
dt, og = resolve_adset_destination("OUTCOME_SALES", "whatsapp")
check("regress SALES whatsapp", dt == "WHATSAPP" and og == "CONVERSATIONS", f"{dt}/{og}")
dt, og = resolve_adset_destination("OUTCOME_LEADS", "on_ad")
check("regress LEADS on_ad", dt == "ON_AD" and og == "LEAD_GENERATION", f"{dt}/{og}")
dt, og = resolve_adset_destination("OUTCOME_ENGAGEMENT", "on_page")
check("regress ENG on_page", dt == "ON_PAGE" and og == "PAGE_LIKES", f"{dt}/{og}")

print(f"SMOKE_RESULT: {'ALL_PASS' if fail == 0 else 'FAIL'} ({ok}/{ok+fail})")
sys.exit(0 if fail == 0 else 1)
