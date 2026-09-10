"""像素库 + 域名库 CRUD（落地页重做，决策 2/6）。

按租户隔离（RLS + tenant_id）。每条带 usage_count + used_by（决策⑥双向闭环）：
- 像素用量 = landing_pages WHERE pixel_id = 此像素（多像素迁移后改 JSON contains）
- 域名用量 = landing_pages WHERE custom_domain = 此域名
删除在用的不硬阻断，但返 usage_count 让前端警告。
"""
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, Response
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from ..core.database import get_db
from ..core.deps import CurrentUser, require_permission
from ..core.i18n import req_locale, L
from ..core.log_utils import write_log, new_trace_id
from ..models.landing_lib import LandingPixel, LandingDomain
from ..models.launch import LandingPage, LandingTemplate
from ..core.config import settings

router = APIRouter(prefix="/landing-lib", tags=["landing-lib"])


# 防护规则场景模板（决策③：模板为主；高级模式可改 raw key）。10 key 见 Worker evalProtection。
PROTECTION_TEMPLATES = [
    {"key": "block_common_bots", "name": "屏蔽常见爬虫",
     "desc": "拒 Googlebot/Bingbot/bot/crawler/spider 等爬虫，省广告费防刷。最常用。",
     "rules": {"ua_block": ["bot", "crawler", "spider", "googlebot", "bingbot", "slurp",
                            "duckduckbot", "baiduspider", "yandexbot", "facebookexternalhit",
                            "preview", "debug"]}},
    {"key": "us_mobile_only", "name": "仅美国 + 仅移动端",
     "desc": "只放行美国手机用户",
     "rules": {"country_allow": ["US"], "device_block": ["desktop", "tablet"]}},
    {"key": "us_no_bot", "name": "仅美国 + 屏蔽爬虫",
     "desc": "美国流量 + 拒爬虫",
     "rules": {"country_allow": ["US"], "ua_block": ["bot", "crawler", "spider", "preview", "debug"]}},
    {"key": "no_bot", "name": "屏蔽爬虫",
     "desc": "拒 crawler/bot/spider",
     "rules": {"ua_block": ["bot", "crawler", "spider", "preview", "debug"]}},
    {"key": "mobile_only", "name": "仅移动端",
     "desc": "拒桌面端，只手机",
     "rules": {"device_block": ["desktop"]}},
    {"key": "require_ad", "name": "必带广告参数",
     "desc": "URL 必含 ?ad 参数（子码追踪），防直接访问刷量",
     "rules": {"required_query": ["ad"]}},
    {"key": "block_referer_debug", "name": "拒调试来源",
     "desc": "拒 referer 含 preview/debug 的调试流量",
     "rules": {"referer_block": ["preview", "debug"]}},
]


@router.get("/protection-templates")
def list_protection_templates(user: CurrentUser = Depends(require_permission("ads.read"))):
    """防护规则场景模板（决策③：一键套用；高级模式直接编 10 key raw）。"""
    return PROTECTION_TEMPLATES


# ── 用量统计 helper ──
def _pixel_usage(db: Session, tenant_id: int, pixel_id: str) -> dict:
    """像素被几个落地页用：legacy pixel_id 单值 OR pixel_ids JSON 数组含此像素。"""
    import json as _json
    rows = db.query(LandingPage).filter(
        LandingPage.tenant_id == tenant_id,
        LandingPage.status != "archived",
    ).all()
    used = []
    for r in rows:
        ids = []
        if r.pixel_ids:
            try:
                ids = _json.loads(r.pixel_ids)
            except Exception:
                ids = []
        if pixel_id == r.pixel_id or pixel_id in ids:  # legacy 单像素 OR 多像素数组
            used.append(r)
    return {"usage_count": len(used),
            "used_by": [{"id": r.id, "title": r.title} for r in used[:10]]}


def _pixel_usage_map(db: Session, tenant_id: int) -> dict:
    """全像素用量一次算（列表用，避免每像素全表扫；_pixel_usage 保留给单像素场景）。
    口径同 _pixel_usage：legacy pixel_id 单值 OR pixel_ids JSON 数组含此像素，一页只计一次。"""
    import json as _json
    rows = db.query(LandingPage).filter(
        LandingPage.tenant_id == tenant_id,
        LandingPage.status != "archived",
    ).all()
    usage: dict = {}
    for r in rows:
        ids = []
        if r.pixel_ids:
            try:
                ids = _json.loads(r.pixel_ids)
            except Exception:
                ids = []
        for pid in set(ids + ([r.pixel_id] if r.pixel_id else [])):
            m = usage.setdefault(pid, {"usage_count": 0, "used_by": []})
            m["usage_count"] += 1
            if len(m["used_by"]) < 10:
                m["used_by"].append({"id": r.id, "title": r.title})
    return usage


