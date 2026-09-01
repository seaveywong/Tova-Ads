"""广告写操作服务（对齐 1.0 services/ad_ops.py 成熟机制）。

三层并发保护（PG advisory lock）+ 权限错误中文快失败 + 回读验证 + minor units 换算 + 缓存 patch + 审计。
写操作绑死账户 token（client_for_account op_kind="write"），不轮换（防孤儿）。
"""
import time
import hashlib
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
    lock_key = int(hashlib.md5(f"ad_status:{node_id}".encode()).hexdigest()[:8], 16)  # 跨 worker 稳定（hash() 受 PYTHONHASHSEED 随机，不同 worker 锁不互斥）
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

    lock_key = int(hashlib.md5(f"ad_budget:{node_id}".encode()).hexdigest()[:8], 16)
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

    lock_key = int(hashlib.md5(f"ad_delete:{node_id}".encode()).hexdigest()[:8], 16)
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


# ── TikTok 写操作（平行函数 + *_any 统一入口分发；上面 FB 函数零改动）──
# 平行而非共用函数体的理由：TT 语义差异大（advertiser_id 维度必带 / opt_status≠status /
# budget 整本币非 minor units / 回读字段名按层不同 adgroup_name…），共用体会在 FB 热路径
# 塞满 platform 分支，违背"FB 逐字节等价"红线；平行函数各自内聚，*_any 是唯一分发点
# （ads.py 端点只认 *_any）。锁号与 FB 同名（ad_status/ad_budget/ad_delete/ad_rename:
# {node_id}）——同一节点无论走哪条路径都互斥，跨平台 act_id 撞号也不互踩。

from ..core.tt_client import TtApiError, TT_OPT_TO_FB  # noqa: E402（文件尾 TT 段，FB 段不受影响）

_TT_NODE_TYPE = {"ad": "ad", "adset": "adgroup", "campaign": "campaign"}
_TT_NAME_KEY = {"ad": "ad_name", "adset": "adgroup_name", "campaign": "campaign_name"}
_TT_OPT_TARGET = {"ACTIVE": "ENABLE", "PAUSED": "DISABLE", "ARCHIVED": "DELETE"}
_TT_BUDGET_MODE = {"daily": "BUDGET_MODE_DAY", "lifetime": "BUDGET_MODE_TOTAL"}


def _tt_classify_write_error(e: TtApiError) -> str:
    """TT 写错误 → 中文 actionable（静态串，error_i18n 译表收录）。"""
    if not e.raw:
        return str(e.friendly)
    code = e.raw.get("code", 0)
    if code == 40113:
        return "无权操作该对象（权限不足或对象不属于该广告主）"
    if code == 40115:
        return "Scope 权限不足，请在 TikTok 开发者后台申请"
    if code in (40000, 40001, 40100):
        return "TikTok 拒绝了请求参数（金额过低/字段不合法）"
    return e.friendly


def _platform_of(db: Session, tenant_id: int, act_id: str) -> str:
    """账户平台（accounts.platform；空/历史缺省 → 'fb'）。"""
    acc = db.query(Account).filter(
        Account.tenant_id == tenant_id, Account.act_id == act_id).first()
    return "tt" if (acc and (acc.platform or "fb") == "tt") else "fb"


def _tt_write_client(db: Session, tenant_id: int, act_id: str):
    """TT 写令牌客户端（绑池内最高优先，语义同 FB cred_for_account_op write）。"""
    from ..core.fb_tokens import tt_client_for_account
    tt, _cred = tt_client_for_account(db, tenant_id, act_id, "write")
    return tt


def _tt_audit(db: Session, tenant_id: int, node_id: str, action_type: str,
              result: str, trigger_detail: str):
    """写操作审计（SuperSessionLocal 绕 RLS，同 FB 路径）。"""
    _sdb = SuperSessionLocal()
    try:
        write_log(_sdb, tenant_id=tenant_id, trace_id=new_trace_id(),
                  actor_type="user", actor_user_id=0,
                  target_type="ad", target_id=node_id,
                  action_type=action_type, source="ad_ops", result=result,
                  trigger_detail=trigger_detail, platform="tt")
        _sdb.commit()
    finally:
        _sdb.close()


