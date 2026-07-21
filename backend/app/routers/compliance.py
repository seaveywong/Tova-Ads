"""受监管地区（TW/SG/HK）认证主页 CRUD + regulated payload 构造（doc 02 受监管地区，审计项目4）。

为什么手动 verified_identity_id：FB API 不暴露该数字 ID，但 TW/SG 受监管广告 AdSet
要求 regional_regulation_identities 注入数字身份。用户从 FB BM 后台手抄录入此表。

本路由只做数据层 CRUD + payload 构造 helper；是否注入 build_adset 待 FB 端验证后决定
（见 02_附录_受监管地区.md 待定项 + memo "TW/SG 认证实测结论"）。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from ..core.database import get_db
from ..core.deps import CurrentUser, require_permission
from ..core.log_utils import write_log, new_trace_id
from ..models.compliance import CertifiedPage

router = APIRouter(prefix="/compliance", tags=["compliance"])

# 区域 → FB regulated 字段映射（实测来源：1.0 launch_engine L2536-2566）
# HK 的 FB 字段名 1.0 未实测，标待定——用 region_key 时 HK 需用户确认。
REGION_KEYS: dict[str, dict[str, str]] = {
    "TW": {"category": "TAIWAN_UNIVERSAL",
           "beneficiary_key": "taiwan_universal_beneficiary",
           "payer_key": "taiwan_universal_payer"},
    "SG": {"category": "SINGAPORE_UNIVERSAL",
           "beneficiary_key": "singapore_universal_beneficiary",
           "payer_key": "singapore_universal_payer"},
    # HK: 待定（1.0 未实测 FB 字段名；HONG_KONG_UNIVERSAL 推测，需验证）
}


class CertifiedPageIn(BaseModel):
    region: str  # TW / SG / HK
    page_id: str
    page_name: str = ""
    beneficiary_identity_id: str  # 数字身份 ID（BM 后台手抄）
    payer_identity_id: str = ""  # 空=与 beneficiary 相同
    beneficiary_name: str = ""
    payer_name: str = ""
    note: str = ""


class CertifiedPageUpdate(BaseModel):
    page_name: str | None = None
    beneficiary_identity_id: str | None = None
    payer_identity_id: str | None = None
    beneficiary_name: str | None = None
    payer_name: str | None = None
    status: str | None = None  # active/disabled
    note: str | None = None


def _row_dict(c: CertifiedPage) -> dict:
    return {
        "id": c.id, "region": c.region, "page_id": c.page_id, "page_name": c.page_name,
        "beneficiary_identity_id": c.beneficiary_identity_id,
        "payer_identity_id": c.payer_identity_id,
        "beneficiary_name": c.beneficiary_name, "payer_name": c.payer_name,
        "status": c.status, "note": c.note,
    }


@router.get("/certified-pages")
def list_certified(region: str = "", user: CurrentUser = Depends(require_permission("ads.read")),
                   db: Session = Depends(get_db)):
    rows = db.query(CertifiedPage).filter(CertifiedPage.tenant_id == user.tenant_id)
    if region:
        rows = rows.filter(CertifiedPage.region == region.upper())
    return [_row_dict(c) for c in rows.order_by(CertifiedPage.id.desc()).all()]


@router.post("/certified-pages")
def create_certified(body: CertifiedPageIn, user: CurrentUser = Depends(require_permission("ads.create")),
                     db: Session = Depends(get_db)):
    region = body.region.upper()
    if region not in REGION_KEYS:
        raise HTTPException(400, f"暂不支持地区 {region}（当前支持 TW/SG；HK 待验证）")
    if not body.beneficiary_identity_id.isdigit():
        raise HTTPException(400, "beneficiary_identity_id 必须是数字（FB 拒绝文本名）")
    payer_id = body.payer_identity_id or body.beneficiary_identity_id
    if not payer_id.isdigit():
        raise HTTPException(400, "payer_identity_id 必须是数字")

    # 同租户同 region+page 唯一
    exists = db.query(CertifiedPage).filter(
        CertifiedPage.tenant_id == user.tenant_id,
        CertifiedPage.region == region,
        CertifiedPage.page_id == body.page_id,
    ).first()
    if exists:
        raise HTTPException(400, f"{region} 主页 {body.page_id} 已存在认证记录")

    row = CertifiedPage(
        tenant_id=user.tenant_id, created_by=user.id, region=region,
        page_id=body.page_id, page_name=body.page_name or None,
        beneficiary_identity_id=body.beneficiary_identity_id,
        payer_identity_id=payer_id,
        beneficiary_name=body.beneficiary_name or None,
        payer_name=body.payer_name or None,
        note=body.note or None,
    )
    db.add(row)
    db.flush()
    rid = row.id
    trace_id = new_trace_id()
    write_log(db, tenant_id=user.tenant_id, trace_id=trace_id, actor_type="user",
              actor_user_id=user.id, target_type="certified_page", target_id=str(rid),
              action_type="create", source="user", result="success",
              metadata={"region": region, "page_id": body.page_id})
    db.commit()
    return {"id": rid, "trace_id": trace_id, **_row_dict(row)}


@router.put("/certified-pages/{cid}")
def update_certified(cid: int, body: CertifiedPageUpdate,
                     user: CurrentUser = Depends(require_permission("ads.create")),
                     db: Session = Depends(get_db)):
    row = db.query(CertifiedPage).filter(
        CertifiedPage.id == cid, CertifiedPage.tenant_id == user.tenant_id).first()
    if not row:
        raise HTTPException(404, "认证记录不存在")
    data = body.model_dump(exclude_unset=True)
    if "beneficiary_identity_id" in data and data["beneficiary_identity_id"] is not None:
        if not data["beneficiary_identity_id"].isdigit():
            raise HTTPException(400, "beneficiary_identity_id 必须是数字")
    if "payer_identity_id" in data and data["payer_identity_id"] is not None:
        if not data["payer_identity_id"].isdigit():
            raise HTTPException(400, "payer_identity_id 必须是数字")
    for k, v in data.items():
        setattr(row, k, v)
    trace_id = new_trace_id()
    write_log(db, tenant_id=user.tenant_id, trace_id=trace_id, actor_type="user",
              actor_user_id=user.id, target_type="certified_page", target_id=str(cid),
              action_type="update", source="user", result="success")
    db.commit()
    return {"id": row.id, **_row_dict(row)}


@router.delete("/certified-pages/{cid}")
def delete_certified(cid: int, user: CurrentUser = Depends(require_permission("ads.create")),
                     db: Session = Depends(get_db)):
    row = db.query(CertifiedPage).filter(
        CertifiedPage.id == cid, CertifiedPage.tenant_id == user.tenant_id).first()
    if not row:
        raise HTTPException(404, "认证记录不存在")
    db.delete(row)
    trace_id = new_trace_id()
    write_log(db, tenant_id=user.tenant_id, trace_id=trace_id, actor_type="user",
              actor_user_id=user.id, target_type="certified_page", target_id=str(cid),
              action_type="delete", source="user", result="success",
              metadata={"region": row.region, "page_id": row.page_id})
    db.commit()
    return {"id": cid, "deleted": True}


# ── regulated payload 构造 helper（供 build_adset 验证后接入）──
def build_regulated_payload(certified: CertifiedPage) -> dict:
    """从 certified_pages 行构造 AdSet 的受监管地区字段（审计项目4）。

    返回：
      {
        "regional_regulated_categories": ["TAIWAN_UNIVERSAL"],
        "regional_regulation_identities": {
            "taiwan_universal_beneficiary": <数字>,
            "taiwan_universal_payer": <数字>,
        }
      }

    ⚠️ FB 端字段注入尚未验证通过（见 memo "TW/SG 认证实测结论"）。
    本 helper 已就绪，待验证后接入 ad_builder.build_adset。
    """
    keys = REGION_KEYS.get(certified.region)
    if not keys:
        raise ValueError(f"未支持的 region: {certified.region}")
    identities = {keys["beneficiary_key"]: certified.beneficiary_identity_id}
    if certified.payer_identity_id:
        identities[keys["payer_key"]] = certified.payer_identity_id
    return {
        "regional_regulated_categories": [keys["category"]],
        "regional_regulation_identities": identities,
    }
