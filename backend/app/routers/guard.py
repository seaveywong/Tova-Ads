"""守护引擎路由：规则 CRUD + 当日加白 + 哨兵 arm/disarm（doc 03）。"""
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..core.database import get_db
from ..core.deps import CurrentUser, require_permission
from ..core.log_utils import write_log, new_trace_id
from ..models.guard import GuardRule, GuardAllowance
from ..models.fb import Account
from pydantic import BaseModel

router = APIRouter(prefix="/guard", tags=["guard"])

# 规则动作（doc 03 §2.3）：observe=只告警 / default/pause=停广告 / pause_adset=停组 / pause_campaign=停系列
RULE_ACTIONS = {"observe", "default", "pause", "pause_adset", "pause_campaign"}


class CreateRuleIn(BaseModel):
    name: str
    category: str  # 空耗止损/成本超标/效果下滑
    rule_type: str  # bleed_abs/cpa_exceed/...
    params: dict = {}
    conversion_source: str = "either"
    action: str = "default"
    scope_act_id: str = ""  # 空=全局（名下所有账户）；填 act_id(裸数字)=仅该账户


class UpdateRuleIn(BaseModel):
    name: str | None = None
    category: str | None = None
    rule_type: str | None = None
    params: dict | None = None
    conversion_source: str | None = None
    action: str | None = None
    scope_act_id: str | None = None
    enabled: bool | None = None


class AllowanceIn(BaseModel):
    act_id: str
    ad_id: str


class SentinelArmIn(BaseModel):
    act_ids: list[str] | None = None  # None=全租户(Owner) / 指定账户


# ── 规则 CRUD ──
@router.get("/rules")
def list_rules(user: CurrentUser = Depends(require_permission("rules.read")), db: Session = Depends(get_db)):
    rules = db.query(GuardRule).filter(GuardRule.tenant_id == user.tenant_id).all()
    # 每条规则的命中统计（action_logs: pause by rule_engine, 按 trigger_type 聚合）
    from ..models.log import ActionLog
    from sqlalchemy import func
    hit_rows = db.query(
        ActionLog.trigger_type, func.count(ActionLog.id), func.max(ActionLog.created_at),
    ).filter(
        ActionLog.tenant_id == user.tenant_id,
        ActionLog.action_type == "pause",
        ActionLog.source == "rule_engine",
    ).group_by(ActionLog.trigger_type).all()
    hit_map = {r[0]: {"count": int(r[1] or 0), "last_at": r[2].isoformat() if r[2] else None} for r in hit_rows}
    return [{"id": r.id, "name": r.name, "category": r.category, "rule_type": r.rule_type,
             "params": json.loads(r.params) if r.params else {}, "conversion_source": r.conversion_source,
             "action": r.action, "scope_act_id": r.scope_act_id, "enabled": r.enabled,
             "hits": hit_map.get(r.rule_type, {"count": 0, "last_at": None})} for r in rules]


@router.post("/rules")
def create_rule(body: CreateRuleIn, user: CurrentUser = Depends(require_permission("rules.create")),
                db: Session = Depends(get_db)):
    if (body.action or "default").lower() not in RULE_ACTIONS:
        raise HTTPException(400, f"action 必须是 {sorted(RULE_ACTIONS)} 之一")
    rule = GuardRule(tenant_id=user.tenant_id, name=body.name, category=body.category,
                     rule_type=body.rule_type, params=json.dumps(body.params),
                     conversion_source=body.conversion_source, action=body.action,
                     scope_act_id=body.scope_act_id or None)
    db.add(rule)
    db.flush()
    rid = rule.id
    trace_id = new_trace_id()
    write_log(db, tenant_id=user.tenant_id, trace_id=trace_id, actor_type="user",
              actor_user_id=user.id, target_type="rule", target_id=str(rid),
              action_type="create", source="user", result="success")
    db.commit()
    return {"id": rid, "name": rule.name, "enabled": True}


