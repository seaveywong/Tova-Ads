"""保活（Keepalive）配置读写。按租户存 SystemSetting 表 key='keepalive:{tenant_id}'。
各团队自己管理保活参数（预算/天数/开关），超管不参与。"""
import json
from ..models.system import SystemSetting
from sqlalchemy.orm import Session

DEFAULT_KEEPALIVE = {
    "enabled": False,              # 团队开关：true=该团队所有 managed 账户自动纳入保活
    "budget_usd": 5,              # 每条保活广告总预算（lifetime，花完自动停）
    "idle_days": 3,                # 连续 N 天无消耗 → 触发保活
    "asset_prefix": "YR",          # 素材库保活素材名前缀
    "campaign_prefix": "[Tova-保活]",  # 系列名标记（巡检/哨兵见此标记跳过不停）
    "objective": "OUTCOME_ENGAGEMENT",
    "conversion_goal": "page_likes",
}


def get_keepalive_config(db: Session, tenant_id: int = 0) -> dict:
    key = f"keepalive:{tenant_id}" if tenant_id else "keepalive"
    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if not row or not row.value:
        return dict(DEFAULT_KEEPALIVE)
    try:
        cfg = json.loads(row.value)
        for k, v in DEFAULT_KEEPALIVE.items():
            cfg.setdefault(k, v)
        return cfg
    except Exception:
        return dict(DEFAULT_KEEPALIVE)


def save_keepalive_config(db: Session, tenant_id: int, cfg: dict) -> dict:
    merged = dict(DEFAULT_KEEPALIVE)
    merged.update({k: v for k, v in cfg.items() if k in DEFAULT_KEEPALIVE})
    key = f"keepalive:{tenant_id}"
    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if not row:
        row = SystemSetting(key=key, value=json.dumps(merged, ensure_ascii=False))
        db.add(row)
    else:
        row.value = json.dumps(merged, ensure_ascii=False)
    db.commit()
    return merged
