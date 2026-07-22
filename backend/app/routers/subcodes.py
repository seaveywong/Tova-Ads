"""子码路由：生成 /a/{slug} 短链 + 列表。

子码是铺广告的核心：提交时预留（reserved）→ 广告上线首次点击 → 绑 ad_id（active）。
"""
import string
import secrets
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from ..core.database import get_db
from ..core.deps import CurrentUser, require_permission
from ..models.launch import LandingAdLink
from ..schemas.launch import GenerateSubcodeIn, SubcodeOut

router = APIRouter(prefix="/subcodes", tags=["subcodes"])

_CHARS = string.ascii_lowercase + string.digits  # a-z0-9


def _gen_slug(db: Session, tries: int = 10) -> str:
    for _ in range(tries):
        slug = "".join(secrets.choice(_CHARS) for _ in range(6))
        if not db.query(LandingAdLink).filter(LandingAdLink.slug == slug).first():
            return slug
    raise RuntimeError("slug 碰撞过多，请重试")


@router.post("/generate", response_model=SubcodeOut)
def generate(
    body: GenerateSubcodeIn,
    user: CurrentUser = Depends(require_permission("ads.create")),
    db: Session = Depends(get_db),
):
    """生成子码（reserved）→ 后续铺广告时创意链接用此 /a/{slug}。"""
    slug = _gen_slug(db)
    link = LandingAdLink(
        tenant_id=user.tenant_id,
        slug=slug,
        act_id=body.act_id,
        page_id=body.page_id,
        status="reserved",
    )
    db.add(link)
    db.flush()
    # 写日志（总则3：每个写操作记 action_logs + trace_id）
    from ..core.log_utils import write_log, new_trace_id
    trace_id = new_trace_id()
    write_log(db, tenant_id=user.tenant_id, trace_id=trace_id,
              actor_type="user", actor_user_id=user.id,
              target_type="subcode", target_id=slug,
              action_type="create", source="user", result="success")
    result = SubcodeOut(
        id=link.id, slug=slug, url=f"/a/{slug}",
        act_id=link.act_id, status=link.status, ad_id=link.ad_id,
    )
    db.commit()  # 持久化（事务结束，SET LOCAL 清除——没关系，响应已构建）
    return result


