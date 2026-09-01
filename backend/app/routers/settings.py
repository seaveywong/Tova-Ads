"""系统设置路由：调度配置 + AI 配置。平台级，超管才能改。"""
import json
import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from ..core.database import get_db
from ..core.deps import CurrentUser, require_superadmin, require_permission
from ..core.schedule_config import (get_schedule_config, save_schedule_config,
                                     effective_intervals, DEFAULT_SCHEDULE)
from ..core.retention import (get_retention_config, save_retention_config,
                              run_data_retention, get_last_run, DEFAULT_RETENTION)
from ..core.config import settings
from ..core.log_utils import write_log, new_trace_id
from ..models.system import SystemSetting

router = APIRouter(prefix="/settings", tags=["settings"])


class ScheduleIn(BaseModel):
    base_minutes: int = DEFAULT_SCHEDULE["base_minutes"]
    sentinel_minutes: int | None = None
    multipliers: dict = {}


@router.get("/schedule")
def get_schedule(user: CurrentUser = Depends(require_superadmin), db: Session = Depends(get_db)):
    cfg = get_schedule_config(db)
    eff = effective_intervals(cfg)
    return {
        "base_minutes": cfg["base_minutes"],
        "sentinel_minutes": cfg["sentinel_minutes"],
        "multipliers": cfg["multipliers"],
        "effective": eff,
        "task_labels": {
            "inspect": "巡检（止损评估）", "watchdog": "令牌健康检查",
            "account_sync": "账户状态/余额", "budget": "预算进度告警",
            "reassociate": "失效账户重绑", "subcode": "子码自动绑定",
            "sentinel": "哨兵巡逻",
        },
    }


@router.put("/schedule")
def set_schedule(body: ScheduleIn, user: CurrentUser = Depends(require_superadmin),
                 db: Session = Depends(get_db)):
    base = body.base_minutes if body.base_minutes and body.base_minutes >= 1 else DEFAULT_SCHEDULE["base_minutes"]
    sm = body.sentinel_minutes if body.sentinel_minutes and 1 <= body.sentinel_minutes <= 10 else None
    save_schedule_config(db, base, body.multipliers, sm)
    cfg = {"base_minutes": base, "sentinel_minutes": sm or DEFAULT_SCHEDULE["sentinel_minutes"],
           "multipliers": body.multipliers}
    from ..main import reschedule_jobs
    reschedule_jobs(cfg)
    return {"effective": effective_intervals(cfg)}


# ── 巡检与告警调优（超管）──
# 三个系统旋钮（平台级，system_settings.value 存 JSON 数字）：
#   guard_concurrency    巡检并发 1-8（guard_engine._max_workers 每轮现读，下一轮生效）
#   guard_learning_hours 学习期保护小时数，0=关（guard_engine 每轮现读）
#   notify_storm_cap     每租户每事件当日告警上限，0=不封顶（notify_utils 60s TTL 缓存，保存后主动失效）
class GuardTuningIn(BaseModel):
    guard_concurrency: int
    guard_learning_hours: int
    notify_storm_cap: int


def _setting_num(db: Session, key: str, default: float) -> float:
    """读 system_settings 数值（value 存 JSON）。缺省/脏值 → default（与 guard_engine._sys_float 同语义）。"""
    try:
        row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if row and row.value not in (None, ""):
            return float(json.loads(row.value))
    except Exception:
        pass
    return default


@router.get("/guard-tuning")
def get_guard_tuning(user: CurrentUser = Depends(require_superadmin), db: Session = Depends(get_db)):
    """三键当前生效值 + 默认值。生效值按读方口径钳制（并发 1-8、风暴上限 ≥0）。"""
    from ..services.guard_engine import DEFAULT_CONCURRENCY, DEFAULT_LEARNING_HOURS
    from ..core.notify_utils import DEFAULT_STORM_CAP
    conc = max(1, min(int(_setting_num(db, "guard_concurrency", DEFAULT_CONCURRENCY)), 8))
    learn = _setting_num(db, "guard_learning_hours", DEFAULT_LEARNING_HOURS)
    storm = max(0, int(_setting_num(db, "notify_storm_cap", DEFAULT_STORM_CAP)))
    return {
        "guard_concurrency": conc,
        "guard_learning_hours": int(learn) if learn == int(learn) else learn,
        "notify_storm_cap": storm,
        "defaults": {
            "guard_concurrency": int(DEFAULT_CONCURRENCY),
            "guard_learning_hours": int(DEFAULT_LEARNING_HOURS),
            "notify_storm_cap": int(DEFAULT_STORM_CAP),
        },
    }


