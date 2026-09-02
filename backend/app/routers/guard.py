"""守护引擎路由：规则 CRUD + 当日加白 + 哨兵 arm/disarm（doc 03）。"""
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from ..core.database import get_db
from ..core.deps import CurrentUser, require_permission, require_superadmin
from ..core.log_utils import write_log, new_trace_id
from ..models.guard import GuardRule, GuardAllowance
from ..models.fb import Account
from pydantic import BaseModel

router = APIRouter(prefix="/guard", tags=["guard"])

# 规则动作（doc 03 §2.3）：observe=只告警 / default/pause=停广告 / pause_adset=停组 / pause_campaign=停系列
# scale=扩量规则加预算（rule_type=slow_scale/roas_scale 专用；引擎里非 observe 的动作都按扩量执行）
RULE_ACTIONS = {"observe", "default", "pause", "pause_adset", "pause_campaign", "scale"}


class CreateRuleIn(BaseModel):
    name: str
    category: str  # 空耗止损/成本超标/效果下滑
    rule_type: str  # bleed_abs/cpa_exceed/...
    params: dict = {}
    conversion_source: str = "either"
    action: str = "default"
    scope_act_id: str = ""  # 空=全局（名下所有账户）；填 act_id(裸数字)=仅该账户
    enabled: bool = True


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
    # 每条规则的命中统计（action_logs: pause/increase_budget by rule_engine, 按 trigger_type 聚合；
    # increase_budget=扩量规则的"命中"，否则扩量规则永远显示未命中）
    from ..models.log import ActionLog
    from sqlalchemy import func
    hit_rows = db.query(
        ActionLog.trigger_type, func.count(ActionLog.id), func.max(ActionLog.created_at),
    ).filter(
        ActionLog.tenant_id == user.tenant_id,
        ActionLog.action_type.in_(["pause", "increase_budget"]),
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
                     scope_act_id=body.scope_act_id or None, enabled=body.enabled)
    db.add(rule)
    db.flush()
    rid = rule.id
    trace_id = new_trace_id()
    write_log(db, tenant_id=user.tenant_id, trace_id=trace_id, actor_type="user",
              actor_user_id=user.id, target_type="rule", target_id=str(rid),
              action_type="create", source="user", result="success")
    db.commit()
    return {"id": rid, "name": rule.name, "enabled": rule.enabled}


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
    else:
        # 全租户/全名下批量 arm 只碰在管账户：软删账户（is_managed=false）被 arm 后，
        # 重新导入即被哨兵全停（意外 kill）。显式指定 act_ids 不受限（用户点名要 arm）
        query = query.filter(Account.is_managed.is_(True))
        if user.role == "operator":
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
def guard_status(user: CurrentUser = Depends(require_permission("ads.pause")),
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
        Account.is_managed.is_(True),  # 与 arm 口径一致：软删账户不计入 armed 数
        (Account.sentinel_armed == True) | (Account.sentinel_auto_armed == True)).count()
    return {"rules_enabled": rules_count, "allowances_today": allowances, "sentinel_armed_accounts": armed}


@router.post("/inspect")
def manual_inspect(force: bool = False,
                   user: CurrentUser = Depends(require_superadmin)):
    """手动触发巡检（平台级——返回全平台各租户执行明细，只能超管）。force=True 跳过冷却。"""
    from ..services.guard_engine import run_inspection
    return run_inspection(force=force)


@router.post("/sentinel-patrol")
def manual_sentinel_patrol(user: CurrentUser = Depends(require_superadmin)):
    """手动触发哨兵巡逻（平台级 kill-switch——会停全平台 armed 账户，只能超管）。"""
    from ..services.guard_engine import run_sentinel_patrol
    return run_sentinel_patrol()


# 紧急暂停后台执行状态（gunicorn 多 worker 各自一份，可接受——同 ads.py _REFRESH_STATE 模式）
# {tenant_id: {"running": bool, "started_at": ts, "paused": n, "verify_failed": n, "total_accounts": n, "errors": []}}
_EMERGENCY_STATE: dict = {}


def _emergency_state_write(db, tenant_id: int, st: dict):
    """状态落 DB system_settings（gunicorn 4 worker——进程内 dict 另一 worker 读不到，
    轮询会第一拍就假报'已暂停 0 条'。DB 是跨 worker 真相源）。"""
    import json as _json
    from ..models.system import SystemSetting
    key = f'emergency_state_{tenant_id}'
    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    val = _json.dumps(st)
    if row:
        row.value = val
    else:
        db.add(SystemSetting(key=key, value=val))
    db.commit()


