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


