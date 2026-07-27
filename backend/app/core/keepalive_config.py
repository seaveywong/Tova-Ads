"""保活（Keepalive）配置读写。照 schedule_config 模式，存 SystemSetting 表 key='keepalive'。"""
import json
from ..models.system import SystemSetting
from sqlalchemy.orm import Session

DEFAULT_KEEPALIVE = {
    "budget_usd": 5,              # 每条保活广告总预算（lifetime，花完自动停）
    "idle_days": 3,                # 连续 N 天无消耗 → 触发保活
    "asset_prefix": "YR",          # 素材库保活素材名前缀
    "campaign_prefix": "[Tova-保活]",  # 系列名标记（巡检/哨兵见此标记跳过不停）
    "objective": "OUTCOME_ENGAGEMENT",
    "conversion_goal": "page_likes",
}


def get_keepalive_config(db: Session) -> dict:
    row = db.query(SystemSetting).filter(SystemSetting.key == "keepalive").first()
    if not row or not row.value:
        return dict(DEFAULT_KEEPALIVE)
    try:
        cfg = json.loads(row.value)
        # 补默认值（新增字段时旧配置可能缺）
        for k, v in DEFAULT_KEEPALIVE.items():
            cfg.setdefault(k, v)
        return cfg
    except Exception:
        return dict(DEFAULT_KEEPALIVE)


def save_keepalive_config(db: Session, cfg: dict) -> dict:
    merged = dict(DEFAULT_KEEPALIVE)
    merged.update({k: v for k, v in cfg.items() if k in DEFAULT_KEEPALIVE})
    row = db.query(SystemSetting).filter(SystemSetting.key == "keepalive").first()
    if not row:
        row = SystemSetting(key="keepalive", value=json.dumps(merged, ensure_ascii=False))
        db.add(row)
    else:
        row.value = json.dumps(merged, ensure_ascii=False)
    db.commit()
    return merged
