"""KPI 配置路由：手动指定 campaign 的 KPI 转化字段 + target_cpa（KPI resolver L0，审计项目10/11）。

用法：给某 campaign 设 target_cpa（让 cpa_exceed/consecutive_bad 用真实目标 CPA），
和/或手动指定 kpi_field（覆盖 resolver 自动解析）。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from ..core.database import get_db
from ..core.deps import CurrentUser, require_permission
from ..core.log_utils import write_log, new_trace_id
from ..models.kpi import KpiConfig

router = APIRouter(prefix="/kpi", tags=["kpi"])


class KpiConfigIn(BaseModel):
    target_id: str               # campaign_id
    kpi_field: str | None = None  # 手动指定转化 action_type；空=走 resolver 自动
    target_cpa: float | None = None  # 目标 CPA（USD）
    target_type: str = "campaign"


@router.get("")
def list_kpi(user: CurrentUser = Depends(require_permission("ads.read")),
             db: Session = Depends(get_db)):
    rows = db.query(KpiConfig).filter(KpiConfig.tenant_id == user.tenant_id).all()
    return [{"id": r.id, "target_type": r.target_type, "target_id": r.target_id,
             "kpi_field": r.kpi_field, "target_cpa": r.target_cpa,
             "source": r.source, "enabled": r.enabled} for r in rows]


@router.post("")
def set_kpi(body: KpiConfigIn, user: CurrentUser = Depends(require_permission("rules.create")),
            db: Session = Depends(get_db)):
    """upsert：同租户同 target 的 kpi_configs 覆盖。"""
    existing = db.query(KpiConfig).filter(
        KpiConfig.tenant_id == user.tenant_id,
        KpiConfig.target_type == body.target_type,
        KpiConfig.target_id == body.target_id,
    ).first()
    if existing:
        existing.kpi_field = body.kpi_field
        existing.target_cpa = body.target_cpa
        existing.enabled = True
        row = existing
    else:
        row = KpiConfig(tenant_id=user.tenant_id, target_type=body.target_type,
                        target_id=body.target_id, kpi_field=body.kpi_field,
                        target_cpa=body.target_cpa, source="manual")
        db.add(row)
    db.flush()
    tid = new_trace_id()
    write_log(db, tenant_id=user.tenant_id, trace_id=tid, actor_type="user",
              actor_user_id=user.id, target_type="kpi_config", target_id=str(row.id),
              action_type="upsert", source="user", result="success",
              metadata={"campaign_id": body.target_id, "target_cpa": body.target_cpa})
    db.commit()
    return {"id": row.id, "trace_id": tid, "target_id": body.target_id,
            "kpi_field": body.kpi_field, "target_cpa": body.target_cpa}


@router.delete("/{kid}")
def delete_kpi(kid: int, user: CurrentUser = Depends(require_permission("rules.create")),
               db: Session = Depends(get_db)):
    row = db.query(KpiConfig).filter(
        KpiConfig.id == kid, KpiConfig.tenant_id == user.tenant_id).first()
    if not row:
        raise HTTPException(404, "KPI 配置不存在")
    db.delete(row)
    db.commit()
    return {"id": kid, "deleted": True}


@router.put("/{kid}")
def toggle_kpi(kid: int, enabled: bool,
               user: CurrentUser = Depends(require_permission("rules.create")),
               db: Session = Depends(get_db)):
    row = db.query(KpiConfig).filter(
        KpiConfig.id == kid, KpiConfig.tenant_id == user.tenant_id).first()
    if not row:
        raise HTTPException(404, "KPI 配置不存在")
    row.enabled = enabled
    db.commit()
    return {"id": kid, "enabled": row.enabled}


# ── KPI 映射配置（系统级，超管）──
from ..core.deps import require_superadmin
from ..core.kpi_mapping import get_kpi_mapping, save_kpi_mapping, KPI_CATEGORIES
from pydantic import BaseModel as PydanticBaseModel


class KpiMappingIn(PydanticBaseModel):
    matrix: dict = {}
    by_objective: dict = {}
    fallback_priority: list = []
    poor_fallback_types: list = []
    field_labels: dict = {}


@router.get("/mapping")
def get_mapping(user: CurrentUser = Depends(require_superadmin),
                db: Session = Depends(get_db)):
    """返回当前 KPI 映射配置（超管）。"""
    return get_kpi_mapping(db)


@router.put("/mapping")
def put_mapping(body: KpiMappingIn,
                user: CurrentUser = Depends(require_superadmin),
                db: Session = Depends(get_db)):
    """更新 KPI 映射配置（超管）。"""
    cfg = {"matrix": body.matrix, "by_objective": body.by_objective,
           "fallback_priority": body.fallback_priority,
           "poor_fallback_types": body.poor_fallback_types,
           "field_labels": body.field_labels}
    save_kpi_mapping(db, cfg)
    return {"saved": True}


@router.get("/categories")
def get_categories(user: CurrentUser = Depends(require_permission("ads.read"))):
    """返回 KPI 字段分类（看板筛选/诊断用，非超管也可读）。"""
    return KPI_CATEGORIES
