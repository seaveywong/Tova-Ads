"""潜客数据（FB Leadgen / Instant Form leads）。leads_retrieval scope。

GET /leads — 列表（本地 DB，按 page/ad/form/status 筛选）
GET /leads/export — CSV 导出（含跟进状态/备注）
POST /leads/sync — 从 FB 拉取（GET /{form_id}/leads → 存本地 + 回填 webhook stub 的 field_data）
POST /leads/subscribe — 订阅该租户所有主页的 leadgen webhook（page-level，需 pages_manage_metadata）
PATCH /leads/{id} — 轻 CRM：标记跟进状态（new/contacted/won/lost）/ 备注（本地状态，不回写 FB）
"""
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..core.database import get_db
from ..core.deps import CurrentUser, require_permission
from ..models.lead import Lead
from ..models.lead_form_template import LeadFormTemplate
from ..models.fb import FbCredential
from ..core.fb_client import FbClient, FbApiError
from ..core.encryption import decrypt

router = APIRouter(prefix="/leads", tags=["leads"])

LEAD_STATUSES = ("new", "contacted", "won", "lost")
LEAD_STATUS_LABELS = {   # CSV 导出列头用（按请求 locale 选）
    "zh": {"new": "新潜客", "contacted": "已联系", "won": "已成交", "lost": "已流失"},
    "en": {"new": "New", "contacted": "Contacted", "won": "Won", "lost": "Lost"},
}


class LeadUpdateIn(BaseModel):
    status: str | None = None
    note: str | None = None


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
        "status": r.status or "new",
        "note": r.note,
        "status_updated_at": r.status_updated_at.isoformat() if r.status_updated_at else None,
    }


@router.get("")
def list_leads(
    page_id: str = "", ad_id: str = "", form_id: str = "", status: str = "",
    limit: int = 200,
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """潜客列表（本地 DB，0 FB 调用）。按 page/ad/form/status 筛选。"""
    q = db.query(Lead).filter(Lead.tenant_id == user.tenant_id)
    if page_id:
        q = q.filter(Lead.page_id == page_id)
    if ad_id:
        q = q.filter(Lead.ad_id == ad_id)
    if form_id:
        q = q.filter(Lead.form_id == form_id)
    if status:
        if status not in LEAD_STATUSES:
            raise HTTPException(400, f"无效状态 {status}")
        q = q.filter(Lead.status == status)
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
    headers = (["Time", "Page ID", "Ad ID", "Form ID", "Name", "Contact", "Status", "Note", "Answers"] if en else
               ["时间", "主页ID", "广告ID", "表单ID", "姓名", "联系方式", "跟进状态", "备注", "问卷答案"])
    st_labels = LEAD_STATUS_LABELS["en" if en else "zh"]
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
            st_labels.get(r.status or "new", r.status or "new"),
            r.note or "",
            " | ".join(fd.get("answers", [])),
        ])
    return build_csv("leads", headers, out)


@router.patch("/{lead_id}")
def update_lead(
    lead_id: int,
    body: LeadUpdateIn,
    user: CurrentUser = Depends(require_permission("ads.create")),
    db: Session = Depends(get_db),
):
    """轻 CRM：标记潜客跟进状态 / 写跟进备注（本地状态，不回写 FB）。
    只更新显式传入的字段；status 枚举校验；status_updated_at 记录最近一次跟进改动。"""
    from ..core.log_utils import write_log, new_trace_id
    lead = db.query(Lead).filter(
        Lead.id == lead_id, Lead.tenant_id == user.tenant_id
    ).first()
    if not lead:
        raise HTTPException(404, "潜客不存在")
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(400, "无要更新的字段")
    if "status" in data and data["status"] is not None and data["status"] not in LEAD_STATUSES:
        raise HTTPException(400, f"无效状态 {data['status']}")
    if data.get("note") and len(data["note"]) > 2000:
        raise HTTPException(400, "备注过长（≤2000 字符）")
    for k, v in data.items():
        setattr(lead, k, v)
    lead.status_updated_at = datetime.now(timezone.utc)
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(),
              actor_type="user", actor_user_id=user.id,
              target_type="lead", target_id=lead.lead_id,
              action_type="update", source="user", result="success",
              metadata={"fields": sorted(data.keys()), "status": lead.status})
    db.commit()
    return _lead_dict(lead)


