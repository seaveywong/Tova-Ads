"""受众模板库路由：兴趣搜索 + 保存/列/改/删（doc 02 受众，审计项目16）。

v1 仅兴趣受众（search+save+use+edit，无 custom_audiences/lookalikes——v2）。
"""
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from ..core.database import get_db
from ..core.deps import CurrentUser, require_permission, require_owned as _ro
from ..core.encryption import decrypt
from ..core.fb_client import FbClient, FbApiError
from ..core.log_utils import write_log, new_trace_id
from ..models.fb import FbCredential
from ..models.audience import SavedAudience

router = APIRouter(prefix="/audiences", tags=["audiences"])


# ── 兴趣搜索（代理 FB adinterest；受众 1:1 批扩 type：行为/语言）──
@router.get("/search")
def search_interests(q: str, type: str = "interest", limit: int = 20,
                     user: CurrentUser = Depends(require_permission("ads.read")),
                     db: Session = Depends(get_db)):
    """FB 定向词搜索（审计项目16）。type=interest|behavior|locale。
    返 [{id,name,audience_size,path}, ...]，供前端选兴趣/行为 → audience_json。"""
    if not q or len(q) < 1:
        raise HTTPException(400, "查询词 q 不能为空")
    if type not in ("interest", "behavior", "locale"):
        raise HTTPException(400, "type 必须是 interest/behavior/locale")
    from ..core.fb_tokens import first_client
    fb = first_client(db, user.tenant_id)  # 定向搜索 token 无关，任一 active 即可
    if not fb:
        raise HTTPException(400, "未绑定 FB 凭证")
    try:
        if type == "behavior":
            return fb.search_behaviors(q, limit=limit)
        if type == "locale":
            return fb.search_locales(q, limit=limit)
        return fb.search_interests(q, limit=limit)
    except FbApiError as e:
        raise HTTPException(400, f"定向搜索失败：{e.friendly}")


@router.get("/geo-search")
def geo_search(q: str, countries: str = "", limit: int = 20,
               user: CurrentUser = Depends(require_permission("ads.read")),
               db: Session = Depends(get_db)):
    """FB 地理位置搜索（州/城市/邮编，type=adgeolocation）——受众 1:1 批。
    countries=逗号分隔 ISO 码（限定在已选国家内搜，如 US）。返 [{key,name,type,country_code}]。"""
    if not q or len(q) < 2:
        raise HTTPException(400, "查询词至少 2 个字符")
    from ..core.fb_tokens import first_client
    fb = first_client(db, user.tenant_id)
    if not fb:
        raise HTTPException(400, "未绑定 FB 凭证")
    cs = [c.strip().upper() for c in (countries or "").split(",") if c.strip()]
    try:
        return fb.search_geo(q, cs or None, limit=limit)
    except FbApiError as e:
        raise HTTPException(400, f"地理搜索失败：{e.friendly}")


@router.get("/custom-audiences")
def list_custom_audiences(act_id: str,
                          user: CurrentUser = Depends(require_permission("ads.read")),
                          db: Session = Depends(get_db)):
    """账户自定义受众列表（含 Lookalike）——受众 1:1 批。受众 id 是账户级的：
    模板里存名称/示例 id，部署时按名在本账户解析（跨账户同名匹配）。
    RBAC：只允许查询本人可见账户（operator=名下）。"""
    from ..models.fb import Account
    from ..core.deps import scope_account_query
    q = scope_account_query(db.query(Account), user)
    if not q.filter(Account.act_id == act_id).first():
        raise HTTPException(403, "该账户不在你的可见范围")
    from ..core.fb_tokens import client_for_account
    fb = client_for_account(db, user.tenant_id, act_id, "read")
    if not fb:
        raise HTTPException(400, f"账户 {act_id} 无可用读令牌")
    try:
        return fb.custom_audiences(act_id)
    except FbApiError as e:
        raise HTTPException(400, f"读取自定义受众失败：{e.friendly}")


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
    _q = db.query(SavedAudience).filter(SavedAudience.tenant_id == user.tenant_id)
    if user.role == "operator":   # 批AG：operator 只看自己创建的
        _q = _q.filter(SavedAudience.created_by == user.id)
    rows = _q.order_by(SavedAudience.id.desc()).all()
    from ..models.auth import User as _U
    umap = {u.id: u.email for u in db.query(_U).filter(_U.id.in_(
        [a.created_by for a in rows if a.created_by] or [0])).all()}
    return [{**_row_dict(a), "created_by_name": umap.get(a.created_by, "")} for a in rows]


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




