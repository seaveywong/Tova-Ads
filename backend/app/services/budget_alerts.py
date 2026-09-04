"""预算进度告警（doc 03 §3.10 / 审计项目21）。

日预算 adset 今日消耗跨 tier [98/90/75/50]% → 告警（不改预算）。
触发条件：progress > 50% + 今日未告警过该 tier + 近 1h 未 pause。
dedup：action_logs(action_type=budget_progress_alert, target_id=adset_id, trigger_detail=tier=N, 今日)。
纯告警，不自动改预算（v1 与"不做自动调预算"一致）。
"""
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from sqlalchemy.orm import Session
from ..core.fb_client import FbClient, FbApiError
from ..core.log_utils import write_log, new_trace_id
from ..core.notify_utils import emit_notification, emit_token_expired_if_due
from ..core.i18n import tenant_locale, notify_text
from ..core.database import SuperSessionLocal, acquire_run_lock, release_run_lock
from ..core.encryption import decrypt
from ..core.fb_tokens import client_for_account, cred_for_account_op
from ..models.fb import FbCredential, Account
from ..models.log import ActionLog
from .guard_engine import from_minor_units

logger = logging.getLogger("toveads.budget")

# tier 高→低（progress 跨过的最高档）
BUDGET_TIERS = [98, 90, 75, 50]


def _local_day_start_utc(acc: Account) -> datetime:
    """账户本地今日 00:00 对应的 UTC 时刻（dedup 窗口用，与"今日消耗"同口径）。
    timezone_name 如 Asia/Ho_Chi_Minh；异常退 UTC 当日零点。"""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(acc.timezone_name or "UTC")
        return datetime.now(tz).replace(
            hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0)


def check_account_budget_progress(
    db: Session, tenant_id: int, fb: FbClient, acc: Account, trace_id: str
) -> list[dict]:
    """单账户预算进度告警。返回触发的告警列表。"""
    # dedup 窗口 = 账户本地今日 00:00（转 UTC）：与"今日消耗"同口径——
    # 本地日一过各 tier 重新可告；不再用滚动 24h（旧口径会把昨日已告的 tier 拖进今日压制）
    today_start_utc = _local_day_start_utc(acc)

    try:
        adsets = fb.get_adsets(acc.act_id)
        spend_map = {i.get("adset_id"): float(i.get("spend", 0))
                     for i in fb.get_adset_insights(acc.act_id, "today")}
    except FbApiError as e:
        logger.warning(f"[Budget] 账户 {acc.act_id} 读取失败: {e.friendly}")
        if e.category == "token_expired":
            # 按凭证 dedup（cred_id 优先）：多令牌同晚全灭各告各的，不被第一条压制
            _cred = cred_for_account_op(db, tenant_id, acc.act_id, "read")
            emit_token_expired_if_due(db, tenant_id, f"act_{acc.act_id}",
                                      cred_id=(_cred.id if _cred else None))
        return []

    alerts = []
    for ad in adsets:
        if (ad.get("effective_status") or "").upper() != "ACTIVE":
            continue
        daily = ad.get("daily_budget")
        if not daily:
            continue  # 非日预算（lifetime/无预算）跳过
        # FB API 金额字段是 minor units（多数币种=分；JPY/KRW/VND 等零小数位
        # 币种=本币整数），与 insights spend（主币）对比前必须换算，否则 progress 虚高
        budget = from_minor_units(daily, acc.currency)
        if not budget or budget <= 0:
            continue

        adset_id = ad["id"]
        adset_name = (ad.get("name") or adset_id)[:50]
        spend = spend_map.get(adset_id, 0.0)
        progress = spend / budget * 100
        if progress <= 50:
            continue  # doc 03：progress > 50% 才告警

        # 近 1h 是否 pause 过该 adset（避免刚停又告警）
        since_1h = datetime.now(timezone.utc) - timedelta(hours=1)
        recent_pause = db.query(ActionLog).filter(
            ActionLog.tenant_id == tenant_id,
            ActionLog.target_id == adset_id,
            ActionLog.action_type == "pause",
            ActionLog.created_at >= since_1h,
        ).first()
        if recent_pause:
            continue

        # 找跨过的最高 tier
        for tier in BUDGET_TIERS:
            if progress < tier:
                continue
            # dedup：今日该 tier 告警过？
            already = db.query(ActionLog).filter(
                ActionLog.tenant_id == tenant_id,
                ActionLog.target_id == adset_id,
                ActionLog.action_type == "budget_progress_alert",
                ActionLog.trigger_detail == f"tier={tier}",
                ActionLog.created_at >= today_start_utc,
            ).first()
            if already:
                break  # 该 tier 今日已告警 → 不再告警（也不降档）

            # 触发告警
            remaining = budget - spend
            _loc = tenant_locale(db, tenant_id)
            _title, _body = notify_text(_loc, "budget_progress",
                progress=progress, tier=tier, adset_name=adset_name, acc_name=acc.name,
                budget=budget, currency=acc.currency, spend=spend, remaining=remaining)
            write_log(db, tenant_id=tenant_id, trace_id=trace_id, actor_type="system",
                      target_type="adset", target_id=adset_id,
                      action_type="budget_progress_alert", source="scheduled", result="success",
                      trigger_type=f"budget_progress_{tier}", trigger_detail=f"tier={tier}",
                      metadata={"act_id": acc.act_id, "progress": round(progress, 1),
                                "spend": spend, "budget": budget})
            # 98% 档升级 critical（TG 必达语义：预算几乎烧完，最后一道提醒）；文案不变
            emit_notification(db, tenant_id=tenant_id,
                              level=("critical" if tier >= 98 else "warning"),
                              event_type=f"budget_progress_{tier}", trace_id=trace_id,
                              title=_title, body=_body,
                              target_type="adset", target_id=adset_id,
                              platform=(acc.platform or "fb"))
            alerts.append({"adset_id": adset_id, "tier": tier,
                           "progress": round(progress, 1), "spend": spend, "budget": budget})
            break  # 一次只告最高档

    if alerts:
        db.commit()
    return alerts