def _bg_emergency_pause(tenant_id: int, user_email: str):
    """后台执行全局紧急暂停：同步 ads_cache → 逐个 PAUSE → 回读核验（advisory lock 113 单实例互斥）。"""
    from ..core.database import SuperSessionLocal, acquire_run_lock, release_run_lock
    from ..core.fb_tokens import cred_for_account_op
    from ..core.fb_client import FbClient
    from ..core.encryption import decrypt
    from ..models.ads_cache import AdsCache
    from ..services.ad_ops import set_status
    from ..routers.ads import _sync_one
    import json as _json, time as _time

    st = _EMERGENCY_STATE.get(tenant_id)
    if st and st.get("running"):
        return
    lock = None
    db = None
    _EMERGENCY_STATE[tenant_id] = {"running": True, "started_at": datetime.now(timezone.utc).isoformat(),
                                   "paused": 0, "verify_failed": 0, "total_accounts": 0, "errors": []}
    try:
        lock = acquire_run_lock(113)
        if not lock:
            # 别的 worker 正在执行紧急暂停（pg_try 拿不到=已有人持有）——不重复跑
            _EMERGENCY_STATE[tenant_id] = {"running": False, "started_at": "", "paused": 0,
                                           "verify_failed": 0, "total_accounts": 0, "errors": []}
            return
        db = SuperSessionLocal()
        _st = _EMERGENCY_STATE[tenant_id]
        _emergency_state_write(db, tenant_id, dict(_st))
        # 按平台分组：FB 组走原 set_status 链（零改动）；TT 组走 TtClient 批量 DISABLE（下方 TT 段）。
        # 不再整段排除 TT（P0-2）——紧急暂停覆盖全平台。
        accounts = db.query(Account).filter(
            Account.tenant_id == tenant_id,
            Account.is_managed.is_(True),
            Account.account_status == 1,
        ).all()
        fb_accounts = [a for a in accounts if (a.platform or "fb") != "tt"]
        tt_accounts = [a for a in accounts if (a.platform or "fb") == "tt"]
        _st["total_accounts"] = len(accounts)

        for acc in fb_accounts:
            cred = cred_for_account_op(db, tenant_id, acc.act_id, "pause")
            if not cred:
                _st["errors"].append(f"{acc.name}: 无可用写令牌")
                continue
            fb = FbClient(decrypt(cred.access_token_enc))

            # ① 先同步 ads_cache（拉最新广告结构，避免关漏新建广告）
            try:
                _sync_one(db, tenant_id, acc.act_id, fb)
                db.commit()
            except Exception as e:
                _st["errors"].append(f"{acc.name}: 同步失败({str(e)[:40]})，用旧缓存")

            # ② 从最新缓存拿 ACTIVE 广告
            # platform=fb：0081 唯一键含 platform 后同 act_id 双平台行可共存，
            # 漏过滤会拿到 TT 行→FB client 去停 TT 广告 id→真 FB 广告漏停
            cache = db.query(AdsCache).filter(
                AdsCache.tenant_id == tenant_id, AdsCache.act_id == acc.act_id,
                AdsCache.platform == "fb").first()
            if not cache:
                _st["errors"].append(f"{acc.name}: 无广告缓存")
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
                    r = set_status(db, tenant_id, acc.act_id, ad_id, "ad", "PAUSED", operator=user_email)
                    if r.get("success"):
                        _st["paused"] += 1
                    else:
                        _st["errors"].append(f"{acc.name}/{ad_id[-8:]}: {r.get('error','')}")
                except Exception as e:
                    _st["errors"].append(f"{acc.name}/{ad_id[-8:]}: {str(e)[:50]}")

            # ④ 回读核验：等 FB 写生效，重新拉广告确认状态
            _time.sleep(2)
            try:
                active_ads = fb.get_active_ads(acc.act_id)
                still_active = [a.get("id") for a in active_ads if str(a.get("id")) in ad_ids]
                if still_active:
                    _st["verify_failed"] += len(still_active)
                    _st["errors"].append(f"{acc.name}: {len(still_active)} 条仍 ACTIVE（FB 写延迟）: {[str(i)[-8:] for i in still_active[:3]]}")
            except Exception:
                pass  # 核验查询失败不阻断（信任 set_status 的成功返回）
            # 每账户拍一次进度到 DB（前端轮询跨 worker 可见；紧急暂停低频，写代价可忽略）
            try:
                _emergency_state_write(db, tenant_id, dict(_st))
            except Exception:
                pass

        # ── TT 组：TtClient → get_active_ads → ad/status/update 批量 DISABLE → 回读核验 ──
        # 与 FB 组共用 _st 进度结构（paused/verify_failed/total_accounts 计数合并），
        # errors 条目带 [TT] 前缀标注平台维度。TT 失败不阻断 FB 已完成的暂停结果。
        if tt_accounts:
            from ..core.fb_tokens import tt_client_for_account
            tt_trace = new_trace_id()
            for acc in tt_accounts:
                tt, _tt_cred = tt_client_for_account(db, tenant_id, acc.act_id, "pause")
                if not tt:
                    _st["errors"].append(f"[TT] {acc.name}: 无可用 TT 写令牌")
                    continue
                try:
                    active_ads = tt.get_active_ads(acc.act_id)
                except Exception as e:
                    _st["errors"].append(f"[TT] {acc.name}: 拉投放中广告失败({str(e)[:40]})")
                    continue
                # TT 行 id 在 ad_id 字段（_ad_id_of 同款归一）
                ad_ids = [str(a.get("ad_id") or a.get("id") or "") for a in active_ads]
                ad_ids = [i for i in ad_ids if i]
                if not ad_ids:
                    continue
                for ad_id in ad_ids:
                    try:
                        tt.update_status(ad_id, "PAUSED", "ad", acc.act_id)  # opt_status=DISABLE
                        _st["paused"] += 1
                        try:
                            write_log(db, tenant_id=tenant_id, trace_id=tt_trace,
                                      actor_type="user", target_type="ad", target_id=ad_id,
                                      action_type="pause", source="emergency_pause",
                                      result="success", platform="tt",
                                      trigger_detail=f"[TT] emergency pause act={acc.act_id}")
                            db.commit()
                        except Exception:
                            db.rollback()
                    except Exception as e:
                        _st["errors"].append(f"[TT] {acc.name}/{ad_id[-8:]}: {str(e)[:50]}")
                # 回读核验：等 TT 写生效，重拉投放中广告，仍出现=核验未过
                _time.sleep(2)
                try:
                    still_ids = {str(a.get("ad_id") or a.get("id") or "")
                                 for a in tt.get_active_ads(acc.act_id)} & set(ad_ids)
                    if still_ids:
                        _st["verify_failed"] += len(still_ids)
                        _st["errors"].append(
                            f"[TT] {acc.name}: {len(still_ids)} 条仍投放中（TT 写延迟）: "
                            f"{[i[-8:] for i in list(still_ids)[:3]]}")
                except Exception:
                    pass  # 核验查询失败不阻断（信任 update_status 的成功返回）
                try:
                    _emergency_state_write(db, tenant_id, dict(_st))
                except Exception:
                    pass

        _st["errors"] = _st["errors"][:10]
        try:
            _emergency_state_write(db, tenant_id, dict(_st))   # 终态落 DB（跨 worker）
        except Exception:
            pass
    except Exception as e:
        if _EMERGENCY_STATE.get(tenant_id):
            _errs = _EMERGENCY_STATE[tenant_id].get("errors") or []
            _EMERGENCY_STATE[tenant_id]["errors"] = (_errs[:9] + [f"emergency_pause: {str(e)[:80]}"])[:10]
    finally:
        if db:
            db.close()
        if lock:
            release_run_lock(lock, 113)
        if _EMERGENCY_STATE.get(tenant_id):
            _EMERGENCY_STATE[tenant_id]["running"] = False
            try:
                _sdb = SuperSessionLocal()
                try:
                    _emergency_state_write(_sdb, tenant_id, dict(_EMERGENCY_STATE[tenant_id]))
                finally:
                    _sdb.close()
            except Exception:
                pass


