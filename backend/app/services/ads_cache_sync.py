"""广告实体缓存同步（定时拉 campaigns/adsets → ads_cache，广告管理器读缓存跨账户汇总，0 FB）。

独立 job（15min）。批AF 起 FB 三层（campaigns/adsets/ads）全部由巡检 5min 顺带回写
（同成本换 5min 新鲜 + 并发自愈），本 cron 只剩 TT（TT 无巡检回写，恒拉三层）与
无令牌账户的停更告警探测。
"""
import logging
from sqlalchemy import or_
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
            Account.is_managed == True,  # noqa: E712
            # 死状态集与巡检同口径（全库审查 P2：受限7/未结清3/宽限9 仍投放须覆盖；
            # 曾 ==1 把这些账户的实体同步排除成盲区）
            or_(Account.account_status.is_(None),
                Account.account_status.notin_([2, 8, 100, 101])),
        ).all()
        updated = 0
        _no_token: dict[int, int] = {}  # tenant_id → 无令牌纳管账户数（停更告警用）
        for acc in accounts:
            platform = _acc_platform(acc)
            client = client_for_account(db, acc.tenant_id, acc.act_id, "read")
            if client is None:
                _no_token[acc.tenant_id] = _no_token.get(acc.tenant_id, 0) + 1
                continue
            if platform != "tt":
                # 批AF：FB 三层已由巡检 5min 顺带供数（结构层同 5min 刷新）——这里再拉是纯冗余，
                # 跳过（本 cron 对 FB 只剩上面 client 探测贡献的停更告警输入）
                continue
            try:
                if _sync_one(db, acc.tenant_id, acc.act_id, client,
                             platform=platform, currency=(acc.currency or "USD"),
                             include_ads=False):
                    updated += 1
                else:
                    logger.warning(f"[AdsCache] 账户 {acc.act_id}（{platform}）拉取失败")
            except Exception as e:
                logger.warning(f"[AdsCache] 账户 {acc.act_id}（{platform}）同步异常: {e}")
                continue
        db.commit()
        logger.info(f"[AdsCache] 同步完成: {updated} 个账户")
        # 停更告警：纳管账户全都没有可用令牌 → 数据静默停更（2026-09 发现停 19 天无人知）。
        # 每租户 24h 去重一条 critical（P0-8：warning→critical——无令牌期间巡检读不到广告数据，
        # 止损规则/哨兵不会执行=止损失效，是最需要立即处理的信号）；有令牌正常更新的租户不收。
        if _no_token:
            from ..core.notify_utils import emit_notification, dedup_recent
            from ..core.i18n import notify_text, tenant_locale
            for tid, n in _no_token.items():
                if dedup_recent(db, tid, "sync_stalled", "ads_cache", 24 * 60):   # 参数是分钟——曾写 24*3600=60 天，critical 发一条静默俩月（复审A P2）
                    continue
                _loc = tenant_locale(db, tid)
                _title, _body = notify_text(_loc, "sync_stalled", n=n)
                emit_notification(db, tenant_id=tid, level="critical",
                                  event_type="sync_stalled",
                                  title=_title, body=_body)
                # dedup_recent 查 action_logs——emit 后必须写 log，下次才会命中去重
                from ..core.log_utils import write_log, new_trace_id
                write_log(db, tenant_id=tid, trace_id=new_trace_id(),
                          actor_type="system", target_type="sync", target_id="ads_cache",
                          action_type="sync_stalled", source="ads_cache_sync",
                          result="fail", trigger_detail=f"no-token accounts: {n}")
                db.commit()
        return {"updated": updated}
    except Exception as e:
        logger.error(f"[AdsCache] 异常: {e}", exc_info=True)
        return {"error": str(e)}
    finally:
        db.close()
        release_run_lock(lock, 111)
