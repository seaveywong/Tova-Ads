"""素材库路由 v2：上传/列表/搜索/重命名/标签/删除 + FB image_hash + AI 分析。

v1: 本地存储（/opt/toveads/assets/）+ 基础 CRUD
v2: 加 name/tags/public_url/搜索/重命名/引用检查
v3: AI 分析（图片→视觉模型看图；视频→ffmpeg抽关键帧→视觉模型）→ 生成 ai_copy + ai_audience
"""
import os, uuid, json, base64
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from ..core.database import get_db
from ..core.deps import CurrentUser, require_permission
from ..core.log_utils import write_log, new_trace_id
from ..core.ai_client import chat_with_images_json, vision_client, AiError
from ..core.media_util import image_dimensions, video_duration, extract_keyframes, file_as_b64, is_video
from ..models.launch import Asset

router = APIRouter(prefix="/assets", tags=["assets"])

ASSET_DIR = os.environ.get("ASSET_DIR", "/opt/toveads/assets")
PUBLIC_BASE = os.environ.get("PUBLIC_BASE_URL", "https://api.tovaads.com")

# 地区→语言（与 ai.py REGION_LANG 一致；AI 文案命中目标投放地区）
REGION_LANG = {
    "TW": "繁體中文", "HK": "繁體中文", "MO": "繁體中文",
    "CN": "简体中文", "SG": "简体中文",
    "US": "English", "GB": "English", "AU": "English", "CA": "English", "PH": "English", "MY": "English", "IN": "English",
    "VN": "Tiếng Việt", "TH": "ภาษาไทย", "ID": "Bahasa Indonesia", "JP": "日本語", "KR": "한국어",
    "ES": "Español", "MX": "Español", "BR": "Português", "DE": "Deutsch", "FR": "Français", "RU": "Русский", "AE": "العربية", "SA": "العربية",
}


def _parse_json_field(raw, default):
    """安全解析存在 Text 列里的 JSON 字符串。"""
    if not raw:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return default


def _mark_asset_failed(db: Session, a: Asset, msg: str):
    """分析失败：回写 ai_status=failed + ai_error。commit 失败先 rollback 再重试，绝不让行卡在 analyzing。"""
    try:
        a.ai_status = "failed"
        a.ai_error = msg
        db.commit()
    except Exception:
        try:
            db.rollback()
            a.ai_status = "failed"
            a.ai_error = msg
            db.commit()
        except Exception:
            db.rollback()


def _asset_dict(a: Asset) -> dict:
    """统一序列化（前端用的字段）。"""
    tags = []
    if a.tags:
        try: tags = json.loads(a.tags) if isinstance(a.tags, str) else a.tags
        except: tags = []
    return {
        "id": a.id, "type": a.type, "filename": a.filename,
        "name": a.name or a.filename or a.storage_key,
        "storage_key": a.storage_key,
        "public_url": a.public_url or f"{PUBLIC_BASE}/static-assets/{a.storage_key}",
        "tags": tags, "file_size": a.file_size or 0,
        "mime_type": a.mime_type or "", "width": a.width or 0, "height": a.height or 0,
        "duration_sec": a.duration_sec or 0, "usage_count": a.usage_count or 0,
        "fb_image_hash": a.fb_image_hash, "category": a.category, "status": a.status,
        "country": a.country or "",
        "ai_status": a.ai_status or "none",
        "ai_error": a.ai_error or "",
        "ai_copy": _parse_json_field(a.ai_copy_json, {"primary_text": "", "headline": "", "description": ""}),
        "ai_audience": _parse_json_field(a.ai_audience_json, {"interests": [], "countries": []}),
        "analyzed_at": str(a.analyzed_at) if a.analyzed_at else "",
        "created_at": str(a.created_at) if a.created_at else "",
    }


@router.get("")
def list_assets(
    type: Optional[str] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
    user: CurrentUser = Depends(require_permission("assets.manage")),
    db: Session = Depends(get_db),
):
    """列本租户素材 + 筛选（类型/标签/名称搜索）。"""
    q = db.query(Asset).filter(Asset.tenant_id == user.tenant_id, Asset.status == "active")
    if type:
        q = q.filter(Asset.type == type)
    if tag:
        q = q.filter(Asset.tags.contains(tag))
    if search:
        q = q.filter(Asset.name.ilike(f"%{search}%"))
    rows = q.order_by(Asset.id.desc()).all()
    return [_asset_dict(a) for a in rows]


