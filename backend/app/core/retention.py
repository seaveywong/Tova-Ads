"""数据保留策略（平台级，可前端配置）。

哪些表的老数据到期清理 + 保留天数。存 system_settings['retention']（JSON）。
每日 cron run_data_retention 按配置 DELETE 老行。

注意：accounts / landing_pages / ads_cache / 配置表不在清理范围（配置+历史永久保留）。
"""
import json
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text
from ..models.system import SystemSetting

# 表 → (日期列, 默认保留天数, 说明)。0 或负数 = 不清理该表（永久保留）
DEFAULT_RETENTION = {
    "perf_snapshots":     {"col": "snapshot_date", "days": 90, "label": "广告消耗快照"},
    "landing_events":     {"col": "created_at",    "days": 60, "label": "落地访问/点击/拦截日志"},
    "action_logs":        {"col": "created_at",    "days": 90, "label": "操作/巡检审计"},
    "notifications":      {"col": "created_at",    "days": 30, "label": "告警通知"},
    "perf_snapshot_ticks":{"col": "snapshot_at",   "days": 30, "label": "增量消耗 tick（瞬烧用）"},
    "token_health":       {"col": "last_checked_at","days": 30, "label": "令牌健康历史"},
    "guard_allowances":   {"col": "created_at",    "days": 30, "label": "加白名单记录"},
}

# 清理是平台级（跨租户），用 super 角色绕 RLS
_LAST_RUN_KEY = "retention_last_run"


def get_retention_config(db: Session) -> dict:
    """返回 {table: days}（合并默认 + 用户覆盖）+ 各表 label。"""
    row = db.query(SystemSetting).filter(SystemSetting.key == "retention").first()
    overrides = {}
    if row and row.value:
        try:
            overrides = json.loads(row.value) or {}
        except Exception:
            overrides = {}
    out = {}
    for t, meta in DEFAULT_RETENTION.items():
        days = overrides.get(t, meta["days"])
        if days is None or days < 0:
            days = 0  # 0 = 永久保留（不清理）
        out[t] = {"col": meta["col"], "days": days, "label": meta["label"]}
    return out


def save_retention_config(db: Session, days_map: dict):
    """days_map: {table: days}。只存用户显式设置的（覆盖默认）。"""
    clean = {}
    for t, days in (days_map or {}).items():
        if t in DEFAULT_RETENTION and days is not None and int(days) >= 0:
            clean[t] = int(days)
    val = json.dumps(clean)
    row = db.query(SystemSetting).filter(SystemSetting.key == "retention").first()
    if row:
        row.value = val
    else:
        db.add(SystemSetting(key="retention", value=val))
    db.commit()


def run_data_retention() -> dict:
    """每日清理：按配置 DELETE 各表超期行。平台级（super 角色绕 RLS）。返回 {table: deleted}。"""
    from ..core.database import SuperSessionLocal
    db = SuperSessionLocal()
    result = {}
    try:
        cfg = get_retention_config(db)
        now = datetime.now(timezone.utc)
        for table, meta in cfg.items():
            days = meta.get("days", 0)
            col = meta["col"]
            if not days or days <= 0:
                result[table] = {"deleted": 0, "kept_days": "永久"}
                continue
            cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            try:
                # col 是白名单硬编码（DEFAULT_RETENTION），无注入风险
                r = db.execute(text(f"DELETE FROM {table} WHERE {col} < :cutoff"), {"cutoff": cutoff})
                result[table] = {"deleted": r.rowcount or 0, "kept_days": days}
                db.commit()
            except Exception as e:
                db.rollback()
                result[table] = {"deleted": 0, "kept_days": days, "error": str(e)[:80]}
        # 记录上次清理时间
        lr = db.query(SystemSetting).filter(SystemSetting.key == _LAST_RUN_KEY).first()
        ts = now.isoformat()
        if lr:
            lr.value = ts
        else:
            db.add(SystemSetting(key=_LAST_RUN_KEY, value=ts))
        db.commit()
    finally:
        db.close()
    return result


def get_last_run(db: Session) -> str:
    row = db.query(SystemSetting).filter(SystemSetting.key == _LAST_RUN_KEY).first()
    return row.value if row else ""