def tt_set_status(db: Session, tenant_id: int, act_id: str, node_id: str,
                  level: str, target_status: str, operator: str = "system") -> dict:
    """改广告/组/系列状态（TT opt_status；ACTIVE/PAUSED/ARCHIVED 同 FB 入参枚举）。
    回读核验 opt_status；effective 回填用归一 FB 形状（前端/缓存同构）。"""
    if target_status not in ("ACTIVE", "PAUSED", "ARCHIVED"):
        raise ValueError(f"无效状态: {target_status}")
    tt = _tt_write_client(db, tenant_id, act_id)
    if not tt:
        return {"success": False, "error": "无可用写令牌（operate/manage）"}
    node_type = _TT_NODE_TYPE.get(level, "ad")

    lock_key = int(hashlib.md5(f"ad_status:{node_id}".encode()).hexdigest()[:8], 16)
    lock = acquire_run_lock(lock_key)
    if not lock:
        return {"success": False, "error": "该广告正在被其他操作处理"}

    try:
        before = tt.get_node(node_id, node_type, advertiser_id=act_id)
        tt.update_status(node_id, target_status, node_type, advertiser_id=act_id)
        time.sleep(0.8)
        after = tt.get_node(node_id, node_type, advertiser_id=act_id)
        opt = str(after.get("opt_status") or "").upper()
        verified = opt == _TT_OPT_TARGET[target_status]
        eff = TT_OPT_TO_FB.get(opt, opt)
        warning = ""
        if target_status == "ACTIVE" and opt == "ENABLE":
            raw = str(after.get("status") or "").upper()
            if raw and raw != "STATUS_ENABLE":
                warning = f"状态已设为 ENABLE 但投放状态={raw}（父级暂停/预算不足/时段外可能）"

        _patch_cache_status(db, tenant_id, act_id, node_id, level, target_status, eff)
        db.commit()
        _tt_audit(db, tenant_id, node_id, f"manual_{target_status.lower()}",
                  "success" if verified else "partial",
                  f"platform=tt level={level} old={before.get('opt_status')} new={target_status} eff={eff}")
        return {"success": True, "verified": verified, "effective_status": eff, "warning": warning}
    except TtApiError as e:
        return {"success": False, "error": _tt_classify_write_error(e), "fb_error": e.friendly}
    finally:
        release_run_lock(lock, lock_key)


def tt_set_budget(db: Session, tenant_id: int, act_id: str, node_id: str,
                  level: str, daily_budget: float = None, currency: str = "USD",
                  operator: str = "system", budget_type: str = "daily",
                  lifetime_budget: float = None) -> dict:
    """改预算（本币金额 → TT 整本币 int，无 ×100；签名照 FB set_budget）。

    TT 预算只在 adgroup 层（campaign 层预算更新端点未证实，拒改给明确提示）。
    类型匹配同 FB：DAY↔TOTAL 不互改；INFINITE（不限）可改设任一类型（budget_mode 一并传）。
    ads_cache patch 用 FB minor units（展示层与 FB 行同一路径）。
    """
    if lifetime_budget is not None and lifetime_budget > 0:
        btype, amount = "lifetime", lifetime_budget
    elif daily_budget is not None and daily_budget > 0:
        btype, amount = "daily", daily_budget
    else:
        return {"success": False, "error": "预算必须大于 0"}
    if budget_type not in ("daily", "lifetime"):
        budget_type = btype
    if level != "adset":
        return {"success": False, "error": "TikTok 仅支持在广告组层级修改预算"}

    tt = _tt_write_client(db, tenant_id, act_id)
    if not tt:
        return {"success": False, "error": "无可用写令牌（operate/manage）"}

    lock_key = int(hashlib.md5(f"ad_budget:{node_id}".encode()).hexdigest()[:8], 16)
    lock = acquire_run_lock(lock_key)
    if not lock:
        return {"success": False, "error": "该广告正在被其他操作处理"}

    try:
        before = tt.get_node(node_id, "adgroup", advertiser_id=act_id)
        mode = str(before.get("budget_mode") or "").upper()
        has_daily = mode == "BUDGET_MODE_DAY"
        has_lifetime = mode == "BUDGET_MODE_TOTAL"
        if btype == "lifetime" and has_daily and not has_lifetime:
            return {"success": False, "error": "该对象使用日预算，不支持改总预算"}
        if btype == "daily" and has_lifetime and not has_daily:
            return {"success": False, "error": "该对象使用总预算(lifetime)，不支持改日预算"}

        amount_int = int(round(amount))  # TT 整本币（无 ×100）
        want_mode = _TT_BUDGET_MODE[btype]
        tt.update_budget(node_id, amount_int, advertiser_id=act_id, budget_mode=want_mode)
        time.sleep(0.8)
        after = tt.get_node(node_id, "adgroup", advertiser_id=act_id)
        verified = (str(after.get("budget") or "") == str(amount_int)
                    and str(after.get("budget_mode") or "").upper() == want_mode)

        minor = _to_minor(amount, currency)  # FB minor units 形状写 cache
        _patch_cache_budget(db, tenant_id, act_id, node_id,
                            daily_budget_minor=minor if btype == "daily" else None,
                            lifetime_minor=minor if btype == "lifetime" else None)
        db.commit()
        _tt_audit(db, tenant_id, node_id, "manual_budget",
                  "success" if verified else "partial",
                  f"platform=tt level={level} type={btype} old={before.get('budget')} new={amount_int}")
        return {"success": True, "verified": verified,
                "budget_type": btype, "budget_minor": minor}
    except TtApiError as e:
        return {"success": False, "error": _tt_classify_write_error(e), "fb_error": e.friendly}
    finally:
        release_run_lock(lock, lock_key)


