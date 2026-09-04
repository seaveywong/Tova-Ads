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

# /me/adaccounts 拉取字段：FbClient.get_ad_accounts 的字段表不含 disable_reason（禁用原因
# 副行要落库），且 fb_client 不在本模块改动管辖——故此处显式声明全量字段，
# routers/fb.py 的 refresh-accounts/_bg_complete_imported 复用同一常量防两处漂移。
ADACCOUNT_SYNC_FIELDS = ("account_id,account_status,disable_reason,name,currency,"
                         "timezone_name,balance,spend_cap,amount_spent")


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


def _balance_alert_threshold(db) -> float:
    """低额告警阈值（USD）：system_settings.balance_alert_threshold（JSON 数字，默认 20；0=关闭）。"""
    try:
        from ..models.system import SystemSetting
        row = db.query(SystemSetting).filter(SystemSetting.key == "balance_alert_threshold").first()
        if row and row.value not in (None, ""):
            return float(json.loads(row.value))
    except Exception:
        pass
    return 20.0


def _maybe_low_balance_alert(db, tenant_id: int, acc, threshold_usd: float) -> bool:
    """账户可用额度 < 阈值 → 告警（6h dedup，notify_utils 兜文案/TG）。

    口径与看板一致（guard_engine.calc_available_balance）：
    - 有花费上限：可用 = spend_cap − amount_spent（USD）
    - 无上限：退回 FB balance（>0 视为预付费余额；≤0 时若有已消耗按"预付费耗尽"告警
      avail=0（P1-6 修复：原口径一律不判，预付费账户烧干后静默停投无人知），纯零消耗不判）
    """
    from .guard_engine import calc_available_balance, from_minor_units, to_usd
    from ..core.notify_utils import emit_low_balance_alert_if_due
    avail_usd, kind = calc_available_balance(acc.spend_cap, acc.amount_spent, acc.currency)
    basis = "spend_cap"
    if kind != "limited":
        bal = from_minor_units(acc.balance, acc.currency)
        if bal is None or bal <= 0:
            # P1-6 预付费耗尽静默：balance≤0 无法区分"后付费账单/欠款"与"预付费烧干"，
            # 保守口径=无花费上限（kind=unlimited，即 spend_cap 空）且已有消耗（amount_spent>0）
            # → 按预付费耗尽告警（avail=0，复用 low_balance_prepaid 文案）。
            # very_high_limit（spend_cap≥$1M）仍不判——它有上限，不属预付费形态。
            # 后付费账户零余额也会撞进来：宁可多告不静默，6h dedup 控频。
            if kind == "unlimited" and (from_minor_units(acc.amount_spent, acc.currency) or 0) > 0:
                return emit_low_balance_alert_if_due(
                    db, tenant_id, act_id=acc.act_id, name=acc.name,
                    avail_usd=0.0, threshold_usd=threshold_usd, basis="prepaid_balance")
            return False
        _tu = to_usd(bal, acc.currency)   # to_usd 未知币种返 None（复审A P2）——round(None) 会 TypeError，被外层吞掉后低额告警永远发不出
        avail_usd, basis = (round(_tu, 2) if _tu is not None else None), "prepaid_balance"
    if avail_usd is not None and avail_usd < threshold_usd:
        return emit_low_balance_alert_if_due(
            db, tenant_id, act_id=acc.act_id, name=acc.name,
            avail_usd=avail_usd, threshold_usd=threshold_usd, basis=basis)
    return False


# TT advertiser status（Business API advertiser/info/ 的 status）→ account_status（FB 语义：
# 1 正常 / 2 禁用 / 7 政策受限；异常判定沿用 STATUS_ABNORMAL 集合，恢复=回到 1）。
# ⚠ sandbox 未实测：按 TikTok 官方文档枚举语义映射，首次真跑如与实际返回不符在此校准；
# 未收录枚举不动状态（防未知值 flap），只记 info 日志留痕。
TT_STATUS_MAP = {
    "STATUS_ENABLE": 1,
    "STATUS_DISABLE": 2,           # 禁用/被关
    "STATUS_LIMIT_LOGIN": 2,       # 登录受限
    "STATUS_RESTRICT": 7,          # 受限（政策类），对齐 FB 7=政策违规
    "STATUS_PENDING_CONFIRM": 2,   # 待确认（未过审不能投）
    "STATUS_PENDING_VERIFIED": 2,
    "STATUS_CONFIRM_FAIL": 2,
    "STATUS_SELF_SERVICE_UNAUDITED": 2,
    "STATUS_CONTRACT_PAYMENT_UNAUDITED": 2,
    "STATUS_WAIT_FOR_BPM_AUDIT": 2,
    "STATUS_WAIT_FOR_PUBLIC_AUTH": 2,
    "STATUS_WAIT_FOR_LEGAL_REPRESENTATIVE_AUTH": 2,
}
TT_STATUS_LABELS = {1: "正常", 2: "禁用", 7: "受限"}
TT_STATUS_ADVICE = {
    2: "TikTok 广告主已被禁用或未过审，请到 TikTok 后台查看原因。",
    7: "账户被 TikTok 限制投放，请检查广告内容或申诉。",
}