@router.put("/guard-tuning")
def set_guard_tuning(body: GuardTuningIn, user: CurrentUser = Depends(require_superadmin),
                     db: Session = Depends(get_db)):
    """写三键（value 存 JSON 数字）。storm_cap 写后失效 TTL 缓存立即生效；另两键下一轮巡检现读。"""
    if not 1 <= body.guard_concurrency <= 8:
        raise HTTPException(400, "巡检并发需为 1-8 的整数")
    if not 0 <= body.guard_learning_hours <= 720:
        raise HTTPException(400, "学习期保护需为 0-720 的整数（0=关闭）")
    if not 0 <= body.notify_storm_cap <= 1000:
        raise HTTPException(400, "告警风暴上限需为 0-1000 的整数（0=不封顶）")
    for key, val in (("guard_concurrency", body.guard_concurrency),
                     ("guard_learning_hours", body.guard_learning_hours),
                     ("notify_storm_cap", body.notify_storm_cap)):
        row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if row:
            row.value = json.dumps(val)
        else:
            db.add(SystemSetting(key=key, value=json.dumps(val)))
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, target_type="system_setting", target_id="guard_tuning",
              action_type="update", source="user", result="success",
              metadata={"guard_concurrency": body.guard_concurrency,
                        "guard_learning_hours": body.guard_learning_hours,
                        "notify_storm_cap": body.notify_storm_cap})
    db.commit()
    from ..core.notify_utils import reset_storm_cap_cache
    reset_storm_cap_cache()
    return get_guard_tuning(user=user, db=db)


# ── AI 配置（超管）──
# 文案/KPI 走 ai_*（DeepSeek），素材看图走 ai_vision_*（Gemini）。两组都在此 UI 配。
# ENV 变量名 → settings 属性名（写 .env + 运行时热重载用）
_AI_ENV_ATTR = {
    "AI_BASE_URL": "ai_base_url", "AI_API_KEY": "ai_api_key", "AI_MODEL": "ai_model",
    "AI_VISION_BASE_URL": "ai_vision_base_url",
    "AI_VISION_API_KEY": "ai_vision_api_key",
    "AI_VISION_MODEL": "ai_vision_model",
}


def _write_env_and_reload(updates: dict):
    """写 .env（更新已有行或追加）+ 运行时 settings 热重载。updates = {ENV_KEY: value}。"""
    from pathlib import Path
    env_path = Path("/opt/toveads/backend/.env")
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    updated_lines, found = [], set()
    for line in lines:
        stripped = line.strip()
        if "=" in stripped:
            k = stripped.split("=", 1)[0]
            if k in updates:
                updated_lines.append(f"{k}={updates[k]}")
                found.add(k)
                continue
        updated_lines.append(line)
    for k, v in updates.items():
        if k not in found:
            updated_lines.append(f"{k}={v}")
    env_path.write_text("\n".join(updated_lines) + "\n")
    for env_key, val in updates.items():
        attr = _AI_ENV_ATTR.get(env_key)
        if attr:
            setattr(settings, attr, val)


def _mask(s: str) -> str:
    s = s or ""
    return s[:6] + "***" + s[-4:] if len(s) > 10 else ("***" if s else "")


class AiConfigIn(BaseModel):
    ai_base_url: str = ""
    ai_api_key: str = ""
    ai_model: str = ""
    ai_vision_base_url: str = ""
    ai_vision_api_key: str = ""
    ai_vision_model: str = ""


