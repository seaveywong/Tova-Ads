"""素材库路由 v2：上传/列表/搜索/重命名/标签/删除 + FB image_hash。

v1: 本地存储（/opt/toveads/assets/）+ 基础 CRUD
v2: 加 name/tags/public_url/搜索/重命名/引用检查
"""
import os, uuid, json
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from ..core.database import get_db
from ..core.deps import CurrentUser, require_permission
from ..core.log_utils import write_log, new_trace_id
from ..models.launch import Asset

router = APIRouter(prefix="/assets", tags=["assets"])

ASSET_DIR = os.environ.get("ASSET_DIR", "/opt/toveads/assets")
PUBLIC_BASE = os.environ.get("PUBLIC_BASE_URL", "https://api.tovaads.com")


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
    user: CurrentUser = Depends(require_permission("assets.manage")),
    db: Session = Depends(get_db),
):
    """上传素材（图片/视频）→ 本地存储 + Asset 行。

    name/tags 通过 FormData 传（和 file 一起）。tags 是 JSON 数组字符串。
    """
    os.makedirs(ASSET_DIR, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1] or ".jpg"
    storage_key = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(ASSET_DIR, storage_key)
    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)
    ftype = "video" if ext.lower() in (".mp4", ".mov", ".avi", ".webm") else "image"
    mime = file.content_type or ""
    user_name = name.strip() or (file.filename or storage_key)
    # 清理 tags JSON
    try:
        tag_list = json.loads(tags) if tags else []
        if not isinstance(tag_list, list):
            tag_list = []
    except Exception:
        tag_list = []
    public_url = f"{PUBLIC_BASE}/static-assets/{storage_key}"
    asset = Asset(
        tenant_id=user.tenant_id, owner_user_id=user.id, type=ftype,
        storage_key=storage_key, filename=file.filename or storage_key,
        name=user_name, tags=json.dumps(tag_list) if tag_list else None,
        public_url=public_url, file_size=len(content), mime_type=mime,
        category="常规", status="active",
    )
    db.add(asset)
    db.flush()
    tid = new_trace_id()
    write_log(db, tenant_id=user.tenant_id, trace_id=tid, actor_type="user",
              actor_user_id=user.id, target_type="asset", target_id=str(asset.id),
              action_type="upload", source="user", result="success",
              metadata={"name": user_name, "type": ftype, "size": len(content)})
    db.commit()
    return _asset_dict(asset)


class AssetUpdateIn(BaseModel):
    name: Optional[str] = None
    tags: Optional[list] = None


@router.put("/{aid}")
def update_asset(aid: int, body: AssetUpdateIn,
                 user: CurrentUser = Depends(require_permission("assets.manage")),
                 db: Session = Depends(get_db)):
    """重命名 / 改标签。"""
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