@router.get("/{aid}")
def get_asset(aid: int, user: CurrentUser = Depends(require_permission("assets.manage")),
              db: Session = Depends(get_db)):
    """素材详情。"""
    a = db.query(Asset).filter(Asset.id == aid, Asset.tenant_id == user.tenant_id).first()
    if not a:
        raise HTTPException(404, "素材不存在")
    return _asset_dict(a)


@router.post("/upload")
async def upload_asset(
    file: UploadFile = File(...),
    name: str = Form(""),
    tags: str = Form("[]"),
    country: str = Form(""),
    user: CurrentUser = Depends(require_permission("assets.manage")),
    db: Session = Depends(get_db),
):
    """上传素材（图片/视频）→ 本地存储 + Asset 行。

    name/tags/country 通过 FormData 传（和 file 一起）。tags 是 JSON 数组字符串。
    上传时自动探测图片尺寸（Pillow）/视频时长（ffprobe），缺工具则留 0 不阻断。
    """
    os.makedirs(ASSET_DIR, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1] or ".jpg"
    storage_key = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(ASSET_DIR, storage_key)
    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)
    ftype = "video" if is_video(filepath) else "image"
    mime = file.content_type or ""
    user_name = name.strip() or (file.filename or storage_key)
    # 清理 tags JSON
    try:
        tag_list = json.loads(tags) if tags else []
        if not isinstance(tag_list, list):
            tag_list = []
    except Exception:
        tag_list = []
    # 探测尺寸/时长（缺工具优雅降级）
    width = height = duration = 0
    if ftype == "image":
        dim = image_dimensions(filepath)
        if dim:
            width, height = dim
    else:
        duration = video_duration(filepath) or 0
    public_url = f"{PUBLIC_BASE}/static-assets/{storage_key}"
    asset = Asset(
        tenant_id=user.tenant_id, owner_user_id=user.id, type=ftype,
        storage_key=storage_key, filename=file.filename or storage_key,
        name=user_name, tags=json.dumps(tag_list) if tag_list else None,
        public_url=public_url, file_size=len(content), mime_type=mime,
        width=width, height=height, duration_sec=duration,
        country=country.strip().upper() or None,
        category="常规", status="active",
    )
    db.add(asset)
    db.flush()
    tid = new_trace_id()
    write_log(db, tenant_id=user.tenant_id, trace_id=tid, actor_type="user",
              actor_user_id=user.id, target_type="asset", target_id=str(asset.id),
              action_type="upload", source="user", result="success",
              metadata={"name": user_name, "type": ftype, "size": len(content), "country": country})
    db.commit()
    return _asset_dict(asset)


class AssetUpdateIn(BaseModel):
    name: Optional[str] = None
    tags: Optional[list] = None
    country: Optional[str] = None


@router.put("/{aid}")
def update_asset(aid: int, body: AssetUpdateIn,
                 user: CurrentUser = Depends(require_permission("assets.manage")),
                 db: Session = Depends(get_db)):
    """重命名 / 改标签 / 改国家。"""
    a = db.query(Asset).filter(Asset.id == aid, Asset.tenant_id == user.tenant_id).first()
    if not a:
        raise HTTPException(404, "素材不存在")
    if body.name is not None:
        n = body.name.strip()
        if not n:
            raise HTTPException(400, "名称不能为空")
        a.name = n
    if body.tags is not None:
        a.tags = json.dumps(body.tags) if body.tags else None
    if body.country is not None:
        a.country = body.country.strip().upper() or None
    tid = new_trace_id()
    write_log(db, tenant_id=user.tenant_id, trace_id=tid, actor_type="user",
              actor_user_id=user.id, target_type="asset", target_id=str(aid),
              action_type="rename", source="user", result="success",
              metadata={"name": a.name})
    db.commit()
    return _asset_dict(a)


class FbUploadIn(BaseModel):
    act_id: str