def _sync_tt_accounts(db) -> tuple[int, int, int]:
    """同步 managed TT 账户（状态/余额/币种/时区）+ 异常/恢复告警（事件同款 account_status_change）。

    余额口径照 FB：acc.balance 存 minor-units 字符串（TT API 返本币明文 → ×_money_factor
    入库），既有读路径（from_minor_units / calc_available_balance / 看板展示）零改动；
    USD 换算沿用 to_usd（CurrencyRate）。TT 无 spend_cap/amount_spent 对应字段，不写；
    低额告警本批不接（balance 字段语义 sandbox 校准后再开）。
    一次事件只告一次（_last_notified_status 同款去重）+ 恢复告知，照 FB 链。
    返回 (synced, alerted, recovered)。
    """
    from ..core.fb_tokens import tt_client_for_account
    from .guard_engine import _money_factor
    tt_accs = db.query(Account).filter(
        Account.platform == "tt",
        Account.is_managed.is_(True),
    ).all()
    synced = alerted = recovered = 0
    for acc in tt_accs:
        try:
            tt, _cred = tt_client_for_account(db, acc.tenant_id, acc.act_id, "read")
            if not tt:
                continue
            info = tt.get_advertiser_info(acc.act_id) or {}
            if info.get("currency") and info["currency"] != acc.currency:
                acc.currency = info["currency"]
            if info.get("timezone"):
                acc.timezone_name = info["timezone"]
            try:
                _factor = _money_factor(acc.currency or "USD")
                acc.balance = str(int(round(float(info.get("balance") or 0) * _factor)))
            except (TypeError, ValueError):
                pass  # balance 缺失/非数值（sandbox 差异）→ 不动
            raw_status = str(info.get("status") or "").upper()
            new_status = TT_STATUS_MAP.get(raw_status)
            if new_status is None:
                if raw_status:
                    logger.info(f"[AccountSync][TT] 账户 {acc.act_id} 未收录状态枚举: {raw_status}")
            else:
                old_status = acc.account_status or 1
                if old_status != new_status:
                    if new_status in STATUS_ABNORMAL:
                        # 进入异常：仅"新状态 ≠ 上次已告状态"时告（同 FB：同状态不重报）
                        if _last_notified_status(db, acc.tenant_id, acc.act_id) != new_status:
                            old_label = STATUS_LABELS.get(old_status, str(old_status))
                            new_label = TT_STATUS_LABELS.get(new_status, str(new_status))
                            try:
                                emit_notification(
                                    db, tenant_id=acc.tenant_id, level="critical",
                                    event_type="account_status_change",
                                    title=f"账户状态变动 · {acc.name}",
                                    body=(f"账户：{acc.name}（TikTok {acc.act_id}）\n"
                                          f"状态：<b>{old_label} → {new_label}</b>（{raw_status}）\n"
                                          f"{TT_STATUS_ADVICE.get(new_status, '')}"),
                                    roles=["owner", "operator"], trace_id=new_trace_id(),
                                    target_type="account", target_id=acc.act_id,
                                    platform=(acc.platform or "fb"),
                                )
                            except Exception as e:
                                logger.warning(f"[AccountSync][TT] 告警发送失败 act {acc.act_id}: {e}")
                            write_log(db, tenant_id=acc.tenant_id, trace_id=new_trace_id(),
                                      actor_type="system", target_type="account", target_id=acc.act_id,
                                      action_type="account_status_change", source="account_sync",
                                      result="alerted", platform="tt",
                                      trigger_detail=f"old={old_status} new={new_status} tt_status={raw_status}",
                                      metadata={"status": new_status, "old": old_status,
                                                "platform": "tt", "tt_status": raw_status})
                            alerted += 1
                    elif new_status == 1 and old_status in STATUS_ABNORMAL:
                        # 恢复正常：告知一次 + 写 status=1（使再异常能再告，同 FB）
                        old_label = STATUS_LABELS.get(old_status, str(old_status))
                        try:
                            emit_notification(
                                db, tenant_id=acc.tenant_id, level="info",
                                event_type="account_status_recovered",
                                title=f"账户已恢复 · {acc.name}",
                                body=(f"账户：{acc.name}（TikTok {acc.act_id}）\n"
                                      f"状态：<b>{old_label} → 正常</b>（{raw_status}）\n账户已恢复正常。"),
                                roles=["owner", "operator"], trace_id=new_trace_id(),
                                target_type="account", target_id=acc.act_id,
                                platform="tt")
                        except Exception as e:
                            logger.warning(f"[AccountSync][TT] 恢复告警发送失败 act {acc.act_id}: {e}")
                        write_log(db, tenant_id=acc.tenant_id, trace_id=new_trace_id(),
                                  actor_type="system", target_type="account", target_id=acc.act_id,
                                  action_type="account_status_change", source="account_sync",
                                  result="recovered", platform="tt",
                                  trigger_detail=f"old={old_status} new=1 tt_status={raw_status}",
                                  metadata={"status": 1, "old": old_status, "recovered": True,
                                            "platform": "tt", "tt_status": raw_status})
                        recovered += 1
                acc.account_status = new_status
            synced += 1
            if synced % 25 == 0:
                db.commit()
        except Exception as e:
            # 单账户异常不阻断其他 TT 账户（照 FB per-account 容错）
            logger.warning(f"[AccountSync][TT] 账户 {acc.act_id} 处理异常: {e}")
            db.rollback()
            continue
    return synced, alerted, recovered


