"""受众模板库路由：兴趣搜索 + 保存/列/改/删（doc 02 受众，审计项目16）。

v1 仅兴趣受众（search+save+use+edit，无 custom_audiences/lookalikes——v2）。
"""
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from ..core.database import get_db
from ..core.deps import CurrentUser, require_permission
from ..core.encryption import decrypt
from ..core.fb_client import FbClient, FbApiError
from ..core.log_utils import write_log, new_trace_id
from ..models.fb import FbCredential
from ..models.audience import SavedAudience

router = APIRouter(prefix="/audiences", tags=["audiences"])


# ── 兴趣搜索（代理 FB adinterest）──
@router.get("/search")
def search_interests(q: str, limit: int = 20,
                     user: CurrentUser = Depends(require_permission("ads.read")),
                     db: Session = Depends(get_db)):
    """FB 兴趣词搜索（审计项目16）。返 [{id,name,audience_size,path}, ...]。"""
    if not q or len(q) < 1:
        raise HTTPException(400, "查询词 q 不能为空")
    from ..core.fb_tokens import first_client
    fb = first_client(db, user.tenant_id)  # 兴趣搜索 token 无关，任一 active 即可
    if not fb:
        raise HTTPException(400, "未绑定 FB 凭证")
    try:
        return fb.search_interests(q, limit=limit)
    except FbApiError as e:
        raise HTTPException(400, f"兴趣搜索失败：{e.friendly}")


# ── 受众模板 CRUD ──
class AudienceIn(BaseModel):
    name: str
    interests: list[dict] = []  # [{id,name}, ...]
    countries: list[str] = ["US"]
    age_min: int = 18
    age_max: int = 65
    gender: int = 0  # 0=all 1=male 2=female
    strategy: str = "broad_interest"  # broad_interest/broad_only/interest_only
    note: str = ""


class AudienceUpdate(BaseModel):
    name: str | None = None
    interests: list[dict] | None = None
    countries: list[str] | None = None
    age_min: int | None = None
    age_max: int | None = None
    gender: int | None = None
    strategy: str | None = None
    note: str | None = None
    status: str | None = None


def _row_dict(a: SavedAudience) -> dict:
    return {
        "id": a.id, "name": a.name,
        "interests": json.loads(a.interests_json or "[]"),
        "countries": json.loads(a.countries or "[]"),
        "age_min": a.age_min, "age_max": a.age_max, "gender": a.gender,
        "strategy": a.strategy, "status": a.status, "note": a.note,
    }


@router.get("")
def list_audiences(user: CurrentUser = Depends(require_permission("ads.read")),
                   db: Session = Depends(get_db)):
    rows = db.query(SavedAudience).filter(
        SavedAudience.tenant_id == user.tenant_id).order_by(SavedAudience.id.desc()).all()
    return [_row_dict(a) for a in rows]


@router.post("")
def create_audience(body: AudienceIn, user: CurrentUser = Depends(require_permission("ads.create")),
                    db: Session = Depends(get_db)):
    if body.strategy not in ("broad_interest", "broad_only", "interest_only"):
        raise HTTPException(400, "strategy 必须是 broad_interest/broad_only/interest_only")
    if not (18 <= body.age_min <= 65) or not (18 <= body.age_max <= 65) or body.age_min > body.age_max:
        raise HTTPException(400, "age_min/age_max 范围无效（18-65，min<=max）")
    if body.gender not in (0, 1, 2):
        raise HTTPException(400, "gender 必须是 0/1/2")
    row = SavedAudience(
        tenant_id=user.tenant_id, created_by=user.id, name=body.name,
        interests_json=json.dumps(body.interests),
        countries=json.dumps(body.countries),
        age_min=body.age_min, age_max=body.age_max, gender=body.gender,
        strategy=body.strategy, note=body.note or None,
    )
    db.add(row)
    db.flush()
    rid = row.id
    trace_id = new_trace_id()
    write_log(db, tenant_id=user.tenant_id, trace_id=trace_id, actor_type="user",
              actor_user_id=user.id, target_type="audience", target_id=str(rid),
              action_type="create", source="user", result="success",
              metadata={"strategy": body.strategy, "interests": len(body.interests)})
    db.commit()
    return {"id": rid, "trace_id": trace_id, **_row_dict(row)}


@router.put("/{aid}")
def update_audience(aid: int, body: AudienceUpdate,
                    user: CurrentUser = Depends(require_permission("ads.create")),
                    db: Session = Depends(get_db)):
    row = db.query(SavedAudience).filter(
        SavedAudience.id == aid, SavedAudience.tenant_id == user.tenant_id).first()
    if not row:
        raise HTTPException(404, "受众模板不存在")
    data = body.model_dump(exclude_unset=True)
    if "strategy" in data and data["strategy"] not in ("broad_interest", "broad_only", "interest_only"):
        raise HTTPException(400, "strategy 无效")
    for k, v in data.items():
        if k == "interests":
            row.interests_json = json.dumps(v)
        elif k == "countries":
            row.countries = json.dumps(v)
        else:
            setattr(row, k, v)
    trace_id = new_trace_id()
    write_log(db, tenant_id=user.tenant_id, trace_id=trace_id, actor_type="user",
              actor_user_id=user.id, target_type="audience", target_id=str(aid),
              action_type="update", source="user", result="success")
    db.commit()
    return {"id": row.id, **_row_dict(row)}


@router.delete("/{aid}")
def delete_audience(aid: int, user: CurrentUser = Depends(require_permission("ads.create")),
                    db: Session = Depends(get_db)):
    row = db.query(SavedAudience).filter(
        SavedAudience.id == aid, SavedAudience.tenant_id == user.tenant_id).first()
    if not row:
        raise HTTPException(404, "受众模板不存在")
    db.delete(row)
    trace_id = new_trace_id()
    write_log(db, tenant_id=user.tenant_id, trace_id=trace_id, actor_type="user",
              actor_user_id=user.id, target_type="audience", target_id=str(aid),
              action_type="delete", source="user", result="success")
    db.commit()
    return {"id": aid, "deleted": True}
