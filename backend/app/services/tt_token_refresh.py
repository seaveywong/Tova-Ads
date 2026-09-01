"""TikTok 令牌自动续期（cron，每 6h）。

TT 与 FB 的关键差异：access_token 24h 过期 + refresh_token 365d 且**刷新即轮换**
（每次刷新返回全新 refresh_token，旧的立即失效）→ 必须把新 access+refresh+expires
在同一次 commit 里原子写回；写回失败时 DB 里的旧 refresh_token 已被 TK 作废，
凭证只能走重新授权（连败 3 次 → status='expired' + 通知）。

职责：
1. expires_at < now+12h 的 active 凭证 → 刷新（轮换原子写回）
2. refresh_expires_at < now+30d → owner 通知「需重新授权」（dedup 24h/凭证）
3. 刷新失败 consecutive_fails+1；refresh_token 无效 → status='invalid'；
   连续 3 次 → status='expired'（均发同一 tt_token_expiring 事件）
"""
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..core.database import SuperSessionLocal, acquire_run_lock, release_run_lock
from ..core.encryption import decrypt, encrypt
from ..core.i18n import tenant_locale
from ..core.log_utils import write_log, new_trace_id
from ..core.notify_utils import emit_notification, dedup_recent
from ..core.tt_client import TtClient, TtApiError

logger = logging.getLogger("toveads.tt_refresh")

LOCK_KEY = 114                     # advisory lock 号（101-113 已占用）
ACCESS_MARGIN = timedelta(hours=12)    # access 剩 <12h 就刷新（cron 6h 一轮，双保险）
REAUTH_WARN = timedelta(days=30)       # refresh 剩 <30d 告警重新授权
FAIL_LIMIT = 3                         # 连续失败 N 次 → expired
DEDUP_MIN = 24 * 60                    # 重新授权告警去重窗口（24h/凭证）


def resolve_tt_app(db: Session, app_id: str = "") -> tuple[str, str] | None:
    """TT App 配置：系统级 tt_apps（tenant_id NULL）优先，环境变量兜底。
    app_id 传入时按凭证的 app_id 精确匹配（多 App 场景 token 刷新必须用自己的
    secret——app_id/secret 不匹配会 refresh 失败）；不传=第一行（兼容旧行为）。
    返回 (app_id, secret) 或 None。平台级配置用 SuperSessionLocal 读（RLS 不挡系统行）。"""
    from ..models.tt import TtApp
    q = db.query(TtApp).filter(TtApp.tenant_id.is_(None), TtApp.is_system.is_(True))
    if app_id:
        q = q.filter(TtApp.app_id == app_id)
    app = q.order_by(TtApp.id).first()
    if app and app.app_id and app.app_secret_enc:
        try:
            return app.app_id, decrypt(app.app_secret_enc)
        except Exception as e:
            logger.error(f"[TT] 系统级 App secret 解密失败: {e}")
            return None
    # TODO: 正式化为 settings.tt_app_id/tt_app_secret（config.py 配置项归 P0/配置批）
    env_id = (os.environ.get("TT_APP_ID") or "").strip()
    secret = (os.environ.get("TT_APP_SECRET") or "").strip()
    if env_id and secret and (not app_id or env_id == app_id):
        return env_id, secret
    return None


def _notify_reauth(db: Session, cred, tenant_id: int, trace_id: str,
                   days_left: int | None = None) -> None:
    """「TikTok 令牌需重新授权」owner 通知（dedup 24h/凭证，action_logs 维度）。
    days_left=None 表示 refresh_token 已失效（invalid/expired 路径）。"""
    if dedup_recent(db, tenant_id, "tt_token_expiring", target_id=str(cred.id),
                    cooldown_min=DEDUP_MIN):
        return
    loc = tenant_locale(db, tenant_id)
    alias = cred.alias or (f"TikTok {cred.advertiser_id}" if cred.advertiser_id else f"#{cred.id}")
    if loc == "en":
        if days_left is None:
            title, body = ("TikTok Token Re-authorization Required",
                           "Token: <b>{a}</b>\nStatus: the refresh token is no longer valid, "
                           "auto-renewal has stopped\nAction: go to Tokens → TikTok and click "
                           "Re-authorize".format(a=alias))
        else:
            title, body = ("TikTok Token Re-authorization Required",
                           "Token: <b>{a}</b>\nThe refresh token expires in {d} days; once it "
                           "expires the token cannot renew automatically.\nAction: go to Tokens "
                           "→ TikTok and click Re-authorize beforehand.".format(a=alias, d=days_left))
    else:
        if days_left is None:
            title, body = ("TikTok 令牌需重新授权",
                           f"令牌：<b>{alias}</b>\n状态：刷新令牌已失效，自动续期已停止\n"
                           f"处理：到令牌管理 → TikTok 点「重新授权」")
        else:
            title, body = ("TikTok 令牌需重新授权",
                           f"令牌：<b>{alias}</b>\n刷新令牌剩余 {days_left} 天，"
                           f"过期后将无法自动续期。\n处理：提前到令牌管理 → TikTok 点「重新授权」。")
    emit_notification(db, tenant_id=tenant_id, level="warning",
                      event_type="tt_token_expiring", trace_id=trace_id,
                      title=title, body=body, roles=["owner"],
                      target_type="tt_credential", target_id=str(cred.id))
    write_log(db, tenant_id=tenant_id, trace_id=trace_id, actor_type="system",
              target_type="tt_credential", target_id=str(cred.id),
              action_type="tt_token_expiring", source="tt_token_refresh",
              result="alerted",
              trigger_detail=f"cred={cred.id} days_left={days_left}")
    db.commit()