def tt_set_budget_daily(tt, advertiser_id, adgroup_id, daily_amount_int) -> bool:
    """（C 组扩量规则契约，签名钉死）TT 广告组日预算直设。

    daily_amount_int = 整本币最小单位（无 ×100，与 FB minor units 不同；C 组换算后传入）。
    轻调用：不落锁/不回读/不写缓存——巡检热路径，扩量生效由下一轮快照核验；
    管理器手动改预算走 tt_set_budget（带锁/回读核验/cache patch/审计全链）。
    """
    try:
        tt.update_budget(str(adgroup_id), int(daily_amount_int),
                         advertiser_id=str(advertiser_id), budget_mode="BUDGET_MODE_DAY")
        return True
    except TtApiError:
        return False


def _tt_level_from_cache(db: Session, tenant_id: int, act_id: str, node_id: str) -> str:
    """从 ads_cache 三层 JSON 反查节点层级（TT 删/改状态需要 node_type，FB 无此维度）。
    查不到默认 ad（删除端点无 level 入参，FB 同款入参形状）。"""
    row = db.query(AdsCache).filter(
        AdsCache.tenant_id == tenant_id, AdsCache.act_id == act_id,
        AdsCache.platform == "tt").first()
    if not row:
        return "ad"
    import json
    for field, level in [("campaigns_json", "campaign"), ("adsets_json", "adset"), ("ads_json", "ad")]:
        try:
            for it in json.loads(getattr(row, field) or "[]"):
                if str(it.get("id")) == str(node_id):
                    return level
        except Exception:
            continue
    return "ad"


def tt_delete_node(db: Session, tenant_id: int, act_id: str, node_id: str,
                   level: str = "", operator: str = "system") -> dict:
    """删节点（TT opt_status=DELETE 软删，无 FB 式硬删端点）。层级由 ads_cache 反查。"""
    tt = _tt_write_client(db, tenant_id, act_id)
    if not tt:
        return {"success": False, "error": "无可用写令牌（operate/manage）"}
    if level not in _TT_NODE_TYPE:
        level = _tt_level_from_cache(db, tenant_id, act_id, node_id)

    lock_key = int(hashlib.md5(f"ad_delete:{node_id}".encode()).hexdigest()[:8], 16)
    lock = acquire_run_lock(lock_key)
    if not lock:
        return {"success": False, "error": "该广告正在被其他操作处理"}

    try:
        tt.delete_node(node_id, _TT_NODE_TYPE[level], advertiser_id=act_id)
        time.sleep(0.8)
        after = tt.get_node(node_id, _TT_NODE_TYPE[level], advertiser_id=act_id)
        verified = str(after.get("opt_status") or "").upper() == "DELETE"
        # patch cache：移除该节点（下一轮同步若 TT 仍返回，会以 ARCHIVED 形态重新出现——TT 软删语义）
        row = db.query(AdsCache).filter(
            AdsCache.tenant_id == tenant_id, AdsCache.act_id == act_id,
            AdsCache.platform == "tt").first()
        if row:
            import json
            for field in ["campaigns_json", "adsets_json", "ads_json"]:
                raw = getattr(row, field)
                if not raw:
                    continue
                try:
                    items = json.loads(raw)
                    filtered = [it for it in items if str(it.get("id")) != str(node_id)]
                    if len(filtered) != len(items):
                        setattr(row, field, json.dumps(filtered))
                except Exception:
                    pass
        db.commit()
        _tt_audit(db, tenant_id, node_id, "manual_delete",
                  "success" if verified else "partial", f"platform=tt level={level}")
        return {"success": True, "verified": verified}
    except TtApiError as e:
        return {"success": False, "error": _tt_classify_write_error(e), "fb_error": e.friendly}
    finally:
        release_run_lock(lock, lock_key)