def run_account_status_sync():
    """定时同步账户状态/余额，变动到异常 → emit 告警。每 30min。"""
    lock = acquire_run_lock(110)
    if not lock:
        return {"skipped": "lock_busy"}
    db = SuperSessionLocal()
    synced = alerted = recovered = 0
    low_balance_alerts = 0
    threshold_usd = _balance_alert_threshold(db)  # 0=关；一次巡检读一遍
    try:
        creds = db.query(FbCredential).filter(FbCredential.status == "active").all()
        for cred in creds:
            tenant_id = cred.tenant_id
            try:
                fb = FbClient(decrypt(cred.access_token_enc))
                # 带 disable_reason 的全量字段（见 ADACCOUNT_SYNC_FIELDS 注释）
                raw_accounts = fb.get_paged("me/adaccounts", {"fields": ADACCOUNT_SYNC_FIELDS})
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
                # 禁用原因落库（FB 官方数字枚举；显式判 None——0=恢复正常是合法值，
                # or 兜底会跳过导致旧原因残留，前端副行就永远清不掉）
                _dr = raw.get("disable_reason")
                if _dr is not None:
                    acc.disable_reason = int(_dr)
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
                                platform=(acc.platform or "fb"))
                        except Exception as e:
                            logger.warning(f"[AccountSync] 恢复告警发送失败 act {act_id}: {e}")
                        write_log(db, tenant_id=tenant_id, trace_id=new_trace_id(),
                                  actor_type="system", target_type="account", target_id=act_id,
                                  action_type="account_status_change", source="account_sync",
                                  result="recovered", trigger_detail=f"old={old_status} new=1",
                                  metadata={"status": 1, "old": old_status, "recovered": True})
                        recovered += 1
                acc.account_status = new_status
                # 可用额度低告警（仅活跃账户；阈值 balance_alert_threshold，0=关；6h dedup）
                if threshold_usd > 0 and new_status == 1:
                    try:
                        if _maybe_low_balance_alert(db, tenant_id, acc, threshold_usd):
                            low_balance_alerts += 1
                    except Exception as e:
                        logger.warning(f"[AccountSync] 低额告警检查失败 act {act_id}: {e}")
                # 同步该账户像素到像素库（绑 act_id，子码级像素用）
                try:
                    sync_pixels_for_act(db, fb, tenant_id, act_id)
                except Exception:
                    pass
                synced += 1
                # 每 25 个账户提交一次——中途异常不再丢掉已处理账户的余额/状态更新
                if synced % 25 == 0:
                    db.commit()
              except Exception as e:
                # 单账户异常不阻断同 cred 其他账户同步（照搬巡检 per-account 容错）
                logger.warning(f"[AccountSync] 账户 {raw.get('account_id','')} 处理异常: {e}")
                db.rollback()
                continue
        # ── TT 账户（P1-9）：advertiser/info 拉状态/余额/币种/时区；异常/恢复告警链同款 FB ──
        # 整段 try 包裹：TT 侧异常不影响 FB 已完成的同步提交
        try:
            _t_synced, _t_alerted, _t_recovered = _sync_tt_accounts(db)
            synced += _t_synced
            alerted += _t_alerted
            recovered += _t_recovered
        except Exception as e:
            logger.warning(f"[AccountSync][TT] 同步异常: {e}")
            db.rollback()
        db.commit()
        logger.info(f"[AccountSync] 同步 {synced} 账户，{alerted} 异常告警，{recovered} 恢复，{low_balance_alerts} 低额告警")
    finally:
        db.close()
        release_run_lock(lock, 110)
    return {"synced": synced, "alerted": alerted, "low_balance_alerts": low_balance_alerts}