@router.put("/rules/{rule_id}")
def update_rule(rule_id: int, body: UpdateRuleIn,
                user: CurrentUser = Depends(require_permission("rules.edit")),
                db: Session = Depends(get_db)):
    """更新规则（全字段，含 enabled 开关）。tenant 隔离。"""
    rule = db.query(GuardRule).filter(
        GuardRule.id == rule_id, GuardRule.tenant_id == user.tenant_id).first()
    if not rule:
        raise HTTPException(404, "规则不存在")
    if body.action is not None and body.action.lower() not in RULE_ACTIONS:
        raise HTTPException(400, f"action 必须是 {sorted(RULE_ACTIONS)} 之一")
    if body.name is not None:
        rule.name = body.name
    if body.category is not None:
        rule.category = body.category
    if body.rule_type is not None:
        rule.rule_type = body.rule_type
    if body.params is not None:
        rule.params = json.dumps(body.params)
    if body.conversion_source is not None:
        rule.conversion_source = body.conversion_source
    if body.action is not None:
        rule.action = body.action
    if body.scope_act_id is not None:
        rule.scope_act_id = body.scope_act_id or None
    if body.enabled is not None:
        rule.enabled = body.enabled
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, target_type="rule", target_id=str(rule_id),
              action_type="update", source="user", result="success")
    db.commit()
    return {"id": rule.id, "enabled": rule.enabled}


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, user: CurrentUser = Depends(require_permission("rules.create")),
                db: Session = Depends(get_db)):
    """删除规则。tenant 隔离。"""
    rule = db.query(GuardRule).filter(
        GuardRule.id == rule_id, GuardRule.tenant_id == user.tenant_id).first()
    if not rule:
        raise HTTPException(404, "规则不存在")
    db.delete(rule)
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, target_type="rule", target_id=str(rule_id),
              action_type="delete", source="user", result="success")
    db.commit()
    return {"deleted": True, "id": rule_id}


# ── 当日加白（= 1.0 当日放行，doc 03 §2.4）──
@router.post("/allowance")
def add_allowance(body: AllowanceIn, user: CurrentUser = Depends(require_permission("rules.edit")),
                  db: Session = Depends(get_db)):
    """加白：账户本地当日巡检跳过。账户本地进入次日自动失效（查不到记录）。

    日期基准=账户本地时区（和巡检查询 / snapshot_date / FB insights today 对齐）：
    北京6号、美东账户本地5号 → 加白写在5号，账户本地进入6号即失效恢复。
    """
    acc = db.query(Account).filter(
        Account.act_id == body.act_id, Account.tenant_id == user.tenant_id
    ).first()
    if not acc:
        raise HTTPException(404, "账户不存在")
    from ..services.guard_engine import _account_local_today
    today = _account_local_today(acc)
    existing = db.query(GuardAllowance).filter(
        GuardAllowance.act_id == body.act_id,
        GuardAllowance.ad_id == body.ad_id,
        GuardAllowance.allowance_date == today,
        GuardAllowance.status == "active",
    ).first()
    if existing:
        return {"status": "already", "date": today}
    # 检查是否有 inactive 的（解除过又重新加）→ 复活
    inactive = db.query(GuardAllowance).filter(
        GuardAllowance.tenant_id == user.tenant_id,
        GuardAllowance.act_id == body.act_id,
        GuardAllowance.ad_id == body.ad_id,
        GuardAllowance.allowance_date == today,
        GuardAllowance.status == "inactive",
    ).first()
    if inactive:
        inactive.status = "active"
        db.commit()
        return {"status": "added", "date": today}
    allowance = GuardAllowance(tenant_id=user.tenant_id, act_id=body.act_id,
                               ad_id=body.ad_id, allowance_date=today)
    db.add(allowance)
    db.flush()
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, target_type="ad", target_id=body.ad_id,
              action_type="allowance", source="user", result="success",
              trigger_detail=f"act={body.act_id} date={today}")
    db.commit()
    return {"status": "added", "date": today}


@router.delete("/allowance")
def remove_allowance(act_id: str, ad_id: str,
                     user: CurrentUser = Depends(require_permission("rules.edit")),
                     db: Session = Depends(get_db)):
    """解除今日放行（当日的加白标记为 inactive）。"""
    acc = db.query(Account).filter(
        Account.act_id == act_id, Account.tenant_id == user.tenant_id
    ).first()
    if not acc:
        raise HTTPException(404, "账户不存在")
    from ..services.guard_engine import _account_local_today
    today = _account_local_today(acc)
    row = db.query(GuardAllowance).filter(
        GuardAllowance.tenant_id == user.tenant_id,
        GuardAllowance.act_id == act_id,
        GuardAllowance.ad_id == ad_id,
        GuardAllowance.allowance_date == today,
        GuardAllowance.status == "active",
    ).first()
    if row:
        row.status = "inactive"
        write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
                  actor_user_id=user.id, target_type="ad", target_id=ad_id,
                  action_type="allowance_removed", source="user", result="success",
                  trigger_detail=f"act={act_id} date={today}")
        db.commit()
    return {"removed": bool(row)}


