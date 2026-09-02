"""Facebook App 配置 CRUD（系统级 + 团队）。

系统级 App（is_system=true）：superadmin 创建，全租户共享
团队 App（is_system=false）：owner 创建，自己租户私有
"""
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..core.database import get_db, SuperSessionLocal
from ..core.deps import CurrentUser, require_permission
from ..core.encryption import encrypt, decrypt
from ..models.fb_app import FbApp

router = APIRouter(prefix="/fb/apps", tags=["fb-apps"])


class AppIn(BaseModel):
    app_id: str
    app_secret: str
    name: str = ""
    is_system: bool = False


def _app_dict(a):
    return {
        "id": a.id,
        "name": a.name,
        "app_id": a.app_id,
        "is_system": a.is_system,
        "status": a.status,
        "created_at": str(a.created_at) if a.created_at else None,
    }


@router.get("")
def list_apps(user: CurrentUser = Depends(require_permission("ads.read")), db: Session = Depends(get_db)):
    """列出 App（系统级 + 自己租户的）。RLS 自动隔离。"""
    apps = db.query(FbApp).filter(FbApp.status == "active").all()
    return [_app_dict(a) for a in apps]


@router.post("")
def create_app(
    body: AppIn,
    user: CurrentUser = Depends(require_permission("ads.create")),
    db: Session = Depends(get_db),
):
    """创建 App。系统级（is_system=true）仅 superadmin。"""
    if body.is_system and not getattr(user, 'is_superadmin', False):
        raise HTTPException(403, "仅超管可创建系统级 App")

    app = FbApp(
        tenant_id=None if body.is_system else user.tenant_id,
        name=body.name or None,
        app_id=body.app_id.strip(),
        app_secret_enc=encrypt(body.app_secret.strip()),
        is_system=body.is_system,
        status="active",
        created_by=user.id,
    )
    # 系统行（tenant_id NULL）走 BYPASSRLS 会话——0080 收紧 policy 后 RLS 会话写不进
    if body.is_system:
        sdb = SuperSessionLocal()
        try:
            sdb.add(app)
            sdb.flush()
            sdb.commit()
        finally:
            sdb.close()
    else:
        db.add(app)
        db.flush()
        db.commit()
    from ..core.webhook_config import invalidate_app_secret_cache
    invalidate_app_secret_cache()
    return _app_dict(app)


@router.post("/{app_id}")
def update_app(
    app_id: int,
    body: AppIn,
    user: CurrentUser = Depends(require_permission("ads.create")),
    db: Session = Depends(get_db),
):
    """更新 App。"""
    app = db.query(FbApp).filter(FbApp.id == app_id).first()
    if not app:
        raise HTTPException(404, "App 不存在")
    if app.is_system and not getattr(user, 'is_superadmin', False):
        raise HTTPException(403, "仅超管可编辑系统级 App")
    # 系统行写走 BYPASSRLS 会话（policy 收紧后 RLS 会话 UPDATE 会被 WITH CHECK 拒）
    if app.tenant_id is None:
        sdb = SuperSessionLocal()
        try:
            sys_app = sdb.query(FbApp).filter(FbApp.id == app_id).first()
            sys_app.name = body.name or sys_app.name
            sys_app.app_id = body.app_id.strip()
            if body.app_secret.strip():
                sys_app.app_secret_enc = encrypt(body.app_secret.strip())
            sys_app.is_system = body.is_system if getattr(user, 'is_superadmin', False) else sys_app.is_system
            sys_app.updated_at = datetime.now(timezone.utc)
            sdb.commit()
        finally:
            sdb.close()
    else:
        app.name = body.name or app.name
        app.app_id = body.app_id.strip()
        if body.app_secret.strip():
            app.app_secret_enc = encrypt(body.app_secret.strip())
        app.is_system = body.is_system if getattr(user, 'is_superadmin', False) else app.is_system
        app.updated_at = datetime.now(timezone.utc)
        db.commit()
    from ..core.webhook_config import invalidate_app_secret_cache
    invalidate_app_secret_cache()
    if app.tenant_id is None:
        db.refresh(app)  # 系统行走 sdb 提交，app 是本 session 旧对象——重读拿新值
    return _app_dict(app)


@router.delete("/{app_id}")
def delete_app(
    app_id: int,
    user: CurrentUser = Depends(require_permission("ads.create")),
    db: Session = Depends(get_db),
):
    """删除 App（软删 status=deleted）。"""
    app = db.query(FbApp).filter(FbApp.id == app_id).first()
    if not app:
        raise HTTPException(404, "App 不存在")
    if app.is_system and not getattr(user, 'is_superadmin', False):
        raise HTTPException(403, "仅超管可删除系统级 App")
    # 系统行写走 BYPASSRLS 会话（同上）
    if app.tenant_id is None:
        sdb = SuperSessionLocal()
        try:
            sdb.query(FbApp).filter(FbApp.id == app_id).update({"status": "deleted"})
            sdb.commit()
        finally:
            sdb.close()
    else:
        app.status = "deleted"
        db.commit()
    from ..core.webhook_config import invalidate_app_secret_cache
    invalidate_app_secret_cache()
    return {"deleted": True, "id": app_id}
