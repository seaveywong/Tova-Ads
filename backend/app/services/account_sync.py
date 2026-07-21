"""账户状态/余额定时同步 + 变动告警（照搬 1.0 scheduler.py:255-297，适配 2.0 emit_notification）。

每 30min 拉 FB /me/adaccounts → 更新 account_status/balance/spend_cap/amount_spent/currency/timezone_name。
状态变为异常（2/3/7/9/100/101）→ emit_notification critical（站内信 + TG）。
"""
import json
import logging
from ..core.database import SuperSessionLocal, acquire_run_lock, release_run_lock
from ..core.encryption import decrypt
from ..core.fb_client import FbClient, FbApiError
from ..core.notify_utils import emit_notification
from ..core.log_utils import new_trace_id, write_log
from ..models.fb import FbCredential, Account
from ..models.log import ActionLog
from ..routers.landing_lib import sync_pixels_for_act

logger = logging.getLogger("toveads.account_sync")

STATUS_ABNORMAL = {2, 3, 7, 9, 100, 101}
STATUS_LABELS = {1: "正常", 2: "禁用", 3: "支付失败", 7: "政策违规",
                 8: "待结算", 9: "宽限期", 100: "待关闭", 101: "已关闭"}
STATUS_ADVICE = {
    2: "账户已被 Meta 标记为禁用，前端将禁止铺广告。",
    3: "请检查付款方式，及时充值或更换信用卡。",
    7: "账户因违反政策被限制，请检查广告内容。",
    9: "账户处于宽限期，请检查付款或账户状态。",
    100: "账户处于待关闭状态，请勿继续铺广告。",
    101: "账户已关闭或停用，请勿继续铺广告。",
}


def _last_notified_status(db, tenant_id: int, act_id: str):
    """该账户最近一次状态告警记录的状态（action_logs.metadata.status）。

    一次事件只告一次：停在同一个异常状态不重报，恢复正常(写 status=1)后再次异常才重报，
    或变成另一种异常（2→3）才重报。无记录返 None。
    """
    row = db.query(ActionLog).filter(
        ActionLog.tenant_id == tenant_id,
        ActionLog.action_type == "account_status_change",
        ActionLog.target_id == str(act_id),
    ).order_by(ActionLog.created_at.desc()).first()
    if not row:
        return None
    try:
        meta = row.metadata_ if isinstance(row.metadata_, dict) else json.loads(row.metadata_ or "{}")
        return meta.get("status")
    except Exception:
        return None