@router.get("")
def list_subcodes(
    page_id: int | None = None,
    status: str = "all",      # all(=reserved+active) / unbound / active / archived / deleted / trash
    q: str = "",
    sort: str = "created",    # created / visits
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """列本租户子码：状态分页 + 搜索(slug/ad_id) + 排序 + 计数。"""
    from ..models.landing_event import LandingEvent
    from sqlalchemy import func, or_
    base = db.query(LandingAdLink).filter(LandingAdLink.tenant_id == user.tenant_id)
    if page_id is not None:
        base = base.filter(LandingAdLink.page_id == page_id)
    # 状态筛选
    if status == "unbound":
        base = base.filter(LandingAdLink.status == "reserved", LandingAdLink.ad_id.is_(None))
    elif status == "active":
        base = base.filter(LandingAdLink.status == "active")
    elif status == "archived":
        base = base.filter(LandingAdLink.status == "archived")
    elif status == "deleted":
        base = base.filter(LandingAdLink.status == "deleted")
    elif status == "trash":
        base = base.filter(LandingAdLink.status.in_(["archived", "deleted"]))
    else:  # all = 在用(reserved+active)，不含归档/硬删
        base = base.filter(LandingAdLink.status.in_(["reserved", "active"]))
    # 搜索
    if q:
        like = f"%{q}%"
        base = base.filter(or_(LandingAdLink.slug.ilike(like), LandingAdLink.ad_id.ilike(like)))
    links = base.order_by(LandingAdLink.id.desc()).all()
    # 批量统计每子码 visit/click（避免 N+1）
    stats = {}
    ad_counts: dict = {}
    slugs = [l.slug for l in links]
    if slugs:
        rows = db.query(LandingEvent.slug, LandingEvent.event_type, func.count()).filter(
            LandingEvent.slug.in_(slugs)
        ).group_by(LandingEvent.slug, LandingEvent.event_type).all()
        for slug, etype, cnt in rows:
            d = stats.setdefault(slug, {"visit": 0, "click": 0})
            if etype == "visit":
                d["visit"] = cnt
            elif etype in ("click", "submit"):
                d["click"] += cnt
        # 该子码被多少个不同广告用过（多广告复用一个子码时，归因靠 ?ad= 区分；这里聚合去重 ad_id）
        ad_counts = dict(db.query(LandingEvent.slug, func.count(LandingEvent.ad_id.distinct())).filter(
            LandingEvent.slug.in_(slugs),
            LandingEvent.ad_id.isnot(None), LandingEvent.ad_id != "",
        ).group_by(LandingEvent.slug).all())
        # 跨多少个不同账户（多账户复用看这个；?act= 透传后准）
        act_counts = dict(db.query(LandingEvent.slug, func.count(LandingEvent.act_id.distinct())).filter(
            LandingEvent.slug.in_(slugs),
            LandingEvent.act_id.isnot(None), LandingEvent.act_id != "",
        ).group_by(LandingEvent.slug).all())
    items = [{"id": l.id, "slug": l.slug, "url": f"/a/{l.slug}", "page_id": l.page_id,
              "act_id": l.act_id, "ad_id": l.ad_id, "status": l.status,
              "ad_count": ad_counts.get(l.slug, 0),
              "act_count": act_counts.get(l.slug, 0),
              "archived_at": l.archived_at.isoformat() if l.archived_at else "",
              "visit_count": stats.get(l.slug, {}).get("visit", 0),
              "click_count": stats.get(l.slug, {}).get("click", 0)} for l in links]
    if sort == "visits":
        items.sort(key=lambda x: x["visit_count"], reverse=True)
    # 状态计数（不受 status 筛选影响，供 tab 徽标）
    cnt_q = db.query(LandingAdLink.status, func.count()).filter(
        LandingAdLink.tenant_id == user.tenant_id)
    if page_id is not None:
        cnt_q = cnt_q.filter(LandingAdLink.page_id == page_id)
    raw = dict(cnt_q.group_by(LandingAdLink.status).all())
    unbound_cnt = db.query(func.count(LandingAdLink.id)).filter(
        LandingAdLink.tenant_id == user.tenant_id,
        LandingAdLink.status == "reserved", LandingAdLink.ad_id.is_(None)
    ).scalar() or 0
    if page_id is not None:
        unbound_cnt = db.query(func.count(LandingAdLink.id)).filter(
            LandingAdLink.tenant_id == user.tenant_id, LandingAdLink.page_id == page_id,
            LandingAdLink.status == "reserved", LandingAdLink.ad_id.is_(None)
        ).scalar() or 0
    counts = {
        "all": (raw.get("reserved", 0) + raw.get("active", 0)),
        "unbound": unbound_cnt,
        "active": raw.get("active", 0),
        "archived": raw.get("archived", 0),
        "deleted": raw.get("deleted", 0),
    }
    return {"items": items, "counts": counts}


@router.get("/{page_id}/events")
def subcode_events(
    page_id: int,
    slug: str = "",
    limit: int = 200,
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """子码访问日志（landing_events per page/slug，前端弹窗展示）。"""
    from ..models.landing_event import LandingEvent
    q = db.query(LandingEvent).filter(
        LandingEvent.page_id == page_id, LandingEvent.tenant_id == user.tenant_id)
    if slug:
        q = q.filter(LandingEvent.slug == slug)
    evs = q.order_by(LandingEvent.id.desc()).limit(min(limit, 500)).all()
    return [{"id": e.id, "event_type": e.event_type, "slug": e.slug, "ad_id": e.ad_id,
             "country": e.country, "city": e.city, "decision": e.decision, "reason": e.reason,
             "user_agent": (e.user_agent or "")[:80], "referrer": e.referrer,
             "created_at": str(e.created_at or "")} for e in evs]


class SubcodeUpdateIn(BaseModel):
    ad_id: str | None = None
    act_id: str | None = None
    target_urls: str | None = None
    status: str | None = None


@router.put("/{sid}")
def update_subcode(
    sid: int,
    body: SubcodeUpdateIn,
    user: CurrentUser = Depends(require_permission("ads.create")),
    db: Session = Depends(get_db),
):
    """改子码（绑/解广告、改专属 target_urls、状态流转）。"""
    from ..core.log_utils import write_log, new_trace_id
    link = db.query(LandingAdLink).filter(
        LandingAdLink.id == sid, LandingAdLink.tenant_id == user.tenant_id
    ).first()
    if not link:
        raise HTTPException(404, "子码不存在")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(link, k, v)
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(),
              actor_type="user", actor_user_id=user.id,
              target_type="subcode", target_id=link.slug,
              action_type="update", source="user", result="success")
    db.commit()
    return {"id": link.id, "slug": link.slug, "ad_id": link.ad_id,
            "act_id": link.act_id, "status": link.status}


@router.delete("/{sid}")
def delete_subcode(
    sid: int,
    hard: int = 0,   # 0=软删(archived,保留配置可恢复) 1=硬删(deleted,清自身配置,恢复后回退页级跳转)
    user: CurrentUser = Depends(require_permission("ads.create")),
    db: Session = Depends(get_db),
):
    """删子码：软删 status=archived（保留配置）；硬删 status=deleted（清 target_urls/ad_id/act_id）。
    两者都保留行可恢复（恢复端点 /{sid}/restore）。"""
    from ..core.log_utils import write_log, new_trace_id
    link = db.query(LandingAdLink).filter(
        LandingAdLink.id == sid, LandingAdLink.tenant_id == user.tenant_id
    ).first()
    if not link:
        raise HTTPException(404, "子码不存在")
    now = datetime.now(timezone.utc)
    if hard:
        link.status = "deleted"
        link.target_urls = None
        link.ad_id = None
        link.act_id = None
        link.archived_at = link.archived_at or now
        act = "hard_delete"
    else:
        link.status = "archived"
        link.archived_at = now
        act = "archive"
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(),
              actor_type="user", actor_user_id=user.id,
              target_type="subcode", target_id=link.slug,
              action_type=act, source="user", result="success")
    db.commit()
    return {"id": sid, "status": link.status}