@router.post("/{aid}/fb-upload")
def fb_upload_image(aid: int, body: FbUploadIn,
                    user: CurrentUser = Depends(require_permission("assets.manage")),
                    db: Session = Depends(get_db)):
    """上传素材到 FB 广告账户 → 拿 image_hash（供铺广告创意用）。仅图片。"""
    from ..core.fb_client import FbClient, FbApiError
    from ..core.fb_tokens import client_for_account
    a = db.query(Asset).filter(Asset.id == aid, Asset.tenant_id == user.tenant_id).first()
    if not a:
        raise HTTPException(404, "素材不存在")
    if a.type != "image":
        raise HTTPException(400, "FB image_hash 仅支持图片素材")
    filepath = os.path.join(ASSET_DIR, a.storage_key)
    if not os.path.exists(filepath):
        raise HTTPException(404, "素材文件丢失")
    with open(filepath, "rb") as f:
        image_bytes = f.read()
    fb = client_for_account(db, user.tenant_id, body.act_id)
    if not fb:
        raise HTTPException(400, "未绑定有效 FB 凭证")
    try:
        result = fb.upload_ad_image(body.act_id, image_bytes, a.filename or "image.jpg")
    except FbApiError as e:
        raise HTTPException(400, f"FB 上传失败：{e.friendly}")
    a.fb_image_hash = result.get("hash")
    tid = new_trace_id()
    write_log(db, tenant_id=user.tenant_id, trace_id=tid, actor_type="user",
              actor_user_id=user.id, target_type="asset", target_id=str(aid),
              action_type="fb_upload", source="fb_api", result="success",
              metadata={"act_id": body.act_id, "image_hash": result.get("hash")})
    db.commit()
    return {"id": aid, "fb_image_hash": result.get("hash"), "fb_url": result.get("url")}


@router.post("/{aid}/analyze")
def analyze_asset(aid: int, user: CurrentUser = Depends(require_permission("assets.manage")),
                  db: Session = Depends(get_db)):
    """AI 分析素材 → 生成广告文案 + 受众建议。

    图片：读文件 base64 → 视觉模型看图。
    视频：ffmpeg 抽 3 关键帧（10%/50%/90%）→ 视觉模型多图看。
    country 驱动文案语言（REGION_LANG）；视觉用独立 ai_vision_* 配置（Gemini）。
    """
    a = db.query(Asset).filter(Asset.id == aid, Asset.tenant_id == user.tenant_id).first()
    if not a:
        raise HTTPException(404, "素材不存在")
    if not vision_client().is_configured():
        raise HTTPException(400, "视觉 AI 未配置（缺 ai_vision_api_key）")
    filepath = os.path.join(ASSET_DIR, a.storage_key)
    if not os.path.exists(filepath):
        raise HTTPException(404, "素材文件丢失")
    # 先置 analyzing（前端可即时反馈）；注意：失败时只在此处之后的 except 里回写 failed
    a.ai_status = "analyzing"
    a.ai_error = None
    db.commit()
    try:
        if a.type == "image":
            b64 = file_as_b64(filepath)
            if not b64:
                raise AiError("图片读不出（文件损坏？）")
            mime = a.mime_type or "image/jpeg"
            images = [b64]
            medium = "图片"
        else:  # video
            frames = extract_keyframes(filepath, 3)
            if not frames:
                raise AiError("视频抽帧失败（服务器未装 ffmpeg 或文件损坏）")
            images = [base64.b64encode(f).decode("ascii") for f in frames]
            mime = "image/jpeg"
            medium = f"视频（{len(frames)} 个关键帧）"
        lang = REGION_LANG.get((a.country or "").upper(), "English")
        sys_msg = ("你是 FB 广告素材分析专家。看图/视频关键帧 → 推断产品与卖点 → 生成 FB 广告文案 + 受众建议。"
                   "符合 FB 合规（禁绝对化/医疗承诺词）。严格只返回 JSON，不要任何解释或 markdown。")
        prompt = (
            f"这是广告{medium}。目标投放国家：{a.country or '未指定'}，文案语言：{lang}。\n"
            "分析素材内容，返回 JSON：\n"
            '{"primary_text":"广告正文(80字内,吸引点击)","headline":"标题(30字内)",'
            '"description":"描述(30字内)","interests":["兴趣标签1","兴趣标签2","兴趣标签3"],'
            '"countries":["国家代码"]}。\n'
            f"countries 用 ISO 国家代码（如 {a.country} 若已知），interests 给 3-6 个相关兴趣。"
        )
        data = chat_with_images_json(prompt, images, mime=mime, system_prompt=sys_msg)
        # 拆成 copy / audience 两组
        copy_obj = {
            "primary_text": str(data.get("primary_text", "")).strip(),
            "headline": str(data.get("headline", "")).strip(),
            "description": str(data.get("description", "")).strip(),
        }
        aud_obj = {
            "interests": data.get("interests") or [],
            "countries": data.get("countries") or ([a.country] if a.country else []),
        }
        a.ai_copy_json = json.dumps(copy_obj, ensure_ascii=False)
        a.ai_audience_json = json.dumps(aud_obj, ensure_ascii=False)
        a.ai_status = "done"
        a.ai_error = None
        a.analyzed_at = datetime.now(timezone.utc)
        tid = new_trace_id()
        write_log(db, tenant_id=user.tenant_id, trace_id=tid, actor_type="user",
                  actor_user_id=user.id, target_type="asset", target_id=str(aid),
                  action_type="ai_analyze", source="ai_vision", result="success",
                  metadata={"medium": medium, "country": a.country})
        out = _asset_dict(a)  # 先序列化（commit 后 ORM 对象仍可用，但提前取避免后续异常回退 done→failed）
        db.commit()
        return out
    except AiError as e:
        _mark_asset_failed(db, a, e.message)
        raise HTTPException(400, f"AI 分析失败：{e.message}")
    except HTTPException:
        raise
    except Exception as e:
        _mark_asset_failed(db, a, str(e)[:300])
        raise HTTPException(500, f"AI 分析异常：{e}")


