"""请求/响应 Schema（auth）。"""
from pydantic import BaseModel


class RegisterIn(BaseModel):
    code: str
    email: str
    password: str


class LoginIn(BaseModel):
    email: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str | None = None
    tenant_id: int | None = None
    is_superadmin: bool = False


class UserOut(BaseModel):
    id: int
    email: str
    role: str | None = None
    tenant_id: int | None = None
    is_superadmin: bool = False
    timezone: str = "Asia/Shanghai"
    permissions: list[str] = []
    must_change_password: bool = False


class UpdateTimezoneIn(BaseModel):
    timezone: str


class UpdateEmailIn(BaseModel):
    email: str


class UpdatePasswordIn(BaseModel):
    old_password: str
    new_password: str
