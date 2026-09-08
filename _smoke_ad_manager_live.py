"""Ads Manager live-data assertions (read-only, superuser session; no auth layer).

跑法（服务器）：venv/bin/python _smoke_ad_manager_live.py
断言：/ads/list 全链路返回带 results_fb_available；0093 前旧快照行不冒充实测；
非零行必可用；细分端点在真账户上返回 rows 结构（FB 侧不可达时 SKIP 不算失败）。
"""
import json
import pathlib
import sys
import types

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from app.routers.ads import list_ads, _perf_map, ads_insights_breakdown  # noqa: E402
from app.core.database import SuperSessionLocal  # noqa: E402
from fastapi import HTTPException  # noqa: E402

TENANT = 1
fails = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


db = SuperSessionLocal()
try:
    user = types.SimpleNamespace(tenant_id=TENANT, is_superadmin=False)
    # 1) /ads/list 全链路（纯读聚合，refresh=0 不触发后台任务）
    r = list_ads("", "2026-09-02", "2026-09-09", 0, user, db, None)
    for level in ("campaigns", "adsets", "ads"):
        rows = r.get(level) or []
        check(f"{level} rows carry results_fb_available",
              all("results_fb_available" in x for x in rows) if rows else True)
    # 2) 口径可用性：非零行必可用；0093 前旧零行不可用（不冒充实测）
    perf = _perf_map(db, TENANT, "", "2026-09-02", "2026-09-09")
    nonzero = [k for k, v in perf.items() if (v["results_fb"] or 0) > 0]
    check("nonzero rows are available", all(perf[k]["results_fb_available"] for k in nonzero))
    old = _perf_map(db, TENANT, "", "2026-09-02", "2026-09-03")
    old_zero = [v for v in old.values() if (v["results_fb"] or 0) == 0]
    check("pre-epoch zero rows are unavailable",
          all(not v["results_fb_available"] for v in old_zero) if old_zero else True)
    # 3) 细分端点（真 FB 账户 + 真 ad；无可用读令牌/无数据 → SKIP）
    from app.models.ads_cache import AdsCache
    cr = db.query(AdsCache).filter(
        AdsCache.tenant_id == TENANT, AdsCache.platform == "fb").first()
    if not cr or not (json.loads(cr.ads_json or "[]")):
        print("SKIP breakdown (no fb ads in cache)")
    else:
        ad = json.loads(cr.ads_json)[0]
        try:
            bd = ads_insights_breakdown(act_id=cr.act_id, ad_id=str(ad["id"]),
                                        dimension="age", date_from="2026-09-02",
                                        date_to="2026-09-09", user=user, db=db)
            check("breakdown returns rows with dimension_value",
                  isinstance(bd.get("rows"), list)
                  and all("dimension_value" in x for x in bd["rows"]))
        except HTTPException as e:
            print(f"SKIP breakdown (endpoint rejected: {e.status_code} {e.detail})")
finally:
    db.close()

print("SMOKE_RESULT:", "ALL_PASS" if not fails else f"FAIL({len(fails)})")
sys.exit(0 if not fails else 1)