def _domain_usage(db: Session, tenant_id: int, domain: str) -> dict:
    rows = db.query(LandingPage).filter(
        LandingPage.tenant_id == tenant_id,
        LandingPage.custom_domain == domain,
        LandingPage.status != "archived",
    ).all()
    return {"usage_count": len(rows),
            "used_by": [{"id": r.id, "title": r.title} for r in rows[:10]]}


# ── 像素库 ──
class PixelIn(BaseModel):
    pixel_id: str
    pixel_name: str = ""
    note: str = ""
    platform: str = "fb"
    tt_access_token: str = ""  # TK Events API token（仅 platform=tt；加密存）
    test_event_code: str = ""  # TK Test Events 标签测试码（明文存）


class PixelUpdate(BaseModel):
    pixel_name: str | None = None
    note: str | None = None
    status: str | None = None
    platform: str | None = None
    tt_access_token: str | None = None  # 传则更新，不传则保持
    test_event_code: str | None = None
    fb_capi_enabled: bool | None = None  # FB CAPI S2S 灰度开关（实验性；验证去重后再开）


@router.get("/pixels")
def list_pixels(user: CurrentUser = Depends(require_permission("ads.read")),
                db: Session = Depends(get_db)):
    """列像素——按 pixel_id 去重（一个像素绑多账户只显示一行）。"""
    from sqlalchemy import func as _f
    # 按 pixel_id 取每组最新一行（去重）
    subq = db.query(
        _f.max(LandingPixel.id).label("max_id")
    ).filter(
        LandingPixel.tenant_id == user.tenant_id,
        LandingPixel.status != "archived",
    ).group_by(LandingPixel.pixel_id).subquery()
    rows = db.query(LandingPixel).filter(
        LandingPixel.id.in_(db.query(subq.c.max_id))
    ).order_by(LandingPixel.id.desc()).all()
    # 用量/绑定账户数批量预取（原每像素 2 组查询 = N+1）
    usage_map = _pixel_usage_map(db, user.tenant_id)
    act_map = dict(db.query(
        LandingPixel.pixel_id, _f.count(LandingPixel.id)
    ).filter(
        LandingPixel.tenant_id == user.tenant_id,
        LandingPixel.status != "archived",
    ).group_by(LandingPixel.pixel_id).all())
    out = []
    for p in rows:
        u = usage_map.get(p.pixel_id) or {"usage_count": 0, "used_by": []}
        act_count = act_map.get(p.pixel_id, 0)
        out.append({"id": p.id, "pixel_id": p.pixel_id, "pixel_name": p.pixel_name,
                    "note": p.note, "status": p.status, "act_count": act_count,
                    "platform": p.platform or "fb",
                    "tt_has_token": bool(p.tt_access_token_enc) if (p.platform or "fb") == "tt" else False,
                    "fb_capi_enabled": bool(p.fb_capi_enabled) if (p.platform or "fb") == "fb" else False,
                    "test_event_code": p.test_event_code or "",   # 编辑回显（测试码定期过期，明文可见便于更新）
                    **u})
    return out


@router.post("/pixels")
def create_pixel(body: PixelIn, user: CurrentUser = Depends(require_permission("landing.manage")),
                 db: Session = Depends(get_db)):
    exists = db.query(LandingPixel).filter(
        LandingPixel.tenant_id == user.tenant_id, LandingPixel.pixel_id == body.pixel_id,
    ).first()
    if exists:
        raise HTTPException(400, "该像素已在库中")
    row = LandingPixel(tenant_id=user.tenant_id, created_by=user.id,
                       pixel_id=body.pixel_id, pixel_name=body.pixel_name or None, note=body.note or None,
                       platform=body.platform or "fb",
                       test_event_code=(body.test_event_code or None) if body.platform == "tt" else None)
    if body.platform == "tt" and body.tt_access_token:
        from ..core.encryption import encrypt
        row.tt_access_token_enc = encrypt(body.tt_access_token)
    db.add(row); db.flush()
    tid = new_trace_id()
    write_log(db, tenant_id=user.tenant_id, trace_id=tid, actor_type="user",
              actor_user_id=user.id, target_type="landing_pixel", target_id=str(row.id),
              action_type="create", source="user", result="success",
              metadata={"pixel_id": body.pixel_id})
    db.commit()
    # TK 像素自动点亮：token + test_event_code 齐备 → 建完立即发一条测试事件（失败不影响创建）
    auto_test = None
    if body.platform == "tt" and row.tt_access_token_enc and row.test_event_code:
        try:
            auto_test = {"attempted": True, **_fire_tt_test_event(row)}
        except Exception as e:
            auto_test = {"attempted": True, "ok": False, "code": None, "message": str(e)[:200]}
    return {"id": row.id, "trace_id": tid, "pixel_id": row.pixel_id, "pixel_name": row.pixel_name,
            "auto_test": auto_test}


