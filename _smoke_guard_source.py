# smoke: 巡检独家供数批（3 断言，数据完整性）
# 1) 巡检回写 ads_cache.ads_json（updated_at 刷新 + 数据非空）
# 2) ads_cache_sync 不再覆盖 ads_json（注入标记 → sync → 标记仍在 → 巡检还原）
# 3) budget_alerts 的 _active_adsets_from_cache 从 cache 读出 ACTIVE 列表
import json
import time
from datetime import datetime, timezone
from app.core.database import SuperSessionLocal
from app.models.ads_cache import AdsCache

ACT = "1338258757886709"  # Roly-V21
db = SuperSessionLocal()
row = db.query(AdsCache).filter(AdsCache.tenant_id == 1, AdsCache.act_id == ACT,
                                AdsCache.platform == "fb").first()
before = row.updated_at if row else None
db.close()

from app.services.guard_engine import run_inspection
r1 = run_inspection()
print("inspection:", {k: r1.get(k) for k in ("evaluated", "hits", "paused", "skipped_spend")})

db = SuperSessionLocal()
row = db.query(AdsCache).filter(AdsCache.tenant_id == 1, AdsCache.act_id == ACT,
                                AdsCache.platform == "fb").first()
assert row and row.ads_json, "ads_json missing after inspection"
assert before is None or row.updated_at > before, f"updated_at not refreshed: {before} -> {row.updated_at}"
_ads = json.loads(row.ads_json)
assert isinstance(_ads, list) and any(a.get("creative") for a in _ads), "ads_json has no creative rows"
print(f"PASS guard writeback: {len(_ads)} ads, updated_at={row.updated_at}")

# 2) 注入标记 → sync → 验证 ads_json 未被覆盖 → 巡检还原
_ads.append({"id": "__mark_guard__"})
row.ads_json = json.dumps(_ads, ensure_ascii=False)
db.commit()
db.close()

from app.services.ads_cache_sync import run_ads_cache_sync
r2 = run_ads_cache_sync()
print("cache_sync:", r2)

db = SuperSessionLocal()
row = db.query(AdsCache).filter(AdsCache.tenant_id == 1, AdsCache.act_id == ACT,
                                AdsCache.platform == "fb").first()
assert "__mark_guard__" in (row.ads_json or ""), "ads_json was OVERWRITTEN by sync (should be guard-only)"
print("PASS sync preserves ads_json (guard is sole ads source)")

# 3) budget_alerts cache 读取
from app.services.budget_alerts import _active_adsets_from_cache
adsets = _active_adsets_from_cache(db, 1, ACT)
assert adsets is not None, "cache read returned None (fell back to live)"
assert all((a.get("effective_status") or "").upper() == "ACTIVE" for a in adsets), "non-ACTIVE leaked"
print(f"PASS budget_alerts cache read: {len(adsets)} ACTIVE adsets")
db.close()
