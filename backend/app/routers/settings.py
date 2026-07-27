"""系统设置路由：调度配置 + AI 配置。平台级，超管才能改。"""
import os
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from ..core.database import get_db
from ..core.deps import CurrentUser, require_superadmin
from ..core.schedule_config import (get_schedule_config, save_schedule_config,
                                     effective_intervals, DEFAULT_SCHEDULE)
from ..core.retention import (get_retention_config, save_retention_config,
                              run_data_retention, get_last_run, DEFAULT_RETENTION)
from ..core.config import settings
from ..core.log_utils import write_log, new_trace_id

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
def get_keepalive(user: CurrentUser = Depends(require_superadmin), db: Session = Depends(get_db)):
    from ..core.keepalive_config import get_keepalive_config
    return get_keepalive_config(db)


@router.put("/keepalive")
def set_keepalive(body: dict, user: CurrentUser = Depends(require_superadmin),
                  db: Session = Depends(get_db)):
    from ..core.keepalive_config import save_keepalive_config
    return save_keepalive_config(db, body)
