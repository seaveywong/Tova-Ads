"""潜客数据（FB Leadgen / Instant Form leads）。leads_retrieval scope。

GET /leads — 列表（本地 DB，按 page/ad/form 筛选）
POST /leads/sync — 从 FB 拉取（GET /{form_id}/leads → 存本地 + 回填 webhook stub 的 field_data）
POST /leads/subscribe — 订阅该租户所有主页的 leadgen webhook（page-level，需 pages_manage_metadata）
"""
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.orm import Session
from ..core.database import get_db
from ..core.deps import CurrentUser, require_permission
from ..models.lead import Lead
from ..models.lead_form_template import LeadFormTemplate
from ..models.fb import FbCredential
from ..core.fb_client import FbClient, FbApiError
from ..core.encryption import decrypt

router = APIRouter(prefix="/leads", tags=["leads"])


def _parse_created_time(raw):
    """FB created_time 兼容解析（ISO 字符串，GET /leads 返的是 ISO）。→ datetime|None。"""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:
        return None


def _lead_dict(r):
    return {
        "id": r.id, "lead_id": r.lead_id, "page_id": r.page_id, "ad_id": r.ad_id,
        "form_id": r.form_id,
        "field_data": json.loads(r.field_data_json or "[]"),
        "created_time": r.created_time.isoformat() if r.created_time else None,
    }