@router.put("/pixels/{pid}")
def update_pixel(pid: int, body: PixelUpdate,
                 user: CurrentUser = Depends(require_permission("landing.manage")),
                 db: Session = Depends(get_db)):
    row = db.query(LandingPixel).filter(
        LandingPixel.id == pid, LandingPixel.tenant_id == user.tenant_id).first()
    if not row:
        raise HTTPException(404, "像素不存在")
    for k, v in body.model_dump(exclude_unset=True).items():
        if k == "tt_access_token":
            if v:
                from ..core.encryption import encrypt
                row.tt_access_token_enc = encrypt(v)
        else:
            setattr(row, k, v)
    db.commit()
    return {"id": row.id, "pixel_name": row.pixel_name, "status": row.status}


def _fire_tt_test_event(row: LandingPixel) -> dict:
    """用像素已配置的 test_event_code 发一个测试转化事件（手动测试端点 + 建像素自动点亮共用）。"""
    import uuid as _uuid
    from ..core.encryption import decrypt
    from ..core.tk_events import TkEventsClient
    token = decrypt(row.tt_access_token_enc)
    client = TkEventsClient(row.pixel_id, token)
    event_id = str(_uuid.uuid4())
    result = client.send(
        event="CompletePayment",
        event_id=event_id,
        test_event_code=row.test_event_code,
        currency="USD", value=1.0,
    )
    code = result.get("code")
    ok = code == 0
    return {"ok": ok, "code": code, "message": result.get("message", ""),
            "event_id": event_id,
            "hint": "请到 TK Events Manager → 该像素 → Test Events 标签查看（秒级可见）" if ok
                    else "TK API 返回错误，请检查 token/test_code 是否正确"}


@router.post("/pixels/{pid}/test-s2s")
def test_pixel_s2s(pid: int,
                   user: CurrentUser = Depends(require_permission("landing.manage")),
                   db: Session = Depends(get_db)):
    """测试 TK S2S 事件：用 test_event_code 发一个测试事件 → TK Events Manager Test Events 标签秒级可见。"""
    row = db.query(LandingPixel).filter(
        LandingPixel.id == pid, LandingPixel.tenant_id == user.tenant_id).first()
    if not row:
        raise HTTPException(404, "像素不存在")
    if (row.platform or "fb") != "tt":
        raise HTTPException(400, "仅 TK 像素支持测试")
    if not row.tt_access_token_enc:
        raise HTTPException(400, "请先配置 Events API Token")
    if not row.test_event_code:
        raise HTTPException(400, "请先配置 Test Event Code（从 TK Events Manager → Test Events 标签复制）")
    return _fire_tt_test_event(row)


@router.delete("/pixels/{pid}")
def delete_pixel(pid: int, user: CurrentUser = Depends(require_permission("landing.manage")),
                 db: Session = Depends(get_db)):
    row = db.query(LandingPixel).filter(
        LandingPixel.id == pid, LandingPixel.tenant_id == user.tenant_id).first()
    if not row:
        raise HTTPException(404, "像素不存在")
    u = _pixel_usage(db, user.tenant_id, row.pixel_id)
    db.delete(row)
    tid = new_trace_id()
    write_log(db, tenant_id=user.tenant_id, trace_id=tid, actor_type="user",
              actor_user_id=user.id, target_type="landing_pixel", target_id=str(pid),
              action_type="delete", source="user", result="success",
              metadata={"pixel_id": row.pixel_id, "was_in_use": u["usage_count"]})
    db.commit()
    # 返删除前的用量，供前端提示（在用的已保留 landing_pages.pixel_id，不影响已发布页）
    return {"id": pid, "deleted": True, "was_usage_count": u["usage_count"]}


