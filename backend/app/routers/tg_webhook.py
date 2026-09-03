"""TG webhook：接收 inline keyboard 加白按钮回调 → 加白该广告（1.0 移植）。"""
import hashlib
import hmac
import logging
import httpx
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import Response
from ..core.database import SuperSessionLocal
from ..core.encryption import decrypt
from ..core.deps import require_superadmin
from ..models.notify import TenantTgBinding, UserTgBinding
from ..models.guard import GuardAllowance
from ..models.fb import Account

router = APIRouter(prefix="/telegram", tags=["telegram"])
logger = logging.getLogger(__name__)


def _webhook_secret(token: str) -> str:
    return hashlib.sha256(f"{token}:tova-tg".encode()).hexdigest()[:32]


def _account_local_today(acc) -> str:
    try:
        return datetime.now(ZoneInfo(acc.timezone_name or "UTC")).strftime("%Y-%m-%d")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _answer_callback(token, callback_id, text, alert=False):
    if not token or not callback_id:
        return
    try:
        httpx.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                   json={"callback_query_id": callback_id, "text": text[:180], "show_alert": alert}, timeout=8)
    except Exception:
        pass


def _edit_reply_markup(token, chat_id, message_id):
    if not token or not chat_id or not message_id:
        return
    try:
        httpx.post(f"https://api.telegram.org/bot{token}/editMessageReplyMarkup",
                   json={"chat_id": chat_id, "message_id": message_id,
                         "reply_markup": {"inline_keyboard": []}}, timeout=8)
    except Exception:
        pass


def _tg_reply(token, chat_id, text):
    try:
        httpx.post(f"https://api.telegram.org/bot{token}/sendMessage",
                   json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=10)
    except Exception:
        pass


