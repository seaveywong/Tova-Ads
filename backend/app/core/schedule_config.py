"""调度配置（base × 倍数，可前端配置 + live reschedule）。

任务实际间隔 = base_minutes × 该任务的倍数；哨兵固定 3min（kill-switch，不绑 base）。
存 system_settings['schedule']（全局，平台级）。
"""
import json
from sqlalchemy.orm import Session
from ..models.system import SystemSetting

DEFAULT_SCHEDULE = {
    "base_minutes": 5,
    "sentinel_minutes": 3,  # 哨兵巡逻（kill-switch，可调，限 1-10 分钟）
    "multipliers": {
        "inspect": 1,        # 巡检（止损评估，按广告，最勤）
        "watchdog": 2,       # 令牌健康（debug_token）
        "account_sync": 6,   # 账户状态/余额
        "budget": 3,         # 预算进度告警
        "reassociate": 24,   # 失效账户重绑（拉全量账户，最贵，必须慢）
        "subcode": 12,       # 子码自动绑定
    },
}

# 任务 key → APScheduler job_id（main.py 注册时用）
JOB_IDS = {
    "inspect": "guard_inspect", "budget": "budget_alerts", "watchdog": "system_watchdog",
    "reassociate": "reassociate_orphans", "subcode": "subcode_autobind",
    "sentinel": "sentinel_patrol", "account_sync": "account_status_sync",
}


def get_schedule_config(db: Session) -> dict:
    row = db.query(SystemSetting).filter(SystemSetting.key == "schedule").first()
    if row and row.value:
        try:
            cfg = json.loads(row.value)
            return {
                "base_minutes": cfg.get("base_minutes", DEFAULT_SCHEDULE["base_minutes"]),
                "sentinel_minutes": max(1, min(10, cfg.get("sentinel_minutes", DEFAULT_SCHEDULE["sentinel_minutes"]))),
                "multipliers": {**DEFAULT_SCHEDULE["multipliers"], **(cfg.get("multipliers") or {})},
            }
        except Exception:
            pass
    return {"base_minutes": DEFAULT_SCHEDULE["base_minutes"],
            "sentinel_minutes": DEFAULT_SCHEDULE["sentinel_minutes"],
            "multipliers": dict(DEFAULT_SCHEDULE["multipliers"])}


def save_schedule_config(db: Session, base_minutes: int, multipliers: dict,
                         sentinel_minutes: int = None):
    # 值归一：前端 v-model.number 清空会送 ''，0/负数同理——原样入库会在重启时
    # base*'' TypeError 打挂 scheduler 注册（全 cron 瘫痪）。这里兜底归一为正整数。
    def _norm_int(v, default, lo, hi):
        try:
            n = int(v)
        except (TypeError, ValueError):
            return default
        return max(lo, min(hi, n)) if n > 0 else default
    bm = _norm_int(base_minutes, DEFAULT_SCHEDULE["base_minutes"], 1, 120)
    sm = _norm_int(sentinel_minutes, DEFAULT_SCHEDULE["sentinel_minutes"], 1, 10)
    _mult = {}
    for k, v in {**DEFAULT_SCHEDULE["multipliers"], **(multipliers or {})}.items():
        _mult[k] = _norm_int(v, DEFAULT_SCHEDULE["multipliers"].get(k, 1), 1, 720)
    val = json.dumps({"base_minutes": bm, "sentinel_minutes": sm, "multipliers": _mult})
    row = db.query(SystemSetting).filter(SystemSetting.key == "schedule").first()
    if row:
        row.value = val
    else:
        db.add(SystemSetting(key="schedule", value=val))
    db.commit()


def effective_intervals(cfg: dict) -> dict:
    try:
        base = int(cfg.get("base_minutes", 5))
    except (TypeError, ValueError):
        base = 5
    out = {}
    for k, v in (cfg.get("multipliers") or {}).items():
        try:
            out[k] = max(1, base * int(v))   # 防御：历史毒化数据也归一，scheduler 注册不再 TypeError
        except (TypeError, ValueError):
            out[k] = base * DEFAULT_SCHEDULE["multipliers"].get(k, 1)
    try:
        out["sentinel"] = max(1, min(10, int(cfg.get("sentinel_minutes", 3) or 3)))
    except (TypeError, ValueError):
        out["sentinel"] = 3
    return out
