"""FB Webhook 配置（verify_token 存 system_settings，App Secret 从 fb_apps 解密）。

- verify_token：endpoint 级（一个 webhook URL 配一个 token），存 system_settings['fb_webhook']。
  前端系统设置 UI 改 → DB 即时生效，免重启。
- App Secret（HMAC 验签）：复用 fb_apps 表已加密的 app_secret_enc。
  webhook 收到 POST → 逐一解密 active App secret 算 HMAC 比对，哪个验过 = 该 lead 属于那个 App。
  60s 内存缓存（App Secret 改了最多 60s 延迟；fb_apps 增删改时主动调 invalidate_app_secret_cache 立即生效）。
"""
import json, time, logging
from sqlalchemy.orm import Session
from ..models.system import SystemSetting
from ..models.fb_app import FbApp
from ..core.encryption import decrypt
from ..core.config import settings

logger = logging.getLogger("toveads.webhook_config")

DEFAULT_VERIFY_TOKEN = "toveads_webhook_verify"
CACHE_TTL = 60  # App secret 解密缓存秒数
_SECRET_CACHE: dict = {"ts": 0.0, "secrets": []}


def get_webhook_config(db: Session) -> dict:
    """读 webhook 配置。verify_token 从 system_settings 读，fallback 默认值。"""
    row = db.query(SystemSetting).filter(SystemSetting.key == "fb_webhook").first()
    verify_token = DEFAULT_VERIFY_TOKEN
    if row and row.value:
        try:
            cfg = json.loads(row.value)
            vt = cfg.get("verify_token", "").strip()
            if vt:
                verify_token = vt
        except Exception:
            pass
    return {
        "verify_token": verify_token,
        "public_url": f"{settings.public_base_url}/fb/webhook",
    }


def save_webhook_config(db: Session, verify_token: str) -> str:
    """保存 verify_token 到 system_settings。返回最终值（空=恢复默认）。"""
    vt = (verify_token or "").strip()
    val = json.dumps({"verify_token": vt})
    row = db.query(SystemSetting).filter(SystemSetting.key == "fb_webhook").first()
    if row:
        row.value = val
    else:
        db.add(SystemSetting(key="fb_webhook", value=val))
    db.commit()
    return vt or DEFAULT_VERIFY_TOKEN


def get_active_app_secrets(db: Session) -> list[dict]:
    """解密所有 active App 的 secret（HMAC 验签用）。60s TTL 内存缓存。
    returns [{"app_id", "name", "secret"}, ...]
    """
    now = time.time()
    if _SECRET_CACHE["secrets"] and now - _SECRET_CACHE["ts"] < CACHE_TTL:
        return _SECRET_CACHE["secrets"]
    rows = db.query(FbApp).filter(FbApp.status == "active").all()
    out = []
    for r in rows:
        try:
            out.append({"app_id": r.app_id, "name": r.name, "secret": decrypt(r.app_secret_enc)})
        except Exception as e:
            logger.warning(f"[webhook_config] App id={r.id} app_id={r.app_id} secret 解密失败: {e}")
    _SECRET_CACHE["secrets"] = out
    _SECRET_CACHE["ts"] = now
    logger.info(f"[webhook_config] 加载 {len(out)} 个 active App secret")
    return out


def invalidate_app_secret_cache() -> None:
    """fb_apps 增删改后调，立即清缓存（下一笔 webhook 重新解密）。"""
    _SECRET_CACHE["secrets"] = []
    _SECRET_CACHE["ts"] = 0.0
