"""广告写操作服务（对齐 1.0 services/ad_ops.py 成熟机制）。

三层并发保护（PG advisory lock）+ 权限错误中文快失败 + 回读验证 + minor units 换算 + 缓存 patch + 审计。
写操作绑死账户 token（client_for_account op_kind="write"），不轮换（防孤儿）。
"""
import time
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from ..core.database import SuperSessionLocal, acquire_run_lock, release_run_lock
from ..core.fb_client import FbClient, FbApiError
from ..core.fb_tokens import cred_for_account_op
from ..core.encryption import decrypt
from ..core.log_utils import write_log, new_trace_id
from ..models.fb import Account, FbCredential
from ..models.ads_cache import AdsCache
from ..services.guard_engine import from_minor_units, to_usd

logger = logging.getLogger("toveads.ad_ops")

# 零小数货币（同 guard_engine，FB 存整数）
_NO_DECIMAL = {"JPY", "KRW", "IDR", "VND", "CLP", "COP", "HUF", "PYG", "UGX", "TZS"}

# 状态字段（ad/adset/campaign 通用）
_LEVEL_FIELDS = {
    "ad": "id,name,status,effective_status,configured_status",
    "adset": "id,name,status,effective_status,configured_status,daily_budget,lifetime_budget",
    "campaign": "id,name,status,effective_status,configured_status,daily_budget,lifetime_budget",
}


def _to_minor(amount: float, currency: str) -> str:
    """本币金额 → FB minor units 字符串（USD: 50→'5000'; VND: 50000→'50000'）。"""
    factor = 1 if (currency or "USD").upper() in _NO_DECIMAL else 100
    return str(int(round(amount * factor)))


def _classify_write_error(e: FbApiError) -> str:
    """FB 写错误 → 中文 actionable（权限类不轮换 token，直接抛）。"""
    if not e.raw:
        return str(e.friendly)
    code = e.raw.get("error_subcode") or e.raw.get("code", 0)
    msg = (e.raw.get("message") or "").lower()
    if code == 33 or "account_id" in msg:
        return "操作号对该广告账户无写权限——请在 BM 给系统用户授予 Advertiser/管理权限"
    if code == 1487202 or "page" in msg:
        return "操作号对该主页无广告权限——请在 BM 主页设置里给系统用户授权"
    if code in (10, 200, 294) or "permission" in msg or "authorization" in msg:
        return "操作号权限不足，请在 BM 授权后重试"
    if code == 1487067:
        return "预算金额无效（过低或超出范围）"
    return e.friendly


def _patch_cache_status(db: Session, tenant_id: int, act_id: str, node_id: str,
                        level: str, new_status: str, new_effective: str):
    """写后 patch ads_cache JSON（避免等 15min 同步才看到变更）。"""
    row = db.query(AdsCache).filter(
        AdsCache.tenant_id == tenant_id, AdsCache.act_id == act_id).first()
    if not row:
        return
    import json
    for field, key in [("campaigns_json", "id"), ("adsets_json", "id"), ("ads_json", "id")]:
        raw = getattr(row, field)
        if not raw:
            continue
        try:
            items = json.loads(raw)
            changed = False
            for it in items:
                if it.get(key) == node_id or str(it.get(key)) == str(node_id):
                    it["status"] = new_status
                    it["effective_status"] = new_effective
                    it["configured_status"] = new_status
                    changed = True
            if changed:
                setattr(row, field, json.dumps(items))
        except Exception:
            pass


def _patch_cache_budget(db: Session, tenant_id: int, act_id: str, node_id: str,
                        daily_budget_minor: str = None, lifetime_minor: str = None):
    """写后 patch ads_cache 预算字段（daily / lifetime 二选一）。"""
    row = db.query(AdsCache).filter(
        AdsCache.tenant_id == tenant_id, AdsCache.act_id == act_id).first()
    if not row:
        return
    import json
    for field in ["campaigns_json", "adsets_json"]:
        raw = getattr(row, field)
        if not raw:
            continue
        try:
            items = json.loads(raw)
            changed = False
            for it in items:
                if it.get("id") == node_id or str(it.get("id")) == str(node_id):
                    if daily_budget_minor:
                        it["daily_budget"] = daily_budget_minor
                    if lifetime_minor:
                        it["lifetime_budget"] = lifetime_minor
                    changed = True
            if changed:
                setattr(row, field, json.dumps(items))
        except Exception:
            pass


