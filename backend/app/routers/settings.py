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
class AiConfigIn(BaseModel):
    ai_base_url: str = ""
    ai_api_key: str = ""
    ai_model: str = ""


@router.get("/ai")
def get_ai_config(user: CurrentUser = Depends(require_superadmin)):
    """返回当前 AI 配置（key 脱敏）。"""
    key = settings.ai_api_key or ""
    masked = key[:6] + "***" + key[-4:] if len(key) > 10 else ("***" if key else "")
    return {
        "ai_base_url": settings.ai_base_url or "",
        "ai_api_key_masked": masked,
        "ai_api_key_set": bool(key),
        "ai_model": settings.ai_model or "",
    }


@router.put("/ai")
def set_ai_config(body: AiConfigIn, user: CurrentUser = Depends(require_superadmin)):
    """更新 AI 配置 → 写 .env + 更新运行时 settings。"""
    from pathlib import Path
    env_path = Path("/opt/toveads/backend/.env")
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    updates = {}
    if body.ai_base_url:
        updates["AI_BASE_URL"] = body.ai_base_url
    if body.ai_api_key:
        updates["AI_API_KEY"] = body.ai_api_key
    if body.ai_model:
        updates["AI_MODEL"] = body.ai_model
    if not updates:
        return {"saved": False, "detail": "无变更"}
    # 更新 .env 文件
    updated_lines = []
    found_keys = set()
    for line in lines:
        stripped = line.strip()
        if "=" in stripped:
            k = stripped.split("=", 1)[0]
            if k in updates:
                updated_lines.append(f"{k}={updates[k]}")
                found_keys.add(k)
                continue
        updated_lines.append(line)
    for k, v in updates.items():
        if k not in found_keys:
            updated_lines.append(f"{k}={v}")
    env_path.write_text("\n".join(updated_lines) + "\n")
    # 更新运行时
    if "AI_BASE_URL" in updates:
        settings.ai_base_url = updates["AI_BASE_URL"]
    if "AI_API_KEY" in updates:
        settings.ai_api_key = updates["AI_API_KEY"]
    if "AI_MODEL" in updates:
        settings.ai_model = updates["AI_MODEL"]
    return {"saved": True}


@router.post("/ai/test")
def test_ai(user: CurrentUser = Depends(require_superadmin)):
    """测试 AI 连接。"""
    from ..core.ai_client import AiClient
    client = AiClient()
    if not client.is_configured():
        return {"ok": False, "detail": "AI 未配置（key 为空）"}
    try:
        resp = client.chat([{"role": "user", "content": "回复 OK"}], temperature=0, max_tokens=10)
        return {"ok": True, "detail": resp[:50]}
    except Exception as e:
        return {"ok": False, "detail": str(e)[:100]}


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