@router.get("/pages")
def pages_status(
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """主页受控视图：遍历活跃令牌 me/accounts，逐页给权限面（能否管理/能否投广告）+
    当前 webhook 订阅实况（GET /{page}/subscribed_apps 比对 App id）。

    回答「哪些主页真的受控」：页权限是 FB 侧该号被分配的角色（OAuth 只能复制不能放大），
    订阅需要「管理主页」任务。手动触发（前端打开面板时拉），每页 1 次订阅查询。
    """
    clients = _tenant_fb_clients(db, user.tenant_id)
    if not clients:
        return {"pages": [], "error": "no active FB credential"}
    # 我方 App id 集（订阅列表按 app 匹配；无 App 配置时退化为「有任意订阅即算」）
    _app_ids = set()
    try:
        from ..models.fb_app import FbApp
        _app_ids = {str(a.app_id) for a in db.query(FbApp).all() if a.app_id}
    except Exception:
        pass
    by_page: dict = {}
    for fb, alias in clients:
        try:
            pages = fb.get_paged("me/accounts",
                                 {"fields": "id,name,access_token,permitted_tasks"})
        except FbApiError:
            continue
        for p in pages:
            pid, ptoken, pname = p.get("id"), p.get("access_token"), p.get("name")
            if not (pid and ptoken):
                continue
            tasks = [str(t).upper() for t in (p.get("permitted_tasks") or [])]
            if pid in by_page:
                continue   # 多令牌同页：保留首个（权限面以能拿到的为准）
            row = {"page_id": pid, "page_name": pname, "alias": alias,
                   "can_manage": any(t in ("MANAGE", "ADMINISTER", "MANAGE_PAGES",
                                           "MANAGE_JOBS") for t in tasks),
                   "can_advertise": "ADVERTISE" in tasks,
                   "tasks": [t for t in tasks if t not in ("ANALYZE",)][:6],
                   "subscribed": None}
            try:
                subs = FbClient(ptoken).get(f"{pid}/subscribed_apps", {"fields": "id"})
                items = (subs.get("data") or []) if isinstance(subs, dict) else []
                if _app_ids:
                    row["subscribed"] = any(str(x.get("id")) in _app_ids for x in items)
                else:
                    row["subscribed"] = bool(items)
            except FbApiError:
                pass   # 查询失败保持 None（未知，前端显示 —）
            by_page[pid] = row
    pages = sorted(by_page.values(), key=lambda r: (not r["can_manage"], r["page_name"]))
    return {"pages": pages, "subscribed_count": sum(1 for r in pages if r["subscribed"])}


def _tenant_fb_clients(db: Session, tenant_id: int) -> list:
    """租户全部活跃令牌的 FbClient 列表 [(client, alias)]。
    潜客链路（订阅/拉取）按页/表单走的是用户级权限（页管理/leads_retrieval），不同令牌权限面
    不同——单取首个 active 曾令订阅全灭（首个是操作员令牌，无 pages_manage_metadata）。"""
    out = []
    for c in db.query(FbCredential).filter(
        FbCredential.tenant_id == tenant_id, FbCredential.status == "active"
    ).all():
        try:
            out.append((FbClient(decrypt(c.access_token_enc)), c.alias or f"#{c.id}"))
        except Exception:
            continue
    return out


def _sync_leads_run(tenant_id: int, forms: list):
    """后台任务：逐表单拉 FB leads → 插新/回填 stub + 通知（dedup_recent 防轮询 spam）。"""
    import logging
    _log = logging.getLogger("toveads.leads")
    from ..core.database import SuperSessionLocal
    db = SuperSessionLocal()
    try:
        clients = _tenant_fb_clients(db, tenant_id)
        if not clients:
            _log.warning("[LeadsSync] tenant=%s 无活跃令牌，后台同步跳过", tenant_id)
            return
        synced, enriched = 0, 0
        fb_errors = []
        for f in forms:
            # 多令牌容灾：不同令牌权限面不同（leads_retrieval 按授权用户），单令牌权限不足/
            # 失效时换下一个重试；全部失败才记错（记最后一个的报错原文）
            leads_data = None
            last_err = None
            for fb, _alias in clients:
                try:
                    leads_data = fb.get_leads(f["form_id"])
                    break
                except FbApiError as e:
                    last_err = e
            if leads_data is None:
                # 异步化后无同步响应可带错误——必须记日志（否则失败完全静默）
                _log.warning("[LeadsSync] form=%s 拉取失败(已试 %d 个令牌): %s",
                             f["form_id"], len(clients), getattr(last_err, "friendly", last_err))
                fb_errors.append({"form_id": f["form_id"],
                                  "error": str(getattr(last_err, "friendly", last_err))})
                continue
            for ld in leads_data:
                lid = ld.get("id")
                if not lid:
                    continue
                field_data = ld.get("field_data", [])
                existing = db.query(Lead).filter(
                    Lead.lead_id == lid, Lead.tenant_id == tenant_id).first()
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
                        roles=["owner", "operator"], trace_id=_tid, platform="fb")
            except Exception:
                pass   # 通知失败不阻断同步
        # 全部表单都拉失败（如 token 失效）→ warning 通知（否则异步化后用户完全无感知）
        if fb_errors and synced == 0 and len(fb_errors) == len(forms):
            from ..core.notify_utils import emit_notification, dedup_recent
            from ..core.log_utils import write_log, new_trace_id
            try:
                if not dedup_recent(db, tenant_id, "leads_sync_failed", None, 360):
                    _tid = new_trace_id()
                    write_log(db, tenant_id=tenant_id, trace_id=_tid, actor_type="system",
                              action_type="leads_sync_failed", source="leads_sync",
                              target_type="lead", result="fail",
                              metadata={"errors": str(fb_errors)[:200]})
                    emit_notification(
                        db, tenant_id=tenant_id, level="warning",
                        event_type="leads_sync_failed",
                        title="潜客同步失败",
                        body="全部表单拉取失败（常见原因：令牌失效/权限不足）。\n"
                             f"错误：{fb_errors[0]['error'][:120]}",
                        roles=["owner", "operator"], trace_id=_tid, platform="fb")
            except Exception:
                pass
        db.commit()
    except Exception:
        db.rollback()
        _log.exception("[LeadsSync] tenant=%s 后台同步异常", tenant_id)
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


