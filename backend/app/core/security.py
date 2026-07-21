"""密码哈希 + JWT 签发/校验。"""
from datetime import datetime, timedelta, timezone
import bcrypt
from jose import jwt
from .config import settings


def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(p: str, h: str) -> bool:
    return bcrypt.checkpw(p.encode("utf-8"), h.encode("utf-8"))


def create_access_token(*, user_id: int, email: str, tenant_id: int | None, role: str | None, is_superadmin: bool = False) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": email,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "is_superadmin": is_superadmin,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_min),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_alg)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_alg])


def renew_token(token: str) -> str | None:
    """滑动续期：解码现有 token → 用原 claims + 新 exp 重新签发。失败返 None（无效/过期不续）。"""
    try:
        p = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_alg])
    except Exception:
        return None
    now = datetime.now(timezone.utc)
    p["iat"] = now
    p["exp"] = now + timedelta(minutes=settings.jwt_expire_min)
    return jwt.encode(p, settings.jwt_secret, algorithm=settings.jwt_alg)
