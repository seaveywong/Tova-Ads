"""哨兵倒计时（dead-man switch）配置读写。

粒度 = 个人（2026-09-15 用户拍板：不针对团队）——每个用户自己的开关/小时数/倒计时，
key = sentinel_scd:{tenant_id}:{user_id}。无交互超时按该用户自己的 last_active_at 判断，
到期 arm 其所属租户的纳管账户（停广告动作天然是账户级）。
历史：2026-09-14 首版为租户级（key=sentinel:{tid}），GET 时自动收编为当前用户的个人配置。
"""
import json
from datetime import datetime, timezone
from ..models.system import SystemSetting
from sqlalchemy.orm import Session

DEFAULT_SENTINEL = {
    "auto_arm_enabled": False,   # 默认关（no-protection-periods 同精神：不惊扰）
    "auto_arm_hours": 48,        # 个人无登录阈值（小时）；开启时刻也计入基线
}

_LEGACY_TENANT_PREFIX = "sentinel:"   # 09-14 租户级旧键（无用户段）


def _key(tenant_id: int, user_id: int) -> str:
    return f"sentinel_scd:{tenant_id}:{user_id}"


def _load(db: Session, key: str) -> dict | None:
    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if not row or not row.value:
        return None
    try:
        return json.loads(row.value)
    except Exception:
        return None


def get_sentinel_config(db: Session, tenant_id: int, user_id: int) -> dict:
    cfg = _load(db, _key(tenant_id, user_id))
    if cfg is None:
        # 迁移收编：个人键不存在 → 读旧租户键（谁先开谁继承为自己的个人配置）
        for row in db.query(SystemSetting).filter(
                SystemSetting.key == f"{_LEGACY_TENANT_PREFIX}{tenant_id}").all():
            try:
                legacy = json.loads(row.value or "{}")
            except Exception:
                continue
            if "auto_arm_enabled" in legacy:
                cfg = legacy
                break
    out = dict(DEFAULT_SENTINEL)
    if cfg:
        for k, v in DEFAULT_SENTINEL.items():
            if k in cfg:
                out[k] = cfg[k]
    return out


def save_sentinel_config(db: Session, tenant_id: int, user_id: int, cfg: dict) -> dict:
    old = _load(db, _key(tenant_id, user_id)) or {}
    merged = dict(DEFAULT_SENTINEL)
    merged.update({k: v for k, v in (cfg or {}).items() if k in DEFAULT_SENTINEL})
    # 开关 false→true 翻转记开启时刻（倒计时基线之一：刚开不立即触发）；true→true 不刷新
    if merged["auto_arm_enabled"] and not old.get("auto_arm_enabled"):
        merged["auto_arm_enabled_at"] = datetime.now(timezone.utc).isoformat()
    elif old.get("auto_arm_enabled_at"):
        merged["auto_arm_enabled_at"] = old["auto_arm_enabled_at"]
    key = _key(tenant_id, user_id)
    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    value = json.dumps(merged, ensure_ascii=False)
    if not row:
        db.add(SystemSetting(key=key, value=value))
    else:
        row.value = value
    db.commit()
    return merged


def list_enabled_user_configs(db: Session) -> list[tuple[int, int, dict]]:
    """全部开启了倒计时的 (tenant_id, user_id, cfg)——watchdog 检查用。"""
    out = []
    prefix = "sentinel_scd:"
    for row in db.query(SystemSetting).filter(
            SystemSetting.key.like(prefix + "%")).all():
        try:
            _, tid, uid = row.key.split(":")
            cfg = json.loads(row.value or "{}")
        except Exception:
            continue
        if cfg.get("auto_arm_enabled"):
            out.append((int(tid), int(uid), cfg))
    return out


def sentinel_auto_arm_state(cfg: dict, last_active: datetime | None, now: datetime) -> str:
    """纯函数：返回 'off' | 'idle' | 'warn' | 'arm'（可单测）。
    基线 = max(本人最近活动, 开启时刻)——都缺 = 无信号不 arm。"""
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
