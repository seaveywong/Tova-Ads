"""素材库路由：上传/列表/删除 + FB image_hash 上传（完成广告创建链）。

v1：本地存储（/opt/toveads/assets/）；R2 v2。
AI 13 purpose 分析 v2（现 /ai/copy 文案已能生成）。
"""
import os, uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from pydantic import BaseModel
from ..core.database import get_db
from ..core.deps import CurrentUser, require_permission
from ..core.encryption import decrypt
from ..core.fb_client import FbClient, FbApiError
from ..core.fb_tokens import client_for_account
from ..core.log_utils import write_log, new_trace_id
from ..models.launch import Asset

router = APIRouter(prefix="/assets", tags=["assets"])

ASSET_DIR = os.environ.get("ASSET_DIR", "/opt/toveads/assets")


@router.get("")
def list_assets(user: CurrentUser = Depends(require_permission("ads.read")),
                db: Session = Depends(get_db)):
    rows = db.query(Asset).filter(Asset.tenant_id == user.tenant_id).order_by(Asset.id.desc()).all()
    return [{"id": a.id, "type": a.type, "filename": a.filename, "storage_key": a.storage_key,
             "fb_image_hash": a.fb_image_hash, "category": a.category, "status": a.status} for a in rows]


@router.post("/upload")
async def upload_asset(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(require_permission("ads.create")),
    db: Session = Depends(get_db),
):
    """上传素材（图片/视频）→ 本地存储 + Asset 行。返 asset + storage_key。"""
    os.makedirs(ASSET_DIR, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1] or ".jpg"
    storage_key = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(ASSET_DIR, storage_key)
    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)
    ftype = "video" if ext.lower() in (".mp4", ".mov", ".avi") else "image"
    asset = Asset(
        tenant_id=user.tenant_id, owner_user_id=user.id, type=ftype,
        storage_key=storage_key, filename=file.filename or storage_key,
        category="常规", status="active",
    )
    db.add(asset)
    db.flush()
    tid = new_trace_id()
    write_log(db, tenant_id=user.tenant_id, trace_id=tid, actor_type="user",
              actor_user_id=user.id, target_type="asset", target_id=str(asset.id),
              action_type="upload", source="user", result="success",
              metadata={"filename": file.filename, "type": ftype})
    db.commit()
    return {"id": asset.id, "storage_key": storage_key, "filename": asset.filename, "type": ftype}


class FbUploadIn(BaseModel):
    act_id: str


@router.post("/{aid}/fb-upload")
def fb_upload_image(aid: int, body: FbUploadIn,
                    user: CurrentUser = Depends(require_permission("ads.create")),
                    db: Session = Depends(get_db)):
    """上传素材到 FB 广告账户 → 拿 image_hash（供铺广告创意用）。仅图片。"""
    asset = db.query(Asset).filter(Asset.id == aid, Asset.tenant_id == user.tenant_id).first()
    if not asset:
        raise HTTPException(404, "素材不存在")
    if asset.type != "image":
        raise HTTPException(400, "FB image_hash 仅支持图片素材")
    filepath = os.path.join(ASSET_DIR, asset.storage_key)
    if not os.path.exists(filepath):
        raise HTTPException(404, "素材文件丢失")
    with open(filepath, "rb") as f:
        image_bytes = f.read()
    fb = client_for_account(db, user.tenant_id, body.act_id)
    if not fb:
        raise HTTPException(400, "未绑定有效 FB 凭证")
    try:
        result = fb.upload_ad_image(body.act_id, image_bytes, asset.filename or "image.jpg")
    except FbApiError as e:
        raise HTTPException(400, f"FB 上传失败：{e.friendly}")
    asset.fb_image_hash = result.get("hash")
    tid = new_trace_id()
    write_log(db, tenant_id=user.tenant_id, trace_id=tid, actor_type="user",
              actor_user_id=user.id, target_type="asset", target_id=str(aid),
              action_type="fb_upload", source="fb_api", result="success",
              metadata={"act_id": body.act_id, "image_hash": result.get("hash")})
    db.commit()
    return {"id": aid, "fb_image_hash": result.get("hash"), "fb_url": result.get("url")}


@router.delete("/{aid}")
def delete_asset(aid: int, user: CurrentUser = Depends(require_permission("ads.create")),
                 db: Session = Depends(get_db)):
    asset = db.query(Asset).filter(Asset.id == aid, Asset.tenant_id == user.tenant_id).first()
    if not asset:
        raise HTTPException(404, "素材不存在")
    # 删本地文件
    try:
        os.remove(os.path.join(ASSET_DIR, asset.storage_key))
    except Exception:
        pass
    db.delete(asset)
    db.commit()
    return {"id": aid, "deleted": True}