# ── 哨兵 arm/disarm（doc 03 §4-5）──
@router.post("/sentinel/arm")
def sentinel_arm(body: SentinelArmIn, user: CurrentUser = Depends(require_permission("ads.pause")),
                 db: Session = Depends(get_db)):
    """手动哨兵 arm：设 accounts.sentinel_armed=true。"""
    query = db.query(Account).filter(Account.tenant_id == user.tenant_id)
    if body.act_ids:
        query = query.filter(Account.act_id.in_(body.act_ids))
    elif user.role == "operator":
        query = query.filter(Account.owner_user_id == user.id)
    count = query.update({Account.sentinel_armed: True}, synchronize_session="fetch")
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, action_type="sentinel_arm", source="user",
              result="success", trigger_detail=f"accounts={count}")
    db.commit()
    return {"armed": True, "accounts": count}


@router.post("/sentinel/disarm")
def sentinel_disarm(body: SentinelArmIn, user: CurrentUser = Depends(require_permission("ads.pause")),
                    db: Session = Depends(get_db)):
    """手动哨兵 disarm（doc 03：解除必须手动）。"""
    query = db.query(Account).filter(Account.tenant_id == user.tenant_id)
    if body.act_ids:
        query = query.filter(Account.act_id.in_(body.act_ids))
    elif user.role == "operator":
        query = query.filter(Account.owner_user_id == user.id)
    count = query.update({Account.sentinel_armed: False, Account.sentinel_auto_armed: False},
                         synchronize_session="fetch")
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, action_type="sentinel_disarm", source="user",
              result="success", trigger_detail=f"accounts={count}")
    db.commit()
    return {"armed": False, "accounts": count}


@router.get("/status")
def guard_status(user: CurrentUser = Depends(require_permission("rules.read")),
                 db: Session = Depends(get_db)):
    """当前守护状态：规则数 / 哨兵 / 加白。"""
    rules_count = db.query(GuardRule).filter(
        GuardRule.tenant_id == user.tenant_id, GuardRule.enabled == True).count()
    # 加白数：按各账户本地今日（多时区账户不能一刀切 UTC；和加白写入/巡检查询对齐）
    from ..services.guard_engine import _account_local_today
    accs = db.query(Account).filter(Account.tenant_id == user.tenant_id).all()
    local_today = {a.act_id: _account_local_today(a) for a in accs}
    today_dates = set(local_today.values())
    allow_cand = db.query(GuardAllowance).filter(
        GuardAllowance.tenant_id == user.tenant_id,
        GuardAllowance.allowance_date.in_(today_dates),
    ).all() if today_dates else []
    allowances = sum(1 for a in allow_cand if local_today.get(a.act_id) == a.allowance_date)
    armed = db.query(Account).filter(
        Account.tenant_id == user.tenant_id,
        (Account.sentinel_armed == True) | (Account.sentinel_auto_armed == True)).count()
    return {"rules_enabled": rules_count, "allowances_today": allowances, "sentinel_armed_accounts": armed}


@router.post("/inspect")
def manual_inspect(force: bool = False,
                   user: CurrentUser = Depends(require_permission("rules.edit"))):
    """手动触发巡检。force=True 跳过冷却。"""
    from ..services import guard_engine as ge
    original = ge.COOLDOWN_MIN
    if force:
        ge.COOLDOWN_MIN = 0
    try:
        return ge.run_inspection()
    finally:
        ge.COOLDOWN_MIN = original


@router.post("/sentinel-patrol")
def manual_sentinel_patrol(user: CurrentUser = Depends(require_permission("ads.pause"))):
    """手动触发哨兵巡逻：armed 账户的 ACTIVE 系列直接全停（kill-switch，不走规则）。"""
    from ..services.guard_engine import run_sentinel_patrol
    return run_sentinel_patrol()


