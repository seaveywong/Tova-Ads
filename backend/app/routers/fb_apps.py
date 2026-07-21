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
from ..core.database import Base
from sqlalchemy import Column, BigInteger, Text, Boolean, DateTime, func

router = APIRouter(prefix="/fb/apps", tags=["fb-apps"])


class FbApp(Base):
    __tablename__ = "fb_apps"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger)  # NULL=系统级
    name = Column(Text)
    app_id = Column(Text, nullable=False)
    app_secret_enc = Column(Text, nullable=False)
    is_system = Column(Boolean, default=False)
    status = Column(Text, default="active")
    created_by = Column(BigInteger)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


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
    db.add(app)
    db.flush()
    db.commit()
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
    app.name = body.name or app.name
    app.app_id = body.app_id.strip()
    if body.app_secret.strip():
        app.app_secret_enc = encrypt(body.app_secret.strip())
    app.is_system = body.is_system if getattr(user, 'is_superadmin', False) else app.is_system
    app.updated_at = datetime.now(timezone.utc)
    db.commit()
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
    app.status = "deleted"
    db.commit()
    return {"deleted": True, "id": app_id}
