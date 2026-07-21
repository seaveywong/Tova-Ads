"""TG webhook：接收 inline keyboard 加白按钮回调 → 加白该广告（1.0 移植）。"""
import hashlib
import hmac
import httpx
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Request, HTTPException, Depends
from ..core.database import SuperSessionLocal
from ..core.encryption import decrypt
from ..core.deps import require_superadmin
from ..models.notify import TenantTgBinding, UserTgBinding
from ..models.guard import GuardAllowance
from ..models.fb import Account

router = APIRouter(prefix="/telegram", tags=["telegram"])


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

        update = await request.json()
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
            json={"url": url, "allowed_updates": ["callback_query"]},
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