@router.post("/emergency-pause")
def emergency_pause(user: CurrentUser = Depends(require_permission("ads.pause")),
                    db: Session = Depends(get_db)):
    """全局紧急暂停：先同步 ads_cache（拉最新 ACTIVE 广告）→ 逐个 PAUSE → 回读核验。"""
    import json as _json, time as _time
    from ..core.fb_tokens import client_for_account, cred_for_account_op
    from ..core.fb_client import FbClient
    from ..core.encryption import decrypt
    from ..models.fb import Account
    from ..models.ads_cache import AdsCache
    from ..services.ad_ops import set_status
    from ..core.security import new_trace_id
    from ..routers.ads import _sync_one

    accounts = db.query(Account).filter(
        Account.tenant_id == user.tenant_id,
        Account.is_managed.is_(True),
        Account.account_status == 1,
    ).all()
    trace_id = new_trace_id()
    paused = 0
    verify_failed = 0
    errors = []

    for acc in accounts:
        cred = cred_for_account_op(db, user.tenant_id, acc.act_id, "pause")
        if not cred:
            errors.append(f"{acc.name}: 无可用写令牌")
            continue
        fb = FbClient(decrypt(cred.access_token_enc))

        # ① 先同步 ads_cache（拉最新广告结构，避免关漏新建广告）
        try:
            _sync_one(db, user.tenant_id, acc.act_id, fb)
            db.commit()
        except Exception as e:
            errors.append(f"{acc.name}: 同步失败({str(e)[:40]})，用旧缓存")

        # ② 从最新缓存拿 ACTIVE 广告
        cache = db.query(AdsCache).filter(
            AdsCache.tenant_id == user.tenant_id, AdsCache.act_id == acc.act_id).first()
        if not cache:
            errors.append(f"{acc.name}: 无广告缓存")
            continue
        ad_ids = []
        try:
            for ad in _json.loads(cache.ads_json or "[]"):
                if ad.get("effective_status") == "ACTIVE":
                    ad_ids.append(str(ad.get("id")))
        except Exception:
            pass
        if not ad_ids:
            continue

        # ③ 逐个暂停
        for ad_id in ad_ids:
            try:
                r = set_status(db, user.tenant_id, acc.act_id, ad_id, "ad", "PAUSED", operator=user.email)
                if r.get("success"):
                    paused += 1
                else:
                    errors.append(f"{acc.name}/{ad_id[-8:]}: {r.get('error','')}")
            except Exception as e:
                errors.append(f"{acc.name}/{ad_id[-8:]}: {str(e)[:50]}")

        # ④ 回读核验：等 FB 写生效，重新拉广告确认状态
        _time.sleep(2)
        try:
            active_ads = fb.get_active_ads(acc.act_id)
            still_active = [a.get("id") for a in active_ads if str(a.get("id")) in ad_ids]
            if still_active:
                verify_failed += len(still_active)
                errors.append(f"{acc.name}: {len(still_active)} 条仍 ACTIVE（FB 写延迟）: {[str(i)[-8:] for i in still_active[:3]]}")
        except Exception:
            pass  # 核验查询失败不阻断（信任 set_status 的成功返回）

    return {"paused": paused, "verify_failed": verify_failed,
            "errors": errors[:10], "total_accounts": len(accounts)}


# ── 预热（warmup）arm/disarm（doc 03 §6）──
class WarmupArmIn(BaseModel):
    act_ids: list[str] | None = None  # None=名下全部；指定=仅那些


@router.post("/warmup/arm")
def warmup_arm(body: WarmupArmIn, user: CurrentUser = Depends(require_permission("ads.pause")),
               db: Session = Depends(get_db)):
    """设置账户预热（warmup_state=warming）→ 巡检/哨兵跳过（新账户保护期）。"""
    query = db.query(Account).filter(Account.tenant_id == user.tenant_id)
    if body.act_ids:
        query = query.filter(Account.act_id.in_(body.act_ids))
    count = query.update({Account.warmup_state: "warming"}, synchronize_session="fetch")
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, action_type="warmup_arm", source="user",
              result="success", trigger_detail=f"accounts={count}")
    db.commit()
    return {"warming": True, "accounts": count}


@router.post("/warmup/disarm")
def warmup_disarm(body: WarmupArmIn, user: CurrentUser = Depends(require_permission("ads.pause")),
                  db: Session = Depends(get_db)):
    """取消预热（warmup_state=none）→ 恢复巡检/哨兵。"""
    query = db.query(Account).filter(
        Account.tenant_id == user.tenant_id, Account.warmup_state == "warming")
    if body.act_ids:
        query = query.filter(Account.act_id.in_(body.act_ids))
    count = query.update({Account.warmup_state: "none"}, synchronize_session="fetch")
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, action_type="warmup_disarm", source="user",
              result="success", trigger_detail=f"accounts={count}")
    db.commit()
    return {"warming": False, "accounts": count}


@router.post("/budget-check")
def manual_budget_check(user: CurrentUser = Depends(require_permission("rules.read"))):
    """手动触发预算进度告警（doc 03 §3.10，审计项目21）。纯告警不改预算。"""
    from ..services.budget_alerts import run_budget_alerts
    return run_budget_alerts()


@router.post("/watchdog")
def manual_watchdog(user: CurrentUser = Depends(require_permission("rules.read"))):
    """手动触发系统看门狗（06_附录 §四）：巡检停滞检测 + token 主动健康检查。"""
    from ..services.guard_engine import run_watchdog
    return run_watchdog()