class SubscribeIn(BaseModel):
    page_ids: list[str] = []   # 空=全部主页（兼容旧行为）；非空=只订阅指定页


@router.post("/subscribe")
def subscribe_webhook(
    body: SubscribeIn | None = None,
    user: CurrentUser = Depends(require_permission("ads.create")),
    db: Session = Depends(get_db),
):
    """订阅主页 leadgen webhook（page-level subscription，可指定页）。

    遍历全部活跃令牌的 me/accounts（含 access_token），逐页 POST /{page}/subscribed_apps +
    subscribed_fields=leadgen；同页任一令牌订阅成功即成（不同令牌权限面不同——曾单取首个
    active，令牌池轮换到操作员令牌时 13 页全灭 0/13，操作员无 pages_manage_metadata）。
    body.page_ids 非空时只订阅指定页（受控面板勾选）。需要 pages_manage_metadata scope；
    app-level 订阅是一次性手动步骤（FB App Dashboard 配 callback URL）。
    """
    only = set((body.page_ids if body else None) or [])
    clients = _tenant_fb_clients(db, user.tenant_id)
    if not clients:
        return {"subscribed": 0, "error": "no active FB credential"}
    by_page: dict = {}   # page_id -> 结果行（多令牌去重：成功后不再试）
    total_pages = 0
    for fb, alias in clients:
        try:
            pages = fb.get_paged("me/accounts", {"fields": "id,name,access_token"})
        except FbApiError:
            continue   # 该令牌拉不到页清单（无 pages_show_list/失效）→ 换下一个令牌
        wanted = [p for p in pages if not only or p.get("id") in only]
        total_pages = max(total_pages, len(wanted))
        for p in wanted:
            pid, ptoken, pname = p.get("id"), p.get("access_token"), p.get("name")
            if not (pid and ptoken):
                continue
            row = by_page.setdefault(pid, {"page_id": pid, "page_name": pname, "ok": False,
                                           "error": ""})
            if row["ok"]:
                continue
            try:
                fb.subscribe_page_webhook(pid, ptoken, fields=["leadgen"])
                row.update(ok=True, error="")
            except FbApiError as e:
                row["error"] = e.friendly   # 保留最新失败原因；后续令牌成功会覆盖
    # 指定了页清单时 total_pages 按清单口径（wanted 可能空=页不属于任何令牌）
    if only:
        total_pages = len(by_page) or len(only)
    results = list(by_page.values())
    ok = sum(1 for r in results if r["ok"])
    return {"subscribed": ok, "total_pages": total_pages or len(results), "pages": results}


@router.post("/unsubscribe")
def unsubscribe_webhook(
    user: CurrentUser = Depends(require_permission("ads.create")),
    db: Session = Depends(get_db),
):
    """手动退订该租户所有主页的 webhook（多令牌遍历同 subscribe）。

    DELETE /{page}/subscribed_apps 是 page×App 级整体退订（FB 无按 field 退订，leadgen/feed
    等一并停）。仅手动触发——删令牌/移除账户不自动退订（webhook 入库按 page→租户映射，
    还在推就能收到潜客；退订=显式放弃接收）。
    """
    clients = _tenant_fb_clients(db, user.tenant_id)
    if not clients:
        return {"unsubscribed": 0, "error": "no active FB credential"}
    by_page: dict = {}
    for fb, alias in clients:
        try:
            pages = fb.get_paged("me/accounts", {"fields": "id,name,access_token"})
        except FbApiError:
            continue
        for p in pages:
            pid, ptoken, pname = p.get("id"), p.get("access_token"), p.get("name")
            if not (pid and ptoken):
                continue
            row = by_page.setdefault(pid, {"page_id": pid, "page_name": pname, "ok": False,
                                           "error": ""})
            if row["ok"]:
                continue
            try:
                fb.unsubscribe_page_webhook(pid, ptoken)
                row.update(ok=True, error="")
            except FbApiError as e:
                row["error"] = e.friendly
    results = list(by_page.values())
    ok = sum(1 for r in results if r["ok"])
    return {"unsubscribed": ok, "total_pages": len(results), "pages": results}