class AssetAiIn(BaseModel):
    """手动编辑 AI 字段（AI 开关关时用户自己填文案/受众）。"""
    primary_text: str = ""
    headline: str = ""
    description: str = ""
    interests: list = []
    countries: list = []


@router.put("/{aid}/ai")
def update_asset_ai(aid: int, body: AssetAiIn,
                    user: CurrentUser = Depends(require_permission("assets.manage")),
                    db: Session = Depends(get_db)):
    """手动编辑素材的 AI 文案 + 受众（不走视觉模型；用户键入）。"""
    a = db.query(Asset).filter(Asset.id == aid, Asset.tenant_id == user.tenant_id).first()
    if not a:
        raise HTTPException(404, "素材不存在")
    a.ai_copy_json = json.dumps({
        "primary_text": body.primary_text.strip(),
        "headline": body.headline.strip(),
        "description": body.description.strip(),
    }, ensure_ascii=False)
    a.ai_audience_json = json.dumps({
        "interests": body.interests or [],
        "countries": body.countries or [],
    }, ensure_ascii=False)
    if a.ai_status != "done":
        a.ai_status = "done"
    if not a.analyzed_at:
        a.analyzed_at = datetime.now(timezone.utc)
    tid = new_trace_id()
    write_log(db, tenant_id=user.tenant_id, trace_id=tid, actor_type="user",
              actor_user_id=user.id, target_type="asset", target_id=str(aid),
              action_type="ai_edit", source="user", result="success")
    db.commit()
    return _asset_dict(a)


@router.delete("/{aid}")
def delete_asset(aid: int, user: CurrentUser = Depends(require_permission("assets.manage")),
                 db: Session = Depends(get_db)):
    """硬删素材：先删服务器文件，再删 DB 行。被引用时阻止。"""
    a = db.query(Asset).filter(Asset.id == aid, Asset.tenant_id == user.tenant_id).first()
    if not a:
        raise HTTPException(404, "素材不存在")
    if (a.usage_count or 0) > 0:
        raise HTTPException(400, f"该素材被 {a.usage_count} 个投放模板引用，请先移除引用")
    # 硬删本地文件
    try:
        os.remove(os.path.join(ASSET_DIR, a.storage_key))
    except Exception:
        pass
    db.delete(a)
    tid = new_trace_id()
    write_log(db, tenant_id=user.tenant_id, trace_id=tid, actor_type="user",
              actor_user_id=user.id, target_type="asset", target_id=str(aid),
              action_type="delete", source="user", result="success",
              metadata={"name": a.name})
    db.commit()
    return {"id": aid, "deleted": True}