def sync_pixels_for_act(db: Session, fb, tenant_id: int, act_id: str) -> int:
    """同步某账户像素到像素库（绑 act_id）。account_sync 定时 + 手动端点共用。"""
    import logging
    log = logging.getLogger("toveads.pixel_sync")
    added = 0
    try:
        for px in fb.get_pixels(act_id):
            pid = str(px.get("id", ""))
            if not pid:
                continue
            # 按 (tenant, pixel, act) 查重——一个像素可绑多个账户(BM 共享像素),每个账户各建一行
            existing = db.query(LandingPixel).filter(
                LandingPixel.tenant_id == tenant_id, LandingPixel.pixel_id == pid,
                LandingPixel.act_id == act_id,
            ).first()
            if existing:
                existing.pixel_name = px.get("name") or existing.pixel_name
                existing.source = "sync"
            else:
                # savepoint 隔离单条插入：多 cred 覆盖同账户时，查重看不到同事务内未 flush 的待插行，
                # 会在 commit 时违反 uq_landing_pixels_tenant_pixel_act → 整个 account_sync 事务回滚（余额/状态全没更新）。
                # 用 begin_nested 把冲突限制在这一条，回滚它即可，外层事务正常提交。
                try:
                    with db.begin_nested():
                        db.add(LandingPixel(tenant_id=tenant_id, act_id=act_id, pixel_id=pid,
                                            pixel_name=px.get("name"), source="sync", status="active"))
                        db.flush()
                    added += 1
                except Exception:
                    pass  # (tenant,pixel,act) 已存在（竞态/多cred），跳过
    except Exception as e:
        log.warning(f"[PixelSync] act {act_id} 失败: {e}")
    return added


@router.post("/pixels/sync")
def sync_pixels(
    user: CurrentUser = Depends(require_permission("landing.manage")),
    db: Session = Depends(get_db),
):
    """手动触发同步所有账户像素（从 FB 拉，绑 act_id）。返回新增数。"""
    from ..core.fb_client import FbClient
    from ..core.encryption import decrypt
    from ..models.fb import FbCredential, Account
    creds = db.query(FbCredential).filter(FbCredential.status == "active").all()
    added = 0
    for cred in creds:
        try:
            fb = FbClient(decrypt(cred.access_token_enc))
            acts = db.query(Account.act_id).filter(
                Account.tenant_id == cred.tenant_id, Account.act_id.isnot(None)
            ).all()
            for (act_id,) in acts:
                added += sync_pixels_for_act(db, fb, cred.tenant_id, act_id)
        except Exception as e:
            import logging
            logging.getLogger("toveads.pixel_sync").warning(f"[PixelSync] cred {cred.id} 失败: {e}")
    db.commit()
    return {"added": added}


@router.post("/pixels/health-check")
def pixel_health_check(
    user: CurrentUser = Depends(require_permission("landing.manage")),
    db: Session = Depends(get_db),
):
    """像素体检：库里 active 的 FB 像素逐账户比对 FB 实况（每账户 1 次调用，5 并发），
    FB 侧已删/解绑的标 status='dead'——random 轮换/自愈只选 active，死像素不再被选中。
    保守原则：令牌拉不动该账户（失效/无权限）= 实况未知，跳过不标记（拿不到实况不冤杀）。"""
    from ..core.fb_tokens import client_for_account
    from concurrent.futures import ThreadPoolExecutor
    rows = db.query(LandingPixel).filter(
        LandingPixel.tenant_id == user.tenant_id,
        LandingPixel.platform == "fb", LandingPixel.status == "active",
        LandingPixel.act_id.isnot(None), LandingPixel.act_id != "").all()
    if not rows:
        return {"checked_acts": 0, "skipped_acts": 0, "dead": [], "alive": 0}
    by_act: dict = {}
    for r in rows:
        by_act.setdefault(r.act_id, []).append(r)
    # 令牌解析在主线程（session 非线程安全）；FbClient 线程安全（FB 调用并发跑）
    acts = []
    for act_id in by_act:
        fb = client_for_account(db, user.tenant_id, act_id, op_kind="read")
        if fb is not None:
            acts.append((act_id, fb))

    def _one(item):
        act_id, fb = item
        try:
            return act_id, {str(p.get("id")) for p in fb.get_pixels(act_id)}
        except Exception:
            return act_id, None   # 拉不动 = 实况未知

    live: dict = {}
    with ThreadPoolExecutor(max_workers=5) as ex:
        for act_id, ids in ex.map(_one, acts):
            if ids is not None:
                live[act_id] = ids
    skipped = len(by_act) - len(live)
    dead = []
    alive = 0
    for act_id, ids in live.items():
        for r in by_act[act_id]:
            if str(r.pixel_id) in ids:
                alive += 1
            else:
                r.status = "dead"
                dead.append({"pixel_id": r.pixel_id, "name": r.pixel_name, "act_id": act_id})
    db.commit()
    return {"checked_acts": len(live), "skipped_acts": skipped,
            "dead": dead, "alive": alive}