def run_account_status_sync():
    """定时同步账户状态/余额，变动到异常 → emit 告警。每 30min。"""
    lock = acquire_run_lock(107)
    if not lock:
        return {"skipped": "lock_busy"}
    db = SuperSessionLocal()
    synced = alerted = recovered = 0
    try:
        creds = db.query(FbCredential).filter(FbCredential.status == "active").all()
        for cred in creds:
            tenant_id = cred.tenant_id
            try:
                fb = FbClient(decrypt(cred.access_token_enc))
                raw_accounts = fb.get_ad_accounts()
            except FbApiError as e:
                logger.warning(f"[AccountSync] cred {cred.id} 拉 adaccounts 失败: {e.friendly}")
                continue
            except Exception as e:
                logger.warning(f"[AccountSync] cred {cred.id} 异常: {e}")
                continue
            for raw in raw_accounts:
              try:
                act_id = str(raw.get("account_id", ""))
                if not act_id:
                    continue
                acc = db.query(Account).filter(
                    Account.act_id == act_id, Account.tenant_id == tenant_id,
                    Account.is_managed.is_(True),  # 跳过已取消纳管的（不刷状态/不发恢复告警）
                ).first()
                if not acc:
                    continue
                old_status = acc.account_status or 1
                new_status = int(raw.get("account_status", 1))
                # 更新余额/上限/已花/币种/时区
                acc.balance = str(raw.get("balance", 0))
                acc.spend_cap = str(raw.get("spend_cap", 0))
                acc.amount_spent = str(raw.get("amount_spent", 0))
                if raw.get("currency"):
                    acc.currency = raw["currency"]
                if raw.get("timezone_name"):
                    acc.timezone_name = raw["timezone_name"]
                # 状态告警（一次事件只告一次 + 恢复告知）。
                # 关键：acc.account_status 始终写真值（看板/规则/哨兵看真状态），
                # 只对"告警通知"去重——停在同一个异常状态不重报，恢复正常或变成另一种异常才再告。
                if old_status != new_status:
                    if new_status in STATUS_ABNORMAL:
                        # 进入异常：仅在"新状态 ≠ 上次已告状态"时告（横跳 9↔2 / 一直停用不重报）
                        if _last_notified_status(db, tenant_id, act_id) != new_status:
                            old_label = STATUS_LABELS.get(old_status, str(old_status))
                            new_label = STATUS_LABELS.get(new_status, str(new_status))
                            try:
                                emit_notification(
                                    db, tenant_id=tenant_id, level="critical",
                                    event_type="account_status_change",
                                    title=f"账户状态变动 · {acc.name}",
                                    body=(f"账户：{acc.name}（act_{act_id}）\n"
                                          f"状态：<b>{old_label} → {new_label}</b>\n"
                                          f"{STATUS_ADVICE.get(new_status, '')}"),
                                    roles=["owner", "operator"], trace_id=new_trace_id(),
                                    target_type="account", target_id=act_id,
                                )
                            except Exception as e:
                                logger.warning(f"[AccountSync] 告警发送失败 act {act_id}: {e}")
                            write_log(db, tenant_id=tenant_id, trace_id=new_trace_id(),
                                      actor_type="system", target_type="account", target_id=act_id,
                                      action_type="account_status_change", source="account_sync",
                                      result="alerted", trigger_detail=f"old={old_status} new={new_status}",
                                      metadata={"status": new_status, "old": old_status})
                            alerted += 1
                    elif new_status == 1 and old_status in STATUS_ABNORMAL:
                        # 恢复正常：告知一次（支付失败恢复/禁用恢复）+ 写 status=1 标记，
                        # 使下次再异常时 _last_notified_status=1≠新异常 → 能再告
                        old_label = STATUS_LABELS.get(old_status, str(old_status))
                        try:
                            emit_notification(
                                db, tenant_id=tenant_id, level="info",
                                event_type="account_status_recovered",
                                title=f"账户已恢复 · {acc.name}",
                                body=(f"账户：{acc.name}（act_{act_id}）\n"
                                      f"状态：<b>{old_label} → 正常</b>\n账户已恢复正常。"),
                                roles=["owner", "operator"], trace_id=new_trace_id(),
                                target_type="account", target_id=act_id,
                            )
                        except Exception as e:
                            logger.warning(f"[AccountSync] 恢复告警发送失败 act {act_id}: {e}")
                        write_log(db, tenant_id=tenant_id, trace_id=new_trace_id(),
                                  actor_type="system", target_type="account", target_id=act_id,
                                  action_type="account_status_change", source="account_sync",
                                  result="recovered", trigger_detail=f"old={old_status} new=1",
                                  metadata={"status": 1, "old": old_status, "recovered": True})
                        recovered += 1
                acc.account_status = new_status
                # 同步该账户像素到像素库（绑 act_id，子码级像素用）
                try:
                    sync_pixels_for_act(db, fb, tenant_id, act_id)
                except Exception:
                    pass
                synced += 1
              except Exception as e:
                # 单账户异常不阻断同 cred 其他账户同步（照搬巡检 per-account 容错）
                logger.warning(f"[AccountSync] 账户 {raw.get('account_id','')} 处理异常: {e}")
                continue
        db.commit()
        logger.info(f"[AccountSync] 同步 {synced} 账户，{alerted} 异常告警，{recovered} 恢复")
    finally:
        db.close()
        release_run_lock(lock, 107)
    return {"synced": synced, "alerted": alerted}