def run_budget_alerts():
    """定时入口：遍历所有有 FB 凭证的租户 → 每账户检查预算进度。advisory lock 防多 worker 重复。"""
    lock = acquire_run_lock(102)
    if not lock:
        return {"skipped": "lock_busy"}
    db = SuperSessionLocal()
    trace_id = new_trace_id()
    total_alerts = 0
    try:
        tenant_ids = db.execute(text(
            "SELECT DISTINCT tenant_id FROM fb_credentials WHERE status = 'active'"
        )).fetchall()
        for (tenant_id,) in tenant_ids:
            creds = db.query(FbCredential).filter(
                FbCredential.tenant_id == tenant_id, FbCredential.status == "active"
            ).all()
            if not creds:
                continue
            accounts = db.query(Account).filter(
                Account.tenant_id == tenant_id, Account.account_status == 1,
                Account.is_managed.is_(True),
            ).all()
            for acc in accounts:
                # 按账户选 client（查 cooldown + RR 兜底）；全灭 → 跳过
                fb = client_for_account(db, tenant_id, acc.act_id, "read")
                if fb is None:
                    continue
                try:
                    alerts = check_account_budget_progress(db, tenant_id, fb, acc, trace_id)
                    total_alerts += len(alerts)
                except Exception as e:
                    logger.warning(f"[Budget] 账户 {acc.act_id} 异常: {e}")
        logger.info(f"[Budget] 预算进度巡检完成: {total_alerts} 条告警 (trace={trace_id})")
        return {"alerts": total_alerts, "trace_id": trace_id}
    except Exception as e:
        logger.error(f"[Budget] 异常: {e}", exc_info=True)
        return {"error": str(e)}
    finally:
        db.close()
        release_run_lock(lock, 102)