@router.post("/{sid}/restore")
def restore_subcode(
    sid: int,
    user: CurrentUser = Depends(require_permission("ads.create")),
    db: Session = Depends(get_db),
):
    """恢复子码：archived/deleted → reserved（deleted 的自身配置已清，恢复后走页级跳转/像素）。"""
    from ..core.log_utils import write_log, new_trace_id
    link = db.query(LandingAdLink).filter(
        LandingAdLink.id == sid, LandingAdLink.tenant_id == user.tenant_id
    ).first()
    if not link:
        raise HTTPException(404, "子码不存在")
    if link.status not in ("archived", "deleted"):
        raise HTTPException(400, "仅归档/硬删的子码可恢复")
    link.status = "reserved"
    link.archived_at = None
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(),
              actor_type="user", actor_user_id=user.id,
              target_type="subcode", target_id=link.slug,
              action_type="restore", source="user", result="success")
    db.commit()
    return {"id": sid, "status": "reserved"}


class FbCheckIn(BaseModel):
    page_id: int
    slug: str = ""


def _resolve_page_base(db, tenant_id, page_id):
    """取落地页的公网 base URL（复用 _run_self_check 的解析逻辑）。"""
    import json as _j
    from ..models.launch import LandingPage
    p = db.query(LandingPage).filter(
        LandingPage.id == page_id, LandingPage.tenant_id == tenant_id).first()
    if not p:
        return None, None
    base = ""
    if p.custom_domain:
        base = p.custom_domain if p.custom_domain.startswith("http") else f"https://{p.custom_domain}"
    elif p.custom_domains:
        try:
            ds = _j.loads(p.custom_domains)
            if ds:
                base = ds[0] if ds[0].startswith("http") else f"https://{ds[0]}"
        except Exception:
            pass
    if not base:
        base = f"https://tovaads-landing-{p.id}.pages.dev"
    return base, p


@router.post("/fb-check")
def fb_check_subcode(
    body: FbCheckIn,
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """检测单个子码 URL 在 FB 是否被封（Graph API scrape 完整 URL /a/{slug}）。

    返回 {status: pass/warn/fail, detail, url}。
    """
    from .landing import _fb_ban_probe
    base, p = _resolve_page_base(db, user.tenant_id, body.page_id)
    if not p:
        raise HTTPException(404, "落地页不存在")
    url = f"{base.rstrip('/')}/a/{body.slug}"
    status, detail = _fb_ban_probe(db, user.tenant_id, url)
    return {"status": status, "detail": detail, "url": url}


@router.post("/fb-check-batch")
def fb_check_batch(
    body: FbCheckIn,
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """批量检测页下所有 active 子码在 FB 是否被封。

    返回 [{slug, status, detail, url}, ...]。
    """
    from .landing import _fb_ban_probe
    base, p = _resolve_page_base(db, user.tenant_id, body.page_id)
    if not p:
        raise HTTPException(404, "落地页不存在")
    links = db.query(LandingAdLink).filter(
        LandingAdLink.page_id == body.page_id,
        LandingAdLink.tenant_id == user.tenant_id,
        LandingAdLink.status == "active",
    ).all()
    results = []
    for link in links:
        url = f"{base.rstrip('/')}/a/{link.slug}"
        status, detail = _fb_ban_probe(db, user.tenant_id, url)
        results.append({"slug": link.slug, "status": status, "detail": detail, "url": url})
    blocked = [r for r in results if r["status"] == "fail"]
    return {"total": len(results), "blocked": len(blocked), "results": results}
              action_type="restore", source="user", result="success")
    db.commit()
    return {"id": sid, "status": "reserved"}
