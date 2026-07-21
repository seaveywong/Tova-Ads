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
from ..core.database import SuperSessionLocal, acquire_run_lock, release_run_lock
from ..core.encryption import decrypt
from ..core.fb_tokens import client_for_account
from ..models.fb import FbCredential, Account
from ..models.log import ActionLog

logger = logging.getLogger("toveads.budget")

# tier 高→低（progress 跨过的最高档）
BUDGET_TIERS = [98, 90, 75, 50]


def _account_local_today(acc: Account) -> str:
    """账户本地今日（YYYY-MM-DD）。timezone_name 如 Asia/Ho_Chi_Minh。"""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(acc.timezone_name or "UTC")
        return datetime.now(tz).strftime("%Y-%m-%d")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def check_account_budget_progress(
    db: Session, tenant_id: int, fb: FbClient, acc: Account, trace_id: str
) -> list[dict]:
    """单账户预算进度告警。返回触发的告警列表。"""
    today = _account_local_today(acc)
    today_start_utc = datetime.now(timezone.utc) - timedelta(hours=24)  # dedup 窗口（粗粒度，覆盖时区差）

    try:
        adsets = fb.get_adsets(acc.act_id)
        spend_map = {i.get("adset_id"): float(i.get("spend", 0))
                     for i in fb.get_adset_insights(acc.act_id, "today")}
    except FbApiError as e:
        logger.warning(f"[Budget] 账户 {acc.act_id} 读取失败: {e.friendly}")
        if e.category == "token_expired":
            emit_token_expired_if_due(db, tenant_id, f"act_{acc.act_id}")
        return []

    alerts = []
    for ad in adsets:
        if (ad.get("effective_status") or "").upper() != "ACTIVE":
            continue
        daily = ad.get("daily_budget")
        if not daily:
            continue  # 非日预算（lifetime/无预算）跳过
        try:
            budget = float(daily)
        except (ValueError, TypeError):
            continue
        if budget <= 0:
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
            title = f"预算进度 {progress:.0f}%（{tier}% 档）"
            body = (f"广告组[{adset_name}]\n账户：{acc.name}\n"
                    f"日预算 {budget:.0f} {acc.currency} / 已消耗 {spend:.0f} ({progress:.0f}%)\n"
                    f"剩余 {remaining:.0f} {acc.currency}")
            write_log(db, tenant_id=tenant_id, trace_id=trace_id, actor_type="system",
                      target_type="adset", target_id=adset_id,
                      action_type="budget_progress_alert", source="scheduled", result="success",
                      trigger_type=f"budget_progress_{tier}", trigger_detail=f"tier={tier}",
                      metadata={"act_id": acc.act_id, "progress": round(progress, 1),
                                "spend": spend, "budget": budget})
            emit_notification(db, tenant_id=tenant_id, level="warning",
                              event_type=f"budget_progress_{tier}", trace_id=trace_id,
                              title=title, body=body,
                              target_type="adset", target_id=adset_id)
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
