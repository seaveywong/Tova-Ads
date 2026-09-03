"""密码哈希 + JWT 签发/校验。"""
from datetime import datetime, timedelta, timezone
import bcrypt
from jose import jwt
from .config import settings


def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(p: str, h: str) -> bool:
    return bcrypt.checkpw(p.encode("utf-8"), h.encode("utf-8"))


def encode_tg_bind_code(user_id: int, tenant_id: int, expire_min: int = 15) -> str:
    """TG deep-link 短码：27 字符（struct 12B + HMAC 8B → base64url）。

    Telegram ?start= 参数上限 64 字符——JWT（200+ 字符）会被 TG 静默丢弃，
    START 按钮发不出命令（绑定"没反应"的根因）。短码自含 user/tenant/过期 + 防篡改签名。
    """
    import base64
    import hashlib
    import hmac as _hmac
    import struct
    import time as _time
    payload = struct.pack("!III", user_id, tenant_id, int(_time.time()) + expire_min * 60)
    sig = _hmac.new(settings.jwt_secret.encode(), payload, hashlib.sha256).digest()[:8]
    return base64.urlsafe_b64encode(payload + sig).decode().rstrip("=")


def decode_tg_bind_code(code: str) -> tuple[int, int] | None:
    """解析 TG 绑定短码 → (user_id, tenant_id)；过期/签名不符 → None。"""
    import base64
    import hashlib
    import hmac as _hmac
    import struct
    import time as _time
    try:
        raw = base64.urlsafe_b64decode(code + "=" * (-len(code) % 4))
        if len(raw) != 20:
            return None
        payload, sig = raw[:12], raw[12:]
        expect = _hmac.new(settings.jwt_secret.encode(), payload, hashlib.sha256).digest()[:8]
        if not _hmac.compare_digest(sig, expect):
            return None
        user_id, tenant_id, exp = struct.unpack("!III", payload)
        if _time.time() > exp:
            return None
        return user_id, tenant_id
    except Exception:
        return None


def create_access_token(*, user_id: int, email: str, tenant_id: int | None, role: str | None,
                        is_superadmin: bool = False, token_use: str = "access",
                        expire_min: int | None = None) -> str:
    """token_use: access=普通会话；tg_bind=TG 绑定 deep-link 专用（10 分钟一次性，泄露面窄）。"""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": email,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "is_superadmin": is_superadmin,
        "type": token_use,
        "iat": now,
        "exp": now + timedelta(minutes=expire_min or settings.jwt_expire_min),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_alg)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_alg])


def renew_token(token: str) -> str | None:
    """滑动续期：解码现有 token → 用原 claims + 新 exp 重新签发。失败返 None（无效/过期不续）。

    只续 access（tg_bind 等专用短效 token 不续期）。"""
    try:
        p = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_alg])
    except Exception:
        return None
    if p.get("type") != "access":
        return None
    now = datetime.now(timezone.utc)
    p["iat"] = now
    p["exp"] = now + timedelta(minutes=settings.jwt_expire_min)
    return jwt.encode(p, settings.jwt_secret, algorithm=settings.jwt_alg)
