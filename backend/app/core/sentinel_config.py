"""哨兵倒计时（dead-man switch）配置读写。按租户存 SystemSetting 表 key='sentinel:{tenant_id}'。

团队超过 N 小时无任何登录态交互（deps 节流写 users.last_active_at）→ watchdog 自动
arm 全部纳管账户（sentinel_auto_armed）。默认关（用户 2026-09-12 定稿方案）。
"""
import json
from datetime import datetime, timezone
from ..models.system import SystemSetting
from sqlalchemy.orm import Session

DEFAULT_SENTINEL = {
    "auto_arm_enabled": False,   # 默认关（no-protection-periods/no-prefilled 同精神：不惊扰）
    "auto_arm_hours": 48,        # 无交互阈值（小时）；开启时刻也计入基线，刚开不会立即触发
}


def get_sentinel_config(db: Session, tenant_id: int) -> dict:
    key = f"sentinel:{tenant_id}"
    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if not row or not row.value:
        return dict(DEFAULT_SENTINEL)
    try:
        cfg = json.loads(row.value)
        for k, v in DEFAULT_SENTINEL.items():
            cfg.setdefault(k, v)
        return cfg
    except Exception:
        return dict(DEFAULT_SENTINEL)


def save_sentinel_config(db: Session, tenant_id: int, cfg: dict) -> dict:
    old = get_sentinel_config(db, tenant_id)
    merged = dict(DEFAULT_SENTINEL)
    merged.update({k: v for k, v in (cfg or {}).items() if k in DEFAULT_SENTINEL})
    # 开关 false→true 翻转时记开启时刻（倒计时基线之一：刚开启+从未活动 → 从开启时刻起数，
    # 不立即触发）；true→true 不刷新（改小时数不该重置倒计时）
    if merged["auto_arm_enabled"] and not old.get("auto_arm_enabled"):
        merged["auto_arm_enabled_at"] = datetime.now(timezone.utc).isoformat()
    elif old.get("auto_arm_enabled_at"):
        merged["auto_arm_enabled_at"] = old["auto_arm_enabled_at"]
    key = f"sentinel:{tenant_id}"
    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    value = json.dumps(merged, ensure_ascii=False)
    if not row:
        row = SystemSetting(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    db.commit()
    return merged


def sentinel_auto_arm_state(cfg: dict, last_active: datetime | None, now: datetime) -> str:
    """纯函数：返回 'off' | 'idle' | 'warn' | 'arm'（可单测）。
    基线 = max(最近活动, 开启时刻)——都缺 = 无信号，不 arm（宁纵勿枉）。"""
    if not cfg.get("auto_arm_enabled"):
        return "off"
    try:
        hours = max(1, int(cfg.get("auto_arm_hours") or 48))
    except (TypeError, ValueError):
        hours = 48
    enabled_at = None
    try:
        _ea = cfg.get("auto_arm_enabled_at")
        if _ea:
            enabled_at = datetime.fromisoformat(_ea)
            if enabled_at.tzinfo is None:
                enabled_at = enabled_at.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        enabled_at = None
    candidates = [t for t in (last_active, enabled_at) if t is not None]
    if not candidates:
        return "idle"
    if last_active is not None and last_active.tzinfo is None:
        last_active = last_active.replace(tzinfo=timezone.utc)
    baseline = max(t.astimezone(timezone.utc) for t in candidates)
    elapsed = (now.astimezone(timezone.utc) - baseline).total_seconds() / 3600
    if elapsed >= hours:
        return "arm"
    if elapsed >= hours * 0.75:
        return "warn"
    return "idle"
