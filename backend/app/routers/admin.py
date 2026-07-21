"""平台超管路由：CF 域名发现 + 分配给租户（落地页重做 ③，用户决策：平台导入→分配给租户）。

模型：超管在 CF 发现所有域名（平台池）→ 分配给租户（内部团队）→ 租户只能看/用分配给自己的（RLS）。
购买/支付后期再说（v2）。
"""
import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from ..core.database import get_system_db
from ..core.deps import require_superadmin
from ..core.config import settings
from ..core.cf_client import CfClient
from ..core.log_utils import write_log, new_trace_id
from ..models.auth import Tenant
from ..models.landing_lib import LandingDomain

router = APIRouter(prefix="/admin", tags=["admin"])


def _cf() -> CfClient:
    token = os.environ.get("CF_API_TOKEN") or settings.cf_api_token
    acct = os.environ.get("CF_ACCOUNT_ID") or settings.cf_account_id
    if not token or not acct:
        raise HTTPException(500, "CF 未配置（CF_API_TOKEN/CF_ACCOUNT_ID）")
    return CfClient(token, acct)


@router.get("/tenants")
def list_tenants(user=Depends(require_superadmin), db: Session = Depends(get_system_db)):
    """租户列表（分配域名时的下拉用）。"""
    return [{"id": t.id, "name": t.name, "plan": t.plan, "status": t.status}
            for t in db.query(Tenant).order_by(Tenant.id).all()]


@router.get("/domains/discover")
def discover_domains(user=Depends(require_superadmin), db: Session = Depends(get_system_db)):
    """发现 CF 账户所有域名 + 各自已分配给哪些租户（平台池视图）。"""
    zones = _cf().list_zones()
    assigned = db.query(LandingDomain).all()  # super session（BYPASSRLS）跨租户读
    by_domain: dict[str, list] = {}
    for a in assigned:
        by_domain.setdefault(a.domain, []).append(
            {"domain_row_id": a.id, "tenant_id": a.tenant_id, "label": a.label, "source": a.source})
    return [{"domain": z.get("name"), "cf_zone_id": z.get("id"), "cf_status": z.get("status"),
             "assigned_to": by_domain.get(z.get("name"), [])}
            for z in zones if z.get("name")]


class AssignIn(BaseModel):
    domain: str
    tenant_id: int
    label: str = ""


@router.post("/domains/assign")
def assign_domain(body: AssignIn, user=Depends(require_superadmin), db: Session = Depends(get_system_db)):
    """把一个 CF 域名分配给租户（写入租户的域名库，source=discovered）。"""
    t = db.query(Tenant).filter(Tenant.id == body.tenant_id, Tenant.status == "active").first()
    if not t:
        raise HTTPException(404, "租户不存在或已停用")
    domain = body.domain.strip().lower()
    # 域名唯一分配：跨租户查，已分给任何租户都报错（用户决策：被分配对象唯一）
    existing = db.query(LandingDomain).filter(LandingDomain.domain == domain).first()
    if existing:
        t_existing = db.query(Tenant).filter(Tenant.id == existing.tenant_id).first()
        who = t_existing.name if t_existing else f"租户{existing.tenant_id}"
        raise HTTPException(400, f"{domain} 已分配给「{who}」（域名唯一，不可多租户分配）")
    # 校验是 CF 真实 zone（防错填/防跨账户）
    zone_id = _cf().get_zone_id(domain)
    if not zone_id:
        raise HTTPException(400, f"{domain} 不在 CF 账户下（无法分配）")
    row = LandingDomain(tenant_id=body.tenant_id, created_by=user.id, domain=domain,
                        label=body.label or None, source="discovered", cf_zone_status="active")
    db.add(row)
    db.flush()
    tid = new_trace_id()
    write_log(db, tenant_id=body.tenant_id, trace_id=tid, actor_type="user", actor_user_id=user.id,
              target_type="landing_domain", target_id=str(row.id),
              action_type="assign", source="admin", result="success",
              metadata={"domain": domain, "tenant_id": body.tenant_id, "tenant_name": t.name})
    db.commit()
    return {"id": row.id, "trace_id": tid, "domain": domain, "tenant_id": body.tenant_id, "tenant_name": t.name}


@router.delete("/domains/{did}")
def unassign_domain(did: int, user=Depends(require_superadmin), db: Session = Depends(get_system_db)):
    """收回域名分配（仅删 landing_domains 行，不动 CF zone；已发布页保留其 custom_domain）。"""
    row = db.query(LandingDomain).filter(LandingDomain.id == did).first()
    if not row:
        raise HTTPException(404, "分配记录不存在")
    domain, tenant_id = row.domain, row.tenant_id
    db.delete(row)
    tid = new_trace_id()
    write_log(db, tenant_id=tenant_id, trace_id=tid, actor_type="user", actor_user_id=user.id,
              target_type="landing_domain", target_id=str(did),
              action_type="unassign", source="admin", result="success",
              metadata={"domain": domain, "tenant_id": tenant_id})
    db.commit()
    return {"id": did, "unassigned": True, "domain": domain}