@router.post("/emergency-pause")
def emergency_pause(background_tasks: BackgroundTasks,
                    user: CurrentUser = Depends(require_permission("ads.pause"))):
    """全局紧急暂停（后台异步）：同步 ads_cache → 逐个 PAUSE → 回读核验。
    立即返回，进度/结果查 GET /guard/emergency-status（前端轮询）。"""
    st = _EMERGENCY_STATE.get(user.tenant_id)
    if st and st.get("running"):
        return {"started": False, "running": True}
    background_tasks.add_task(_bg_emergency_pause, user.tenant_id, user.email)
    return {"started": True, "running": True}


@router.get("/emergency-status")
def emergency_status(user: CurrentUser = Depends(require_permission("ads.pause"))):
    """紧急暂停进度（DB 真相源——进程内 dict 多 worker 读不到会假报'暂停 0 条'）。"""
    import json as _json
    from ..core.database import SuperSessionLocal
    from ..models.system import SystemSetting
    _sdb = SuperSessionLocal()
    try:
        row = _sdb.query(SystemSetting).filter(SystemSetting.key == f'emergency_state_{user.tenant_id}').first()
        if row:
            try:
                return _json.loads(row.value)
            except Exception:
                pass
    finally:
        _sdb.close()
    return {"running": False, "paused": 0, "verify_failed": 0, "total_accounts": 0, "errors": []}


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
    else:
        # 全名下批量预热只碰在管账户（软删账户不 arm warming；显式点名不受限）
        query = query.filter(Account.is_managed.is_(True))
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


@router.post("/keepalive/run")
def manual_keepalive(user: CurrentUser = Depends(require_superadmin)):
    """手动触发保活扫描（平台级花钱操作——全租户扫描建广告，只能超管）。
    检查 warming/团队开关账户连续 idle_days 天无消耗 → 建 $5 主页赞。
    返回 {checked, created, skipped, failed}。"""
    from ..services.guard_engine import run_keepalive
    return run_keepalive()
