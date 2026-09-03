"""诊断 TG bot webhook：getWebhookInfo + 最近 getUpdates。"""
import json
import httpx
from app.core.database import SuperSessionLocal
from app.core.encryption import decrypt
from app.models.notify import TenantTgBinding

db = SuperSessionLocal()
tb = db.query(TenantTgBinding).filter(TenantTgBinding.tenant_id == 1).first()
db.close()
tok = decrypt(tb.bot_token_enc)
print(f"chat_id={tb.chat_id}")

r = httpx.get(f"https://api.telegram.org/bot{tok}/getWebhookInfo", timeout=15).json()
print("getWebhookInfo:", json.dumps(r.get("result", {}), ensure_ascii=False, indent=1))

# webhook 没设的话，看积压的 updates（含用户发的 /start）
if not r.get("result", {}).get("url"):
    u = httpx.get(f"https://api.telegram.org/bot{tok}/getUpdates", params={"limit": 5}, timeout=15).json()
    for up in (u.get("result") or [])[:5]:
        msg = up.get("message") or {}
        print(f"  pending update: chat={msg.get('chat', {}).get('id')} text={str(msg.get('text'))[:50]}")
else:
    print("（webhook 已设，看 pending_update_count）")