# ── 域名库（V1：只读——仅超管分配，租户不可手填/改/删；像素库仍可手填）──
@router.get("/domains")
def list_domains(user: CurrentUser = Depends(require_permission("ads.read")),
                 db: Session = Depends(get_db)):
    """租户只看超管分配给自己的域名（V1 唯一来源；手填已禁用，V2 再开购买/默认平台域名）。"""
    rows = db.query(LandingDomain).filter(
        LandingDomain.tenant_id == user.tenant_id,
    ).order_by(LandingDomain.id.desc()).all()
    out = []
    for d in rows:
        u = _domain_usage(db, user.tenant_id, d.domain)
        out.append({"id": d.id, "domain": d.domain, "label": d.label, "source": d.source,
                    "cf_zone_status": d.cf_zone_status, "note": d.note, "status": d.status, **u})
    return out


# ── 域名管理（超管：从域名服务商导入/删除；前端文案不暴露具体服务商）──
@router.get("/cf-zones")
def list_importable_zones(
    user: CurrentUser = Depends(require_permission("landing.manage")),
    db: Session = Depends(get_db),
):
    if not getattr(user, "is_superadmin", False):
        raise HTTPException(403, "仅平台超管可查看域名服务 zones")
    """列可导入的域名（超管，从已配置的域名服务商拉取）。"""
    from ..core.cf_client import CfClient
    cf_token = settings.cf_api_token
    cf_account = settings.cf_account_id
    if not cf_token:
        raise HTTPException(500, "域名服务未配置")
    cf = CfClient(cf_token, cf_account)
    resp = cf._get("/zones", params={"per_page": 50})
    imported = {d.domain for d in db.query(LandingDomain).filter(
        LandingDomain.tenant_id == user.tenant_id).all()}
    return [{"name": z.get("name"), "status": z.get("status"),
             "imported": z.get("name") in imported}
            for z in (resp.get("result") or [])]


class DomainImportIn(BaseModel):
    domains: list[str] = []


@router.post("/domains/import")
def import_domains(
    body: DomainImportIn,
    user: CurrentUser = Depends(require_permission("landing.manage")),
    db: Session = Depends(get_db),
):
    if not getattr(user, "is_superadmin", False):
        raise HTTPException(403, "仅平台超管可导入域名")
    """导入域名到域名库（超管）。"""
    added = 0
    for name in body.domains:
        if not name:
            continue
        import re
        name = re.sub(r'^https?://', '', name.strip().lower()).split('/')[0].split(':')[0]
        if not name or '.' not in name:
            continue
        exists = db.query(LandingDomain).filter(
            LandingDomain.tenant_id == user.tenant_id, LandingDomain.domain == name
        ).first()
        if exists:
            continue
        db.add(LandingDomain(tenant_id=user.tenant_id, domain=name,
                             source="imported", status="active"))
        added += 1
    db.commit()
    return {"added": added}


@router.delete("/domains/{did}")
def delete_domain(
    did: int,
    user: CurrentUser = Depends(require_permission("landing.manage")),
    db: Session = Depends(get_db),
):
    """删除域名（超管）。"""
    d = db.query(LandingDomain).filter(
        LandingDomain.id == did, LandingDomain.tenant_id == user.tenant_id
    ).first()
    if not d:
        raise HTTPException(404, "域名不存在")
    db.delete(d)
    db.commit()
    return {"id": did, "deleted": True}


# ── 落地页模板（租户 zip 上传 + 解压防病毒 + 占位符校验 + 载入）──
ALLOWED_TEMPLATE_EXT = {'.html', '.htm', '.css', '.js', '.json', '.svg', '.png', '.jpg', '.jpeg', '.gif', '.woff', '.woff2', '.txt'}
BLOCKED_TEMPLATE_EXT = {'.exe', '.php', '.sh', '.so', '.dll', '.bat', '.cmd', '.py', '.rb', '.pl', '.jar', '.class'}
REQUIRED_PLACEHOLDERS = ['{{TITLE}}', '__LP_TARGET_URL__', '__LP_PIXELS_JSON__']


