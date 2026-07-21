"""像素库 + 域名库 CRUD（落地页重做，决策 2/6）。

按租户隔离（RLS + tenant_id）。每条带 usage_count + used_by（决策⑥双向闭环）：
- 像素用量 = landing_pages WHERE pixel_id = 此像素（多像素迁移后改 JSON contains）
- 域名用量 = landing_pages WHERE custom_domain = 此域名
删除在用的不硬阻断，但返 usage_count 让前端警告。
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Response
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from ..core.database import get_db
from ..core.deps import CurrentUser, require_permission
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


class PixelUpdate(BaseModel):
    pixel_name: str | None = None
    note: str | None = None
    status: str | None = None


@router.get("/pixels")
def list_pixels(user: CurrentUser = Depends(require_permission("ads.read")),
                db: Session = Depends(get_db)):
    rows = db.query(LandingPixel).filter(
        LandingPixel.tenant_id == user.tenant_id,
    ).order_by(LandingPixel.id.desc()).all()
    out = []
    for p in rows:
        u = _pixel_usage(db, user.tenant_id, p.pixel_id)
        out.append({"id": p.id, "pixel_id": p.pixel_id, "pixel_name": p.pixel_name,
                    "note": p.note, "status": p.status, **u})
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
                       pixel_id=body.pixel_id, pixel_name=body.pixel_name or None, note=body.note or None)
    db.add(row); db.flush()
    tid = new_trace_id()
    write_log(db, tenant_id=user.tenant_id, trace_id=tid, actor_type="user",
              actor_user_id=user.id, target_type="landing_pixel", target_id=str(row.id),
              action_type="create", source="user", result="success",
              metadata={"pixel_id": body.pixel_id})
    db.commit()
    return {"id": row.id, "trace_id": tid, "pixel_id": row.pixel_id, "pixel_name": row.pixel_name}


@router.put("/pixels/{pid}")
def update_pixel(pid: int, body: PixelUpdate,
                 user: CurrentUser = Depends(require_permission("landing.manage")),
                 db: Session = Depends(get_db)):
    row = db.query(LandingPixel).filter(
        LandingPixel.id == pid, LandingPixel.tenant_id == user.tenant_id).first()
    if not row:
        raise HTTPException(404, "像素不存在")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    db.commit()
    return {"id": row.id, "pixel_name": row.pixel_name, "status": row.status}


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
                db.add(LandingPixel(tenant_id=tenant_id, act_id=act_id, pixel_id=pid,
                                    pixel_name=px.get("name"), source="sync", status="active"))
                added += 1
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
    name: str = Form(...),
    description: str = Form(""),
    file: UploadFile = File(...),
    user: CurrentUser = Depends(require_permission("landing.manage")),
    db: Session = Depends(get_db),
):
    """zip 上传 → 解压 + 防病毒(白名单/黑名单/大小/数量/路径穿越) + 占位符校验 → 入库。"""
    import zipfile, io, json
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(400, "只支持 .zip 文件")
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(400, "zip 超过 10MB 限制")
    html = None
    resources = {}
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
        names = zf.namelist()
        if len(names) > 100:
            raise HTTPException(400, "zip 内文件数超过 100")
        total = sum(i.file_size for i in zf.infolist())
        if total > 50 * 1024 * 1024:
            raise HTTPException(400, "解压内容超过 50MB")
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
            if base_name.lower() in ("index.html", "index.htm"):
                html = zf.read(info).decode("utf-8", errors="ignore")
            elif ext in (".css", ".js", ".json", ".svg", ".txt"):
                resources[fname] = zf.read(info).decode("utf-8", errors="ignore")
    except zipfile.BadZipFile:
        raise HTTPException(400, "损坏的 zip 文件")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"解析失败: {e}")
    if not html:
        raise HTTPException(400, "zip 内未找到 index.html")
    missing = [p for p in REQUIRED_PLACEHOLDERS if p not in html]
    if missing:
        raise HTTPException(400, f"index.html 缺少系统占位符: {', '.join(missing)}")
    row = LandingTemplate(
        tenant_id=user.tenant_id, name=name, description=description or None, html=html,
        resources_meta=json.dumps(resources) if resources else None,
        is_builtin=False, status="active", created_by=user.id,
    )
    db.add(row); db.flush()
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, target_type="landing_template", target_id=str(row.id),
              action_type="create", source="user", result="success", metadata={"name": name})
    db.commit()
    return {"id": row.id, "name": name, "validation": {"ok": True, "resources": len(resources)}}


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
    """下载参考模板 zip（双模式适配：_d 解码 + 多转化 + 动态 target）。"""
    import zipfile, io
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{TITLE}}</title>
<style>
body{margin:0;padding:0;font-family:-apple-system,sans-serif;background:#f5f5f7;color:#1d1d1f}
.c{max-width:480px;margin:0 auto;padding:40px 20px;text-align:center}
h1{font-size:28px;margin:0 0 16px}
p{font-size:16px;color:#6e6e73;line-height:1.6;margin:0 0 32px}
.cta{display:inline-block;padding:14px 40px;background:#0071e3;color:#fff;text-decoration:none;border-radius:10px;font-size:17px;font-weight:600}
</style>
<script>
!function(f,b,e,v,n,t,s){if(f.fbq)return;n=f.fbq=function(){n.callMethod?n.callMethod.apply(n,arguments):n.queue.push(arguments)};if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version='2.0';n.queue=[];t=b.createElement(e);t.async=!0;t.src=v;s=b.getElementsByTagName(e)[0];s.parentNode.insertBefore(t,s)}(window,document,'script','https://connect.facebook.net/en_US/fbevents.js');
var _d=new URLSearchParams(location.search).get('_d');var _info={};try{_info=JSON.parse(decodeURIComponent(escape(atob(_d))))}catch(e){}
var LP_PIXELS=(_info.p&&_info.p.length)?_info.p.split(',').filter(Boolean):(__LP_PIXELS_JSON__||[]);
var LP_TARGET_URL=_info.t||"__LP_TARGET_URL__";
var _rawConv=_info.c?_info.c.split(','):(__LP_CONV_EVENT_JSON__||[]);
var LP_CONV=(Array.isArray(_rawConv)?_rawConv:[_rawConv]).filter(Boolean);
LP_PIXELS.forEach(function(pid){if(pid){fbq('init',pid);fbq('trackSingle',pid,'PageView');}});
var _cta=document.getElementById('cta');if(_cta&&LP_TARGET_URL)_cta.href=LP_TARGET_URL;
function trackConversion(){if(!window.fbq||!Array.isArray(LP_PIXELS)||!LP_CONV.length)return;LP_PIXELS.forEach(function(pid){if(!pid)return;LP_CONV.forEach(function(evt){fbq('trackSingle',pid,evt);});});}
function goNext(ev){if(ev&&ev.preventDefault)ev.preventDefault();trackConversion();setTimeout(function(){window.location.href=LP_TARGET_URL;},300);return false;}
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
    readme = (
        "落地页模板规范（双模式适配版）\n"
        "================================\n\n"
        "适配说明（开发者必读）：\n\n"
        "1. _d 参数：系统在落地页模式下通过 URL ?_d=xxx 传入 base64 编码的 JSON，\n"
        "   含 p（像素ID逗号分隔）、t（CTA跳转目标）、c（转化事件逗号分隔）。\n"
        "   HTML JS 优先从 _d 解码读取（动态，子码级），fallback 到 publish 注入的占位符。\n\n"
        "2. 必须包含的系统占位符（publish 时自动替换）：\n"
        "   {{TITLE}}              页面标题\n"
        "   {{DESCRIPTION}}        描述\n"
        "   __LP_TARGET_URL__      CTA 跳转目标（fallback，运行时被 _d.t 覆盖）\n"
        "   __LP_PIXELS_JSON__     像素 ID 数组（fallback，运行时被 _d.p 覆盖）\n"
        "   __LP_CONV_EVENT_JSON__ 转化事件（fallback，运行时被 _d.c 覆盖）\n\n"
        "3. 多转化事件：LP_CONV 是数组（如 ['Purchase','Contact']），\n"
        "   CTA 点击时 forEach 对每个像素 fire 每个事件。\n\n"
        "4. CTA 跳转：goNext() 先 trackConversion() 再 setTimeout 300ms 跳 LP_TARGET_URL。\n\n"
        "5. 规则：\n"
        "   - zip 根目录必须有 index.html\n"
        "   - index.html 必须含上述占位符（否则上传校验失败）\n"
        "   - 支持类型：html/css/js/json/svg/png/jpg/gif/woff2/txt\n"
        "   - 禁止：exe/php/sh/so/dll/bat/cmd/py 等\n"
        "   - zip <=10MB，解压 <=50MB，文件数 <=100\n"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("index.html", html)
        zf.writestr("README.txt", readme)
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": "attachment; filename=template-reference.zip"})
