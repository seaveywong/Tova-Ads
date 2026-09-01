"""广告实体缓存同步（定时拉 campaigns/adsets/ads → ads_cache，广告管理器读缓存跨账户汇总，0 FB）。

独立 job（15min），不进巡检 5min 主循环（广告实体变化慢，降频省 API）。
FB/TT 都同步（P1-5）：TT 走同一 _sync_one 平台分发——归一 FB 形状后 upsert platform='tt' 行，
两份实现不漂移。
"""
import logging
from ..core.database import SuperSessionLocal, acquire_run_lock, release_run_lock
from ..core.fb_tokens import client_for_account
from ..models.fb import Account

logger = logging.getLogger("toveads.ads_cache")


def run_ads_cache_sync():
    """定时拉所有账户（FB+TT）campaigns/adsets/ads（全状态）→ upsert ads_cache。"""
    db = SuperSessionLocal()
    lock = acquire_run_lock(111)
    if not lock:
        db.close()
        return {"skipped": "already running"}
    try:
        from ..routers.ads import _sync_one, _acc_platform  # 同一实现（FB/TT 分发），避免映射两份 drift
        accounts = db.query(Account).filter(
            Account.is_managed == True, Account.account_status == 1,  # noqa: E712
        ).all()
        updated = 0
        for acc in accounts:
            platform = _acc_platform(acc)
            client = client_for_account(db, acc.tenant_id, acc.act_id, "read")
            if client is None:
                continue
            try:
                if _sync_one(db, acc.tenant_id, acc.act_id, client,
                             platform=platform, currency=(acc.currency or "USD")):
                    updated += 1
                else:
                    logger.warning(f"[AdsCache] 账户 {acc.act_id}（{platform}）拉取失败")
            except Exception as e:
                logger.warning(f"[AdsCache] 账户 {acc.act_id}（{platform}）同步异常: {e}")
                continue
        db.commit()
        logger.info(f"[AdsCache] 同步完成: {updated} 个账户")
        return {"updated": updated}
    except Exception as e:
        logger.error(f"[AdsCache] 异常: {e}", exc_info=True)
        return {"error": str(e)}
    finally:
        db.close()
        release_run_lock(lock, 111)