@router.get("/templates")
def list_templates(
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    rows = db.query(LandingTemplate).filter(
        LandingTemplate.tenant_id == user.tenant_id, LandingTemplate.status == "active"
    ).order_by(LandingTemplate.id.desc()).all()
    return [{"id": r.id, "name": r.name, "description": r.description,
             "is_builtin": r.is_builtin, "has_resources": bool(r.resources_meta)} for r in rows]


@router.post("/templates/upload")
async def upload_template(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    file: UploadFile = File(...),
    user: CurrentUser = Depends(require_permission("landing.manage")),
    db: Session = Depends(get_db),
):
    """zip 上传 → 解压 + 防病毒(白名单/黑名单/大小/数量/路径穿越) + 占位符校验 → 入库。
    校验分两级：error 拦截上传；warning 不拦截，随响应带回（前端 toast 提示）。"""
    import zipfile, io, json, re
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(400, "只支持 .zip 文件")
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(400, "zip 超过 10MB 限制")
    html = None
    resources = {}
    index_hits = 0     # 根目录 index.html 命中数（>1 = 入口歧义，拒）
    resource_files = 0  # 非 index.html 的文件数（warning 用：这些当前不会上线）
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
        names = zf.namelist()
        if len(names) > 100:
            raise HTTPException(400, "zip 内文件数超过 100")
        total = sum(i.file_size for i in zf.infolist())
        if total > 50 * 1024 * 1024:
            raise HTTPException(400, "解压内容超过 50MB")

        _zip_total = [0]   # 实际解压累计字节
        for info in zf.infolist():
            if info.is_dir():
                continue
            fname = info.filename
            if ".." in fname or fname.startswith("/") or fname.startswith("\\"):
                raise HTTPException(400, f"非法路径: {fname}")
            base_name = fname.rsplit("/", 1)[-1]
            ext = ("." + base_name.rsplit(".", 1)[-1].lower()) if "." in base_name else ""
            if ext in BLOCKED_TEMPLATE_EXT:
                raise HTTPException(400, f"禁用文件类型（安全限制）: {fname}")
            if ext not in ALLOWED_TEMPLATE_EXT:
                raise HTTPException(400, f"不支持的文件类型: {fname}")
            # 全库审查P2：声明大小+解压累计双重限额（deflate 炸弹声明小实解大）
            _read = zf.read(info)
            _zip_total[0] += len(_read)
            if _zip_total[0] > 80 * 1024 * 1024:
                raise HTTPException(400, "解压总量超限（80MB）")
            if fname.lower() == "index.html":
                # 入口只认 zip 根目录的 index.html（精确匹配，子目录的不算）
                index_hits += 1
                html = _read.decode("utf-8", errors="ignore")
            else:
                resource_files += 1
                if ext in (".css", ".js", ".json", ".svg", ".txt"):
                    resources[fname] = _read.decode("utf-8", errors="ignore")
    except zipfile.BadZipFile:
        raise HTTPException(400, "损坏的 zip 文件")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"解析失败: {e}")
    if index_hits > 1:
        raise HTTPException(400, "zip 内有多个根目录 index.html，请只保留一个")
    if not html:
        raise HTTPException(400, "zip 根目录未找到 index.html（子目录里的不算）")
    missing = [p for p in REQUIRED_PLACEHOLDERS if p not in html]
    if missing:
        raise HTTPException(400, f"index.html 缺少系统占位符: {', '.join(missing)}")
    # —— warning 级检测（不拦截，按请求 locale 中英双语，响应带回给前端）——
    warnings = []
    loc = req_locale(request)
    if resource_files:
        warnings.append(L(loc, "landing.tplWarnResourceFiles", n=resource_files))
    if re.search(r'''fbq\(\s*['"]init['"]\s*,\s*['"]\d{6,}''', html) \
            or re.search(r'''ttq\.load\(\s*['"][Cc]?\d{6,}''', html):
        warnings.append(L(loc, "landing.tplWarnHardcodedPixel"))
    # 写死外链（排除带占位符的——那些发布时会被替换，是正确写法）
    _hard_links = [u for u in re.findall(r'''href\s*=\s*['"]([^'"]+)['"]''', html)
                   if u.lower().startswith(("http://", "https://"))
                   and "__LP_" not in u and "{{" not in u]
    if _hard_links:
        warnings.append(L(loc, "landing.tplWarnHardcodedLink"))
    supports_tt = "__LP_TT_PIXELS_JSON__" in html
    if not supports_tt:
        warnings.append(L(loc, "landing.tplWarnNoTtPixel"))
    # 同名覆盖：有则 UPDATE，无则 INSERT
    existing_tpl = db.query(LandingTemplate).filter(
        LandingTemplate.tenant_id == user.tenant_id,
        LandingTemplate.name == name,
        LandingTemplate.is_builtin == False,
    ).first()
    if existing_tpl:
        existing_tpl.html = html
        existing_tpl.resources_meta = json.dumps(resources) if resources else None
        existing_tpl.description = description or existing_tpl.description
        row = existing_tpl
        action = "update"
    else:
        row = LandingTemplate(
            tenant_id=user.tenant_id, name=name, description=description or None, html=html,
            resources_meta=json.dumps(resources) if resources else None,
            is_builtin=False, status="active", created_by=user.id,
        )
        db.add(row); db.flush()
        action = "create"
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, target_type="landing_template", target_id=str(row.id),
              action_type=action, source="user", result="success", metadata={"name": name})
    db.commit()
    return {"id": row.id, "name": name, "action": action,
            "warnings": warnings, "supports_tt": supports_tt,
            "validation": {"ok": True, "resources": len(resources)}}