@router.get("/ai")
def get_ai_config(user: CurrentUser = Depends(require_superadmin)):
    """返回当前 AI 配置（文案 + 视觉，key 脱敏）。"""
    return {
        "ai_base_url": settings.ai_base_url or "",
        "ai_api_key_masked": _mask(settings.ai_api_key),
        "ai_api_key_set": bool(settings.ai_api_key),
        "ai_model": settings.ai_model or "",
        "ai_vision_base_url": settings.ai_vision_base_url or "",
        "ai_vision_api_key_masked": _mask(settings.ai_vision_api_key),
        "ai_vision_api_key_set": bool(settings.ai_vision_api_key),
        "ai_vision_model": settings.ai_vision_model or "",
    }


@router.put("/ai")
def set_ai_config(body: AiConfigIn, user: CurrentUser = Depends(require_superadmin),
                  db: Session = Depends(get_db)):
    """更新 AI 配置（文案/视觉）→ 写 .env + 热重载 settings。空字段=不改。"""
    field_to_env = {
        "ai_base_url": "AI_BASE_URL", "ai_api_key": "AI_API_KEY", "ai_model": "AI_MODEL",
        "ai_vision_base_url": "AI_VISION_BASE_URL",
        "ai_vision_api_key": "AI_VISION_API_KEY",
        "ai_vision_model": "AI_VISION_MODEL",
    }
    updates = {}
    for field, env_key in field_to_env.items():
        val = getattr(body, field)
        if val:
            updates[env_key] = val
    if not updates:
        return {"saved": False, "detail": "无变更"}
    _write_env_and_reload(updates)
    changed = sorted(k for k in updates if "KEY" in k)
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, target_type="system_setting", target_id="ai_config",
              action_type="update", source="user", result="success",
              metadata={"changed_fields": sorted(updates.keys()), "key_fields_changed": changed})
    return {"saved": True}


@router.post("/ai/test")
def test_ai(vision: bool = False, user: CurrentUser = Depends(require_superadmin)):
    """测试 AI 连接。vision=False 测文案(DeepSeek)，vision=True 测视觉(Gemini 看图)。"""
    from ..core.ai_client import AiClient, vision_client
    client = vision_client() if vision else AiClient()
    label = "视觉" if vision else "文案"
    if not client.is_configured():
        return {"ok": False, "detail": f"{label} AI 未配置（key 为空）"}
    try:
        # max_tokens 留够：gemini-2.5-flash 是 thinking 模型，10 token 会被推理吃光→空 content
        resp = client.chat([{"role": "user", "content": "回复 OK"}], temperature=0, max_tokens=64)
        return {"ok": True, "detail": resp[:50]}
    except Exception as e:
        return {"ok": False, "detail": str(e)[:120]}


# ── CF 配置（超管）──
class CfConfigIn(BaseModel):
    cf_api_token: str = ""
    cf_account_id: str = ""


@router.get("/cf")
def get_cf_config(user: CurrentUser = Depends(require_superadmin)):
    """返回当前 CF 配置（token 脱敏）。"""
    token = settings.cf_api_token or ""
    masked = token[:6] + "***" + token[-4:] if len(token) > 10 else ("***" if token else "")
    return {
        "cf_api_token_masked": masked,
        "cf_api_token_set": bool(token),
        "cf_account_id": settings.cf_account_id or "",
    }


@router.put("/cf")
def set_cf_config(body: CfConfigIn, user: CurrentUser = Depends(require_superadmin)):
    """更新 CF 配置 → 写 .env + 更新运行时 settings（即时生效，免重启）。"""
    from pathlib import Path
    env_path = Path("/opt/toveads/backend/.env")
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    updates = {}
    if body.cf_api_token:
        updates["CF_API_TOKEN"] = body.cf_api_token
    if body.cf_account_id:
        updates["CF_ACCOUNT_ID"] = body.cf_account_id
    if not updates:
        return {"saved": False, "detail": "无变更"}
    updated_lines, found = [], set()
    for line in lines:
        s = line.strip()
        if "=" in s:
            k = s.split("=", 1)[0]
            if k in updates:
                updated_lines.append(f"{k}={updates[k]}"); found.add(k); continue
        updated_lines.append(line)
    for k, v in updates.items():
        if k not in found:
            updated_lines.append(f"{k}={v}")
    env_path.write_text("\n".join(updated_lines) + "\n")
    if "CF_API_TOKEN" in updates:
        settings.cf_api_token = updates["CF_API_TOKEN"]
    if "CF_ACCOUNT_ID" in updates:
        settings.cf_account_id = updates["CF_ACCOUNT_ID"]
    return {"saved": True}