def set_status(db: Session, tenant_id: int, act_id: str, node_id: str,
               level: str, target_status: str, operator: str = "system") -> dict:
    """改广告/组/系列状态（ACTIVE/PAUSED/ARCHIVED）。

    返回 {success, verified, effective_status, warning} 或抛 HTTPException。
    """
    if target_status not in ("ACTIVE", "PAUSED", "ARCHIVED"):
        raise ValueError(f"无效状态: {target_status}")

    cred = cred_for_account_op(db, tenant_id, act_id, "write")
    if not cred:
        return {"success": False, "error": "无可用写令牌（operate/manage）"}
    fb = FbClient(decrypt(cred.access_token_enc))
    fields = _LEVEL_FIELDS.get(level, _LEVEL_FIELDS["ad"])

    # PG advisory lock（target 级，防并发写同一条）
    lock_key = abs(hash(f"ad_status:{node_id}")) % (2**31)
    lock = acquire_run_lock(lock_key)
    if not lock:
        return {"success": False, "error": "该广告正在被其他操作处理"}

    try:
        # 读旧值
        before = fb.get_node(node_id, fields)
        # 写
        fb.update_status(node_id, target_status)
        time.sleep(0.8)
        # 回读验证
        after = fb.get_node(node_id, fields)
        verified = after.get("status") == target_status
        eff = after.get("effective_status", "")
        warning = ""
        if target_status == "ACTIVE" and after.get("status") == "ACTIVE" and eff != "ACTIVE":
            warning = f"状态已设为 ACTIVE 但 effective_status={eff}（父级或账户可能仍在暂停）"

        # patch cache
        _patch_cache_status(db, tenant_id, act_id, node_id, level, target_status, eff)
        db.commit()

        # 审计（用 SuperSessionLocal 绕 RLS——用户触发但系统记录，actor_user_id=0 在 RLS 下被拒）
        _sdb = SuperSessionLocal()
        try:
            write_log(_sdb, tenant_id=tenant_id, trace_id=new_trace_id(),
                      actor_type="user", actor_user_id=0,
                      target_type="ad", target_id=node_id,
                      action_type=f"manual_{target_status.lower()}",
                      source="ad_ops", result="success" if verified else "partial",
                      trigger_detail=f"level={level} old={before.get('status')} new={target_status} eff={eff}")
            _sdb.commit()
        finally:
            _sdb.close()
        return {"success": True, "verified": verified, "effective_status": eff, "warning": warning}
    except FbApiError as e:
        return {"success": False, "error": _classify_write_error(e), "fb_error": e.friendly}
    finally:
        release_run_lock(lock, lock_key)