def refresh_credential(db: Session, cred, app_id: str, secret: str) -> dict:
    """刷新单个凭证并原子写回（新 access+refresh+expires 一次 commit）。

    TK 刷新即轮换：API 成功的瞬间 DB 里的旧 refresh_token 已作废——
    本函数从 API 返回到 commit 之间不做任何其他写操作，失败即 rollback，
    把「半新半旧」窗口压到最小；commit 失败的凭证下一轮刷新必失败（40106），
    走连败 → expired → 重新授权的兜底链路。
    """
    data = TtClient.refresh_access_token(app_id, secret, decrypt(cred.refresh_token_enc))
    new_access = data.get("access_token") or ""
    new_refresh = data.get("refresh_token") or ""
    if not new_access or not new_refresh:
        raise TtApiError("unknown", "刷新响应缺少 token 字段", data, 0)
    now = datetime.now(timezone.utc)
    try:
        access_ttl = int(data.get("expires_in") or 86400)
    except (TypeError, ValueError):
        access_ttl = 86400
    try:
        refresh_ttl = int(data.get("refresh_token_expires_in") or 31536000)
    except (TypeError, ValueError):
        refresh_ttl = 31536000
    cred.access_token_enc = encrypt(new_access)
    cred.refresh_token_enc = encrypt(new_refresh)
    cred.expires_at = now + timedelta(seconds=access_ttl)
    cred.refresh_expires_at = now + timedelta(seconds=refresh_ttl)
    cred.last_refreshed_at = now
    cred.consecutive_fails = 0
    cred.status = "active"
    db.commit()
    return {"ok": True, "cred_id": cred.id}


def _fail_credential(db: Session, cred, tenant_id: int, trace_id: str,
                     err: TtApiError) -> None:
    """刷新失败处理：rollback 后计数/降级 + 触发重新授权通知。"""
    db.rollback()
    cred.consecutive_fails = (cred.consecutive_fails or 0) + 1
    if err.category == "refresh_invalid":
        cred.status = "invalid"          # refresh_token 已废，重试无意义
    elif cred.consecutive_fails >= FAIL_LIMIT:
        cred.status = "expired"
    db.commit()
    if err.category == "refresh_invalid" or cred.status == "expired":
        _notify_reauth(db, cred, tenant_id, trace_id, days_left=None)


def run_tt_token_refresh():
    """定时入口（main.py 挂 6h interval）。advisory lock 114 防多 worker 重复。"""
    lock = acquire_run_lock(LOCK_KEY)
    if not lock:
        return {"skipped": "lock_busy"}
    db = SuperSessionLocal()
    trace_id = new_trace_id()
    refreshed = failed = warned = 0
    try:
        from ..models.tt import TtCredential
        app_cfg = resolve_tt_app(db)
        if not app_cfg:
            logger.warning("[TTRefresh] 未配置 TikTok App（tt_apps 系统级 / TT_APP_ID 环境变量），跳过本轮")
            return {"skipped": "no_app"}
        app_id, secret = app_cfg

        creds = db.query(TtCredential).filter(TtCredential.status == "active").all()
        now = datetime.now(timezone.utc)
        for cred in creds:
            # ① refresh_token 临期告警（与是否刷新无关，独立判断）
            if cred.refresh_expires_at:
                days_left = (cred.refresh_expires_at - now).days
                if days_left < 30:
                    _notify_reauth(db, cred, cred.tenant_id, trace_id, days_left=max(days_left, 0))
                    warned += 1
            # ② access_token 临期 → 刷新（expires_at 为空也刷，拿到准确过期时间）
            if cred.refresh_token_enc and (
                cred.expires_at is None or cred.expires_at < now + ACCESS_MARGIN
            ):
                # 多 App 场景按凭证自己的 app_id 找 secret（不匹配的 refresh 必失败）；
                # 凭证无 app_id（旧行）或 app 已删 → 回退第一行
                cfg = resolve_tt_app(db, (cred.app_id or "").strip()) or app_cfg
                if not cfg:
                    logger.warning(f"[TTRefresh] 凭证 {cred.id} 的 App（app_id={cred.app_id}）未配置，跳过刷新")
                    continue
                try:
                    refresh_credential(db, cred, cfg[0], cfg[1])
                    refreshed += 1
                    logger.info(f"[TTRefresh] 凭证 {cred.id} 已刷新轮换 (trace={trace_id})")
                except TtApiError as e:
                    _fail_credential(db, cred, cred.tenant_id, trace_id, e)
                    failed += 1
                    logger.warning(f"[TTRefresh] 凭证 {cred.id} 刷新失败: {e.category} {e.friendly}")
                except Exception as e:
                    db.rollback()
                    logger.error(f"[TTRefresh] 凭证 {cred.id} 异常: {e}", exc_info=True)
                    failed += 1

        logger.info(f"[TTRefresh] 完成: 刷新 {refreshed} / 失败 {failed} / 临期告警 {warned} (trace={trace_id})")
        return {"refreshed": refreshed, "failed": failed, "warned": warned, "trace_id": trace_id}
    except Exception as e:
        logger.error(f"[TTRefresh] 异常: {e}", exc_info=True)
        return {"error": str(e)}
    finally:
        db.close()
        release_run_lock(lock, LOCK_KEY)
