"""广告实体缓存同步（定时拉 campaigns/adsets/ads → ads_cache，广告管理器读缓存跨账户汇总，0 FB）。

独立 job（15min），不进巡检 5min 主循环（广告实体变化慢，降频省 API）。
"""
import json
import logging
from datetime import datetime, timezone
from ..core.database import SuperSessionLocal, acquire_run_lock, release_run_lock
from ..core.fb_tokens import client_for_account
from ..core.fb_client import FbApiError
from ..models.fb import Account
from ..models.ads_cache import AdsCache

logger = logging.getLogger("toveads.ads_cache")


def run_ads_cache_sync():
    """定时拉所有账户 campaigns/adsets/ads（全状态）→ upsert ads_cache。"""
    db = SuperSessionLocal()
    lock = acquire_run_lock(108)
    if not lock:
        db.close()
        return {"skipped": "already running"}
    try:
        accounts = db.query(Account).filter(Account.account_status == 1).all()
        updated = 0
        for acc in accounts:
            fb = client_for_account(db, acc.tenant_id, acc.act_id, "read")
            if fb is None:
                continue
            try:
                campaigns = fb.get_campaigns(acc.act_id)
                adsets = fb.get_adsets(acc.act_id, effective_status=None)
                ads = fb.get_ads(acc.act_id, effective_status=None)
            except (FbApiError, Exception) as e:
                logger.warning(f"[AdsCache] 账户 {acc.act_id} 拉取失败: {e}")
                continue
            row = db.query(AdsCache).filter(
                AdsCache.tenant_id == acc.tenant_id, AdsCache.act_id == acc.act_id,
            ).first()
            if not row:
                row = AdsCache(tenant_id=acc.tenant_id, act_id=acc.act_id)
                db.add(row)
            row.campaigns_json = json.dumps(campaigns)
            row.adsets_json = json.dumps(adsets)
            row.ads_json = json.dumps(ads)
            row.updated_at = datetime.now(timezone.utc)
            updated += 1
        db.commit()
        logger.info(f"[AdsCache] 同步完成: {updated} 个账户")
        return {"updated": updated}
    except Exception as e:
        logger.error(f"[AdsCache] 异常: {e}", exc_info=True)
        return {"error": str(e)}
    finally:
        db.close()
        release_run_lock(lock, 108)