def tt_rename_node(db: Session, tenant_id: int, act_id: str, node_id: str,
                   level: str, name: str, operator: str = "system") -> dict:
    """改名（campaign/adgroup/ad 通用，各层端点与 name 字段不同）。照 ads.py FB rename 全链：
    node 级锁 + 回读核验 + ads_cache patch + SuperSessionLocal 审计。"""
    tt = _tt_write_client(db, tenant_id, act_id)
    if not tt:
        return {"success": False, "error": "无可用写令牌（operate/manage）"}
    if level not in _TT_NODE_TYPE:
        level = "ad"
    node_type = _TT_NODE_TYPE[level]
    name_key = _TT_NAME_KEY[level]

    lock_key = int(hashlib.md5(f"ad_rename:{node_id}".encode()).hexdigest()[:8], 16)
    lock = acquire_run_lock(lock_key)
    if not lock:
        return {"success": False, "error": "该广告正在被其他操作处理"}

    try:
        before = tt.get_node(node_id, node_type, advertiser_id=act_id)
        tt.rename_node(node_id, name, node_type, advertiser_id=act_id)
        time.sleep(0.8)
        after = tt.get_node(node_id, node_type, advertiser_id=act_id)
        verified = (after.get(name_key) or "").strip() == name
        # patch ads_cache（写后立即生效，不等 15min 同步）
        row = db.query(AdsCache).filter(
            AdsCache.tenant_id == tenant_id, AdsCache.act_id == act_id,
            AdsCache.platform == "tt").first()
        if row:
            import json
            for field in ["campaigns_json", "adsets_json", "ads_json"]:
                raw = getattr(row, field)
                if not raw:
                    continue
                try:
                    items = json.loads(raw)
                    changed = False
                    for it in items:
                        if str(it.get("id")) == str(node_id):
                            it["name"] = name
                            changed = True
                    if changed:
                        setattr(row, field, json.dumps(items))
                except Exception:
                    pass
        db.commit()
        _tt_audit(db, tenant_id, node_id, "manual_rename",
                  "success" if verified else "partial",
                  f"platform=tt level={level} old={before.get(name_key)} new={name}")
        return {"success": True, "verified": verified, "name": name}
    except TtApiError as e:
        return {"success": False, "error": _tt_classify_write_error(e), "fb_error": e.friendly}
    finally:
        release_run_lock(lock, lock_key)


# ── 统一入口分发（ads.py 端点唯一调用面；FB 分支 = 原 FB 函数原样透传）──

def set_status_any(db: Session, tenant_id: int, act_id: str, node_id: str,
                   level: str, target_status: str, operator: str = "system") -> dict:
    """改状态：按账户 platform 分发（FB=set_status 原函数）。"""
    if _platform_of(db, tenant_id, act_id) == "tt":
        return tt_set_status(db, tenant_id, act_id, node_id, level, target_status, operator)
    return set_status(db, tenant_id, act_id, node_id, level, target_status, operator)


def set_budget_any(db: Session, tenant_id: int, act_id: str, node_id: str,
                   level: str, daily_budget: float = None, currency: str = "USD",
                   operator: str = "system", budget_type: str = "daily",
                   lifetime_budget: float = None) -> dict:
    """改预算：按账户 platform 分发（FB=set_budget 原函数）。"""
    if _platform_of(db, tenant_id, act_id) == "tt":
        return tt_set_budget(db, tenant_id, act_id, node_id, level,
                             daily_budget=daily_budget, currency=currency,
                             operator=operator, budget_type=budget_type,
                             lifetime_budget=lifetime_budget)
    return set_budget(db, tenant_id, act_id, node_id, level,
                      daily_budget=daily_budget, currency=currency,
                      operator=operator, budget_type=budget_type,
                      lifetime_budget=lifetime_budget)


def delete_node_any(db: Session, tenant_id: int, act_id: str, node_id: str,
                    operator: str = "system") -> dict:
    """删节点：按账户 platform 分发（FB=delete_node 原函数；TT 层级由 ads_cache 反查）。"""
    if _platform_of(db, tenant_id, act_id) == "tt":
        return tt_delete_node(db, tenant_id, act_id, node_id, operator=operator)
    return delete_node(db, tenant_id, act_id, node_id, operator)