@router.post("/webhook/{secret}")
async def tg_webhook(secret: str, request: Request):
    """TG bot webhook：接收 callback_query（加白按钮）→ 加白该广告当日。"""
    db = SuperSessionLocal()
    try:
        # 找匹配 secret 的 bot_token（遍历所有 TG binding）
        all_bindings = list(db.query(TenantTgBinding).all()) + list(db.query(UserTgBinding).all())
        bot_token = None
        for b in all_bindings:
            try:
                token = decrypt(b.bot_token_enc)
            except Exception:
                continue
            if hmac.compare_digest(secret, _webhook_secret(token)):
                bot_token = token
                break
        if not bot_token:
            raise HTTPException(status_code=404, detail="Not found")

        try:
            update = await request.json()
        except Exception:
            return Response(content="Bad JSON", status_code=200)   # TG 对非 2xx 会重试放大——静默吞掉畸形请求

        # ── /start deep link 绑定（用户点 https://t.me/bot?start=<token> → 自动绑定 chat_id）──
        msg = update.get("message") or {}
        text = str(msg.get("text") or "")
        # chat_id/username 提前取：裸 /start（无参数）分支也要用——
        # 曾只在带参分支定义，裸 /start 走到下方 _tg_reply(tg_chat_id) → NameError →
        # webhook 500，TG 侧表现为「点了 START 毫无反应」并堆积重试 update
        tg_chat_id = str((msg.get("chat") or {}).get("id") or "")
        tg_username = (msg.get("from") or {}).get("username") or ""
        if text.startswith("/start "):
            bind_token = text[7:].strip()
            try:
                # 注意：UserTgBinding 用模块级 import（顶部已有）——此处再 import 会把
                # 它遮蔽成函数局部变量，第 65 行的 secret 遍历先于它执行 → UnboundLocalError。
                # 短码（≤64 字符，TG deep-link 上限）优先；旧 JWT 兼容期同判
                from ..core.security import decode_tg_bind_code, decode_token
                decoded = decode_tg_bind_code(bind_token)
                if decoded:
                    user_id, tenant_id = decoded
                else:
                    payload = decode_token(bind_token)
                    if payload.get("type") != "tg_bind":
                        raise ValueError("invalid token type")
                    user_id = int(payload.get("user_id") or 0)
                    tenant_id = payload.get("tenant_id")
                if not user_id or not tenant_id:
                    raise ValueError("invalid token")
                # 用 SuperSessionLocal（BYPASSRLS）——原 get_db() 无租户上下文，
                # INSERT user_tg_bindings 违反 RLS 策略静默失败（绑定 0 行的真因）
                db_session = SuperSessionLocal()
                try:
                    from datetime import datetime, timezone
                    # 多 TG 语义：同 chat_id 幂等刷新，新 chat_id 追加一行（一人多 TG 全收）
                    existing = db_session.query(UserTgBinding).filter(
                        UserTgBinding.tenant_id == tenant_id,
                        UserTgBinding.user_id == user_id,
                        UserTgBinding.chat_id == tg_chat_id,
                    ).first()
                    if existing:
                        existing.bot_token_enc = b.bot_token_enc
                        existing.verified_at = datetime.now(timezone.utc)
                    else:
                        db_session.add(UserTgBinding(
                            tenant_id=tenant_id, user_id=user_id,
                            bot_token_enc=b.bot_token_enc, chat_id=tg_chat_id,
                            verified_at=datetime.now(timezone.utc),
                        ))
                    # 回复说清绑到了哪个平台用户
                    from ..models.auth import User as _U
                    _plat = db_session.query(_U).filter(_U.id == user_id).first()
                    _plat_label = (_plat.email if _plat and _plat.email else f"用户#{user_id}")
                    _n = db_session.query(UserTgBinding).filter(
                        UserTgBinding.tenant_id == tenant_id,
                        UserTgBinding.user_id == user_id).count()
                    db_session.commit()
                    _tg_reply(bot_token, tg_chat_id,
                              f"✅ 绑定成功！已关联平台用户：{_plat_label}\n"
                              f"TG：@{tg_username or tg_chat_id}"
                              + (f"\n（该用户共 {_n} 个 TG，告警将全部发送）" if _n > 1 else ""))
                finally:
                    db_session.close()
            except Exception as e:
                logger.warning(f"[TG] /start 绑定失败 code={bind_token[:10]}… chat={tg_chat_id}: {type(e).__name__}: {e}")
                _tg_reply(bot_token, tg_chat_id,
                          "❌ 绑定码无效或已过期（30 分钟有效）。\n"
                          "请回到系统「设置 → Telegram」重新点击「复制命令」，发送新的 /start 命令。")
            return {"ok": True}

        # 裸 /start（无 deep-link 参数）或普通消息：不再静默——给引导（否则用户以为 bot 死了）
        if text.startswith("/start") or text == "/help":
            _tg_reply(bot_token, tg_chat_id,
                      "👋 我是 Tova Ads 告警 bot。\n"
                      "绑定方法：到系统「设置 → Telegram」点「绑定 Telegram」按钮，"
                      "再用此链接发送 /start 即可完成绑定。")

        callback = update.get("callback_query") or {}
        if not callback:
            return {"ok": True}

        callback_id = callback.get("id")
        message = callback.get("message") or {}
        chat_id = str((message.get("chat") or {}).get("id") or "")
        data = str(callback.get("data") or "")
        parts = data.split("|")
        if len(parts) != 4 or parts[0] != "allow":
            _answer_callback(bot_token, callback_id, "未知操作", alert=True)
            return {"ok": True}

        _, tenant_id_str, act_id, ad_id = parts
        try:
            tenant_id = int(tenant_id_str)
        except ValueError:
            _answer_callback(bot_token, callback_id, "参数错误", alert=True)
            return {"ok": True}

        acc = db.query(Account).filter(
            Account.act_id == act_id, Account.tenant_id == tenant_id).first()
        if not acc:
            _answer_callback(bot_token, callback_id, "账户不存在", alert=True)
            return {"ok": True}

        allowance_date = _account_local_today(acc)
        existing = db.query(GuardAllowance).filter(
            GuardAllowance.tenant_id == tenant_id,
            GuardAllowance.act_id == act_id,
            GuardAllowance.ad_id == ad_id,
            GuardAllowance.allowance_date == allowance_date,
        ).first()
        if existing:
            existing.status = "active"
        else:
            db.add(GuardAllowance(
                tenant_id=tenant_id, act_id=act_id, ad_id=ad_id,
                allowance_date=allowance_date, status="active",
            ))
        db.commit()

        _answer_callback(bot_token, callback_id, f"已加白至 {allowance_date}")
        _edit_reply_markup(bot_token, chat_id, message.get("message_id"))
        _tg_reply(bot_token, chat_id,
                  f"✅ <b>已加白广告</b>\n"
                  f"账户：{_esc(acc.name)}\n"
                  f"广告ID：<code>{ad_id}</code>\n"
                  f"有效期：账户本地日期 {allowance_date}")
        return {"ok": True}
    finally:
        db.close()


def _esc(s):
    from html import escape
    return escape(str(s or ""), quote=False)


@router.post("/setup")
def setup_webhook(user=Depends(require_superadmin)):
    """注册 TG webhook（超管，绑定 callback 到 api.tovaads.com）。"""
    db = SuperSessionLocal()
    try:
        tb = db.query(TenantTgBinding).first()
        if not tb:
            raise HTTPException(400, "未配置 TG bot（tenant_tg_binding 空）")
        token = decrypt(tb.bot_token_enc)
        secret = _webhook_secret(token)
        url = f"https://api.tovaads.com/telegram/webhook/{secret}"
        resp = httpx.post(
            f"https://api.telegram.org/bot{token}/setWebhook",
            json={"url": url, "allowed_updates": ["callback_query", "message"]},  # message：/start 深链绑定依赖
            timeout=15,
        )
        return {"success": resp.json().get("ok"), "webhook_url": url, "telegram": resp.json()}
    finally:
        db.close()


@router.get("/info")
def webhook_info(user=Depends(require_superadmin)):
    """查 TG webhook 状态（超管）。"""
    db = SuperSessionLocal()
    try:
        tb = db.query(TenantTgBinding).first()
        if not tb:
            raise HTTPException(400, "未配置 TG bot")
        token = decrypt(tb.bot_token_enc)
        resp = httpx.get(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=15)
        return {"telegram": resp.json()}
    finally:
        db.close()