@router.get("")
def list_leads(
    page_id: str = "", ad_id: str = "", form_id: str = "",
    limit: int = 200,
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """潜客列表（本地 DB，0 FB 调用）。按 page/ad/form 筛选。"""
    q = db.query(Lead).filter(Lead.tenant_id == user.tenant_id)
    if page_id:
        q = q.filter(Lead.page_id == page_id)
    if ad_id:
        q = q.filter(Lead.ad_id == ad_id)
    if form_id:
        q = q.filter(Lead.form_id == form_id)
    total = q.count()  # 真实总数（limit 前），给前端准确显示
    rows = q.order_by(Lead.created_time.desc().nullslast()).limit(min(max(limit, 1), 500)).all()
    return {"items": [_lead_dict(r) for r in rows], "total": total}


@router.get("/export")
def export_leads(
    page_id: str = "", ad_id: str = "", form_id: str = "",
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
    request: Request = None,
):
    """潜客列表 CSV 导出（BOM UTF-8）。筛选条件与列表一致；上限 2000 行。"""
    from ..services.csv_export import build_csv
    from ..core.i18n import req_locale
    en = req_locale(request) == "en"
    q = db.query(Lead).filter(Lead.tenant_id == user.tenant_id)
    if page_id:
        q = q.filter(Lead.page_id == page_id)
    if ad_id:
        q = q.filter(Lead.ad_id == ad_id)
    if form_id:
        q = q.filter(Lead.form_id == form_id)
    rows = q.order_by(Lead.created_time.desc().nullslast()).limit(2000).all()
    headers = (["Time", "Page ID", "Ad ID", "Form ID", "Name", "Contact", "Answers"] if en else
               ["时间", "主页ID", "广告ID", "表单ID", "姓名", "联系方式", "问卷答案"])
    out = []
    for r in rows:
        fd = {}
        try:
            for f in json.loads(r.field_data_json or "[]"):
                name = f.get("name", "")
                vals = f.get("values") or []
                if name == "full_name":
                    fd["name"] = " ".join(vals)
                elif name in ("email", "phone_number"):
                    fd.setdefault("contact", []).append(" ".join(vals))
                else:
                    fd.setdefault("answers", []).append(f"{name}: {' '.join(vals)}")
        except Exception:
            pass
        out.append([
            r.created_time or "", r.page_id or "", r.ad_id or "", r.form_id or "",
            fd.get("name", ""),
            "; ".join(fd.get("contact", [])),
            " | ".join(fd.get("answers", [])),
        ])
    return build_csv("leads", headers, out)


def _get_active_cred(db: Session, tenant_id: int):
    """取租户活跃 FB 凭证（多令牌取首个活跃）。"""
    return db.query(FbCredential).filter(
        FbCredential.tenant_id == tenant_id, FbCredential.status == "active"
    ).first()


def _sync_leads_run(tenant_id: int, forms: list):
    """后台任务：逐表单拉 FB leads → 插新/回填 stub + 通知（dedup_recent 防轮询 spam）。"""
    from ..core.database import SuperSessionLocal
    db = SuperSessionLocal()
    try:
        cred = _get_active_cred(db, tenant_id)
        if not cred:
            return
        fb = FbClient(decrypt(cred.access_token_enc))
        synced, enriched = 0, 0
        for f in forms:
            try:
                leads_data = fb.get_leads(f["form_id"])
            except FbApiError:
                continue
            for ld in leads_data:
                lid = ld.get("id")
                if not lid:
                    continue
                field_data = ld.get("field_data", [])
                existing = db.query(Lead).filter(Lead.lead_id == lid).first()
                if existing:
                    # webhook stub 先存了 → 回填 field_data（+ 补 ad_id/created_time）
                    if field_data and not (existing.field_data_json and existing.field_data_json != "[]"):
                        existing.field_data_json = json.dumps(field_data)
                        if ld.get("ad_id") and not existing.ad_id:
                            existing.ad_id = str(ld["ad_id"])
                        if not existing.created_time:
                            existing.created_time = _parse_created_time(ld.get("created_time"))
                        enriched += 1
                else:
                    db.add(Lead(
                        tenant_id=tenant_id,
                        page_id=f.get("page_id"),
                        ad_id=str(ld.get("ad_id")) if ld.get("ad_id") else None,
                        form_id=f["form_id"],
                        lead_id=lid,
                        field_data_json=json.dumps(field_data),
                        created_time=_parse_created_time(ld.get("created_time")),
                    ))
                    synced += 1
        # 新 lead 到达通知（sync 批次聚合一条，1h dedup 防轮询 spam——landing_health_alert 同款模式）
        if synced > 0:
            from ..core.notify_utils import emit_notification, dedup_recent
            from ..core.log_utils import write_log, new_trace_id
            try:
                if not dedup_recent(db, tenant_id, "leads_new", None, 60):
                    _tid = new_trace_id()
                    write_log(db, tenant_id=tenant_id, trace_id=_tid, actor_type="system",
                              action_type="leads_new", source="leads_sync",
                              target_type="lead", result="success",
                              metadata={"synced": synced, "forms": len(forms)})
                    emit_notification(
                        db, tenant_id=tenant_id, level="info",
                        event_type="leads_new",
                        title=f"新潜客 × {synced}",
                        body=f"Instant Form 同步到 {synced} 条新潜客（{len(forms)} 个表单）。\n"
                             f"到 AdManager → 潜客 查看或导出。",
                        roles=["owner", "operator"], trace_id=_tid,
                    )
            except Exception:
                pass   # 通知失败不阻断同步
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


@router.post("/sync")
def sync_leads(
    form_id: str = "",
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = None,
):
    """从 FB 拉潜客数据（后台任务执行，立即返回）。form_id 空=拉该租户所有已部署的 Instant Form 表单。"""
    forms = []
    if form_id:
        # 归属校验：form_id 必须属于本租户已部署的表单（否则可拉别家表单的潜客进自己租户）
        own = db.query(LeadFormTemplate).filter(
            LeadFormTemplate.tenant_id == user.tenant_id,
            LeadFormTemplate.fb_form_id == form_id,
        ).first()
        if not own:
            raise HTTPException(403, "该表单不属于当前团队")
        forms = [{"form_id": form_id, "page_id": own.fb_page_id}]
    else:
        tpls = db.query(LeadFormTemplate).filter(
            LeadFormTemplate.tenant_id == user.tenant_id,
            LeadFormTemplate.fb_form_id.isnot(None),
        ).all()
        forms = [{"form_id": t.fb_form_id, "page_id": t.fb_page_id} for t in tpls]
    if not forms:
        return {"started": False, "synced": 0, "enriched": 0, "error": "no forms to sync (deploy an Instant Form first)"}
    background_tasks.add_task(_sync_leads_run, user.tenant_id, forms)
    return {"started": True, "forms": len(forms)}


@router.post("/subscribe")
def subscribe_webhook(
    user: CurrentUser = Depends(require_permission("ads.create")),
    db: Session = Depends(get_db),
):
    """订阅该租户所有主页的 leadgen webhook（page-level subscription）。

    遍历 me/accounts（含 access_token），逐页 POST /{page}/subscribed_apps + subscribed_fields=leadgen。
    需 pages_manage_metadata scope。app-level 订阅是一次性手动步骤（FB App Dashboard 配 callback URL）。
    """
    cred = _get_active_cred(db, user.tenant_id)
    if not cred:
        return {"subscribed": 0, "error": "no active FB credential"}
    fb = FbClient(decrypt(cred.access_token_enc))
    try:
        pages = fb.get_paged("me/accounts", {"fields": "id,name,access_token"})
    except FbApiError as e:
        return {"subscribed": 0, "error": e.friendly}
    results = []
    ok = 0
    for p in pages:
        pid, ptoken, pname = p.get("id"), p.get("access_token"), p.get("name")
        if not (pid and ptoken):
            continue
        try:
            fb.subscribe_page_webhook(pid, ptoken, fields=["leadgen"])
            results.append({"page_id": pid, "page_name": pname, "ok": True})
            ok += 1
        except FbApiError as e:
            results.append({"page_id": pid, "page_name": pname, "ok": False, "error": e.friendly})
    return {"subscribed": ok, "total_pages": len(pages), "pages": results}