def set_budget(db: Session, tenant_id: int, act_id: str, node_id: str,
               level: str, daily_budget: float = None, currency: str = "USD",
               operator: str = "system", budget_type: str = "daily",
               lifetime_budget: float = None) -> dict:
    """改预算（本币金额 → minor units）。

    budget_type='daily' 改日预算；'lifetime' 改总预算。两者择一：显式传值优先于 budget_type。
    对象当前用的预算类型必须匹配（lifetime 对象不能塞 daily，反之亦然）。
    """
    # 解析目标类型 + 金额：显式金额 > budget_type
    if lifetime_budget is not None and lifetime_budget > 0:
        btype, amount = "lifetime", lifetime_budget
    elif daily_budget is not None and daily_budget > 0:
        btype, amount = "daily", daily_budget
    else:
        return {"success": False, "error": "预算必须大于 0"}
    if budget_type not in ("daily", "lifetime"):
        budget_type = btype

    cred = cred_for_account_op(db, tenant_id, act_id, "write")
    if not cred:
        return {"success": False, "error": "无可用写令牌（operate/manage）"}
    fb = FbClient(decrypt(cred.access_token_enc))
    fields = _LEVEL_FIELDS.get(level, _LEVEL_FIELDS["adset"])

    lock_key = abs(hash(f"ad_budget:{node_id}")) % (2**31)
    lock = acquire_run_lock(lock_key)
    if not lock:
        return {"success": False, "error": "该广告正在被其他操作处理"}

    try:
        before = fb.get_node(node_id, fields)
        has_daily = bool(before.get("daily_budget"))
        has_lifetime = bool(before.get("lifetime_budget"))
        # 类型不匹配：daily 对象塞 lifetime（或反之）拒改，避免 FB 静默改类型
        if btype == "lifetime" and has_daily and not has_lifetime:
            return {"success": False, "error": "该对象使用日预算，不支持改总预算"}
        if btype == "daily" and has_lifetime and not has_daily:
            return {"success": False, "error": "该对象使用总预算(lifetime)，不支持改日预算"}

        minor = _to_minor(amount, currency)
        if btype == "lifetime":
            fb.update_budget(node_id, lifetime_budget=minor)
        else:
            fb.update_budget(node_id, daily_budget=minor)
        time.sleep(0.8)
        after = fb.get_node(node_id, fields)
        verified_field = "lifetime_budget" if btype == "lifetime" else "daily_budget"
        verified = str(after.get(verified_field)) == minor

        _patch_cache_budget(db, tenant_id, act_id, node_id,
                           daily_budget_minor=minor if btype == "daily" else None,
                           lifetime_minor=minor if btype == "lifetime" else None)
        db.commit()

        _sdb = SuperSessionLocal()
        try:
            write_log(_sdb, tenant_id=tenant_id, trace_id=new_trace_id(),
                      actor_type="user", actor_user_id=0,
                      target_type="ad", target_id=node_id,
                      action_type="manual_budget",
                      source="ad_ops", result="success" if verified else "partial",
                      trigger_detail=f"level={level} type={btype} old={before.get(verified_field)} new={minor}")
            _sdb.commit()
        finally:
            _sdb.close()
        return {"success": True, "verified": verified,
                "budget_type": btype, "budget_minor": minor}
    except FbApiError as e:
        return {"success": False, "error": _classify_write_error(e), "fb_error": e.friendly}
    finally:
        release_run_lock(lock, lock_key)


def delete_node(db: Session, tenant_id: int, act_id: str, node_id: str,
                operator: str = "system") -> dict:
    """硬删节点（DELETE /{id}，不可恢复）。"""
    cred = cred_for_account_op(db, tenant_id, act_id, "write")
    if not cred:
        return {"success": False, "error": "无可用写令牌（operate/manage）"}
    fb = FbClient(decrypt(cred.access_token_enc))

    lock_key = abs(hash(f"ad_delete:{node_id}")) % (2**31)
    lock = acquire_run_lock(lock_key)
    if not lock:
        return {"success": False, "error": "该广告正在被其他操作处理"}

    try:
        fb.delete_node(node_id)
        # patch cache：从 ads_cache JSON 中移除该节点
        row = db.query(AdsCache).filter(
            AdsCache.tenant_id == tenant_id, AdsCache.act_id == act_id).first()
        if row:
            import json
            for field in ["campaigns_json", "adsets_json", "ads_json"]:
                raw = getattr(row, field)
                if not raw:
                    continue
                try:
                    items = json.loads(raw)
                    filtered = [it for it in items if it.get("id") != node_id and str(it.get("id")) != str(node_id)]
                    if len(filtered) != len(items):
                        setattr(row, field, json.dumps(filtered))
                except Exception:
                    pass
        db.commit()
        _sdb = SuperSessionLocal()
        try:
            write_log(_sdb, tenant_id=tenant_id, trace_id=new_trace_id(),
                      actor_type="user", actor_user_id=0,
                      target_type="ad", target_id=node_id,
                      action_type="manual_delete",
                      source="ad_ops", result="success")
            _sdb.commit()
        finally:
            _sdb.close()
        return {"success": True}
    except FbApiError as e:
        return {"success": False, "error": _classify_write_error(e), "fb_error": e.friendly}
    finally:
        release_run_lock(lock, lock_key)