# ── 数据保留（超管）── 各表老数据保留天数，0=永久
class RetentionIn(BaseModel):
    days: dict = {}  # {table: days}，缺省用默认


@router.get("/retention")
def get_retention(user: CurrentUser = Depends(require_superadmin), db: Session = Depends(get_db)):
    cfg = get_retention_config(db)
    return {
        "tables": [{"key": t, "label": m["label"], "days": m["days"], "col": m["col"]} for t, m in cfg.items()],
        "last_run": get_last_run(db),
    }


@router.put("/retention")
def set_retention(body: RetentionIn, user: CurrentUser = Depends(require_superadmin),
                  db: Session = Depends(get_db)):
    save_retention_config(db, body.days)
    return get_retention(user=user, db=db)


@router.post("/retention/run")
def run_retention_now(user: CurrentUser = Depends(require_superadmin)):
    """手动触发一次清理（不等每日 cron）。"""
    return run_data_retention()


@router.get("/fx")
def get_fx(user: CurrentUser = Depends(require_superadmin), db: Session = Depends(get_db)):
    """当前汇率快照（止损 to_usd 用）。"""
    from ..models.perf import CurrencyRate
    rows = db.query(CurrencyRate).order_by(CurrencyRate.code).all()
    return {"rates": [{"code": r.code, "rate": r.rate, "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None} for r in rows],
            "count": len(rows)}


@router.post("/fx/run")
def run_fx_now(user: CurrentUser = Depends(require_superadmin)):
    """手动拉一次实时汇率（不等每日 cron）。"""
    from ..services.fx_sync import run_fx_sync
    return run_fx_sync()


@router.get("/keepalive")
def get_keepalive(user: CurrentUser = Depends(require_permission("ads.pause")), db: Session = Depends(get_db)):
    from ..core.keepalive_config import get_keepalive_config
    return get_keepalive_config(db, user.tenant_id)


@router.put("/keepalive")
def set_keepalive(body: dict, user: CurrentUser = Depends(require_permission("ads.pause")),
                  db: Session = Depends(get_db)):
    from ..core.keepalive_config import save_keepalive_config
    return save_keepalive_config(db, user.tenant_id, body)


# ── FB Webhook 配置（超管）── verify_token 存 system_settings，App Secret 复用 fb_apps 表
class WebhookIn(BaseModel):
    verify_token: str = ""


@router.get("/webhook")
def get_webhook(user: CurrentUser = Depends(require_superadmin), db: Session = Depends(get_db)):
    """返回 webhook 配置：公开 URL（只读）+ verify_token（脱敏）+ active App 数。"""
    from ..core.webhook_config import get_webhook_config
    from ..models.fb_app import FbApp
    cfg = get_webhook_config(db)
    vt = cfg["verify_token"]
    masked = (vt[:4] + "***" + vt[-3:]) if vt and len(vt) > 8 else ("***" if vt else "")
    apps = db.query(FbApp).filter(FbApp.status == "active").all()
    return {
        "public_url": cfg["public_url"],
        "verify_token_masked": masked,
        "verify_token_set": bool(vt),
        "verify_token_is_default": vt == "toveads_webhook_verify",
        "active_apps": len(apps),
        "app_names": [a.name or f"App {a.app_id}" for a in apps],
    }


@router.put("/webhook")
def set_webhook(body: WebhookIn, user: CurrentUser = Depends(require_superadmin),
                db: Session = Depends(get_db)):
    """更新 verify_token（空=恢复默认值）。DB 即时生效，免重启。"""
    from ..core.webhook_config import save_webhook_config
    save_webhook_config(db, body.verify_token)
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, target_type="system_setting", target_id="fb_webhook",
              action_type="update", source="user", result="success",
              metadata={"field": "verify_token"})
    return {"saved": True}