@router.delete("/templates/{tid}")
def delete_template(
    tid: int,
    user: CurrentUser = Depends(require_permission("landing.manage")),
    db: Session = Depends(get_db),
):
    r = db.query(LandingTemplate).filter(
        LandingTemplate.id == tid, LandingTemplate.tenant_id == user.tenant_id).first()
    if not r:
        raise HTTPException(404, "模板不存在")
    if r.is_builtin:
        raise HTTPException(400, "内置模板不可删")
    db.delete(r)
    db.commit()
    return {"id": tid, "deleted": True}


@router.get("/templates/reference")
def template_reference(user: CurrentUser = Depends(require_permission("ads.read"))):
    """下载参考模板 zip（守卫范式：像素/转化 fallback 全带 _d 守卫 + 占位符 + README 规范）。"""
    import zipfile, io
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{TITLE}}</title>
<style>
body{margin:0;padding:0;font-family:-apple-system,'Segoe UI',sans-serif;background:#f5f5f7;color:#1d1d1f}
.c{max-width:480px;margin:0 auto;padding:48px 20px;text-align:center}
h1{font-size:26px;margin:0 0 14px}
p{font-size:15px;color:#6e6e73;line-height:1.6;margin:0 0 32px}
.cta{display:inline-block;padding:14px 44px;background:#0071e3;color:#fff;text-decoration:none;border-radius:10px;font-size:17px;font-weight:600}
</style>
<script>
// 像素 fallback：必须带 _d 守卫（照抄这几行）
// URL 带 ?_d= 的流量（广告访客）由系统注入的 _d_decode / _d_decode_tt 脚本统一
// fire 像素加载、PageView 和 CTA 点击转化；模板 fallback 只管直访（URL 无 _d）。
// 少了 (_d)?[]:(...) 守卫会同一事件双发、像素数据翻倍。
var _d=new URLSearchParams(location.search).get('_d');
var LP_PIXELS=(_d)?[]:(__LP_PIXELS_JSON__||[]);
var LP_CONV=(_d)?[]:(__LP_CONV_EVENT_JSON__||[]);
var LP_TT_PIXELS=(_d)?[]:(__LP_TT_PIXELS_JSON__||[]);
var LP_TT_CONV=(_d)?[]:(__LP_TT_CONV_JSON__||[]);
var LP_TARGET_URL="__LP_TARGET_URL__";

// FB 像素（仅直访加载；加载后 fire 一次 PageView）
if(LP_PIXELS.length){
!function(f,b,e,v,n,t,s){if(f.fbq)return;n=f.fbq=function(){n.callMethod?
n.callMethod.apply(n,arguments):n.queue.push(arguments)};if(!f._fbq)f._fbq=n;
n.push=n;n.loaded=!0;n.version='2.0';n.queue=[];t=b.createElement(e);t.async=!0;
t.src=v;s=b.getElementsByTagName(e)[0];s.parentNode.insertBefore(t,s)}(window,
document,'script','https://connect.facebook.net/en_US/fbevents.js');
LP_PIXELS.forEach(function(pid){if(pid){fbq('init',pid);fbq('trackSingle',pid,'PageView');}});
}

// TikTok 像素（仅直访；有 TT 像素才加载）
if(LP_TT_PIXELS.length){
!function(w,d,t){w.TiktokAnalyticsObject=t;var ttq=w[t]=w[t]||[];
ttq.methods=["page","track","identify","instances","debug","on","off","once","ready","alias","group","enableCookie","disableCookie"];
ttq.setAndDefer=function(t,e){t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}};
for(var i=0;i<ttq.methods.length;i++)ttq.setAndDefer(ttq,ttq.methods[i]);
ttq.load=function(e){var i="https://analytics.tiktok.com/i18n/pixel/events.js";
ttq._i=ttq._i||{};ttq._i[e]=[];ttq._i[e]._u=i;ttq._t=ttq._t||{};ttq._t[e]=+new Date;
ttq._o=ttq._o||{};ttq._o[e]={};
var o=d.createElement("script");o.type="text/javascript";o.async=!0;o.src=i+"?sdkid="+e+"&lib="+t;
var a=d.getElementsByTagName("script")[0];a.parentNode.insertBefore(o,a);};
LP_TT_PIXELS.forEach(function(pid){if(pid)ttq.load(pid);});
ttq.page();
}(window,document,'ttq');
}

// CTA 点击：fire 全部转化事件后 300ms 跳转（守卫的空数组 = 不 fire，_d 流量交给注入脚本）
function trackConversion(){
  if(window.fbq&&LP_PIXELS.length&&LP_CONV.length)
    LP_PIXELS.forEach(function(pid){if(!pid)return;LP_CONV.forEach(function(evt){fbq('trackSingle',pid,evt);});});
  if(window.ttq&&LP_TT_CONV.length)
    LP_TT_CONV.forEach(function(evt){ttq.track(evt);});
}
function goNext(ev){if(ev&&ev.preventDefault)ev.preventDefault();trackConversion();
  setTimeout(function(){window.location.href=LP_TARGET_URL;},300);return false;}
</script>
</head>
<body>
<div class="c">
  <h1>{{TITLE}}</h1>
  <p>{{DESCRIPTION}}</p>
  <a href="__LP_TARGET_URL__" class="cta" id="cta" onclick="return goNext(event)">立即购买</a>
</div>
</body>
</html>"""
    readme = """落地页模板规范（2026-09-10 守卫版）
================================

一、占位符（发布时自动替换；必填缺一上传被拒）
  必填：
    {{TITLE}}               页面标题（<title> + 页面主标题）
    __LP_TARGET_URL__       CTA 跳转目标（替换为页配置的第一个目标）
    __LP_PIXELS_JSON__      FB 像素 ID 数组（直访 fallback）
  可选（不写 = 对应功能不 fire，不影响发布）：
    {{DESCRIPTION}}           页面描述
    __LP_CONV_EVENT_JSON__  FB 转化事件，如 ["Purchase","Contact"]
    __LP_TT_PIXELS_JSON__   TikTok 像素 ID 数组（直访 fallback）
    __LP_TT_CONV_JSON__     TikTok 转化事件，如 ["CompletePayment"]

二、像素脚本机制（最重要，照抄 index.html 的写法）
  系统发布时自动注入 _d_decode（FB）/_d_decode_tt（TT）两段脚本：
  广告流量（URL 带 ?_d=）的像素加载、PageView、CTA 点击转化全部由注入脚本 fire。
  模板里只写「直访 fallback」（URL 无 _d 时才生效），并且必须带守卫：

    var _d=new URLSearchParams(location.search).get('_d');
    var LP_PIXELS=(_d)?[]:(__LP_PIXELS_JSON__||[]);

  守卫 (_d)?[]:(...) 不能省——省了模板 fallback 和注入脚本会同一事件双发，
  像素数据直接翻倍。index.html 里 LP_PIXELS/LP_CONV/LP_TT_PIXELS/LP_TT_CONV
  四个数组全都带守卫，直接照抄。

三、禁止事项（上传会出 warning，而且实际投放必出问题）
  1. 硬编码像素：fbq('init','1234567890') / ttq.load('CXXXXXXXXXX')
     ——系统按页配置动态注入像素，写死会把数据发到错误像素。
  2. 写死 CTA 链接：href="https://xxx.com"
     ——CTA 必须用 __LP_TARGET_URL__ 占位符，否则不跟随目标轮换/子码跳转。
  3. 引用外部 css/js 文件——当前仅部署 index.html，资源文件不会上线，
     样式/脚本请全部内联进 index.html。

四、上传校验规则
  - 只支持 .zip；根目录必须有 index.html（子目录的不算，多个会被拒）
  - index.html 必须含 3 个必填占位符
  - zip <= 10MB，解压 <= 50MB，文件数 <= 100
  - 类型白名单：html/css/js/json/svg/png/jpg/jpeg/gif/woff/woff2/txt；
    禁止 exe/php/sh/so/dll/bat/cmd/py 等
  - 硬编码像素/写死链接/缺 TT 占位符/含资源文件只出 warning 不拦截

五、上传前建议
  本地把占位符手动替换成假值检查效果（如 __LP_PIXELS_JSON__ 换成
  ["111111111111111"]、__LP_TARGET_URL__ 换成 https://example.com），
  浏览器打开确认排版和按钮跳转正常后再上传。
"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("index.html", html)
        zf.writestr("README.txt", readme)
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": "attachment; filename=template-reference.zip"})
