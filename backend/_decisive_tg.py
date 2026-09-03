"""决定性测试：真实 bind_token + 用户真实 chat_id 打 webhook → bot 应回复用户 TG 并完成绑定。"""
import json
import httpx
from app.core.database import SuperSessionLocal
from app.core.encryption import decrypt
from app.core.security import create_access_token
from app.models.notify import TenantTgBinding, UserTgBinding
from app.models.auth import User

db = SuperSessionLocal()
# 找超管（登录的那个）
u = db.query(User).filter(User.is_superadmin == True).first()  # noqa: E712
if not u:
    u = db.query(User).order_by(User.id).first()
from app.models.auth import TenantMembership
_m = db.query(TenantMembership).filter(TenantMembership.user_id == u.id).first()
tb = db.query(TenantTgBinding).filter(TenantTgBinding.tenant_id == _m.tenant_id).first()
tok = decrypt(tb.bot_token_enc)
chat_id = tb.chat_id  # 用户真实 TG chat（租户级绑定的那个）
print(f"平台用户: {u.email} (id={u.id}, tenant={_m.tenant_id}) → TG chat {chat_id}")

# 生成真 bind token（照 /tg/bind-link 逻辑）
bind_token = create_access_token(
    user_id=u.id, email=u.email,
    tenant_id=_m.tenant_id, role=(_m.role or "owner"),
    is_superadmin=bool(u.is_superadmin),
    token_use="tg_bind", expire_min=10,
)
# webhook secret（tg_webhook._webhook_secret）
from app.routers.tg_webhook import _webhook_secret
secret = _webhook_secret(tok)

# 打本地 webhook（模拟 TG 投递一条 /start 深链消息）
payload = {"message": {
    "text": f"/start {bind_token}",
    "chat": {"id": int(chat_id)},
    "from": {"id": int(chat_id), "username": "seavey"},
}}
r = httpx.post(f"http://127.0.0.1:8000/telegram/webhook/{secret}", json=payload, timeout=30)
print(f"webhook 响应: HTTP {r.status_code} {r.text[:80]}")

# 验证绑定行
b = db.query(UserTgBinding).filter(UserTgBinding.user_id == u.id).all()
print(f"绑定行: {len(b)} 条 chat={[x.chat_id for x in b]}")
db.close()
print("\n→ 你的 TG 现在应该收到了「✅ 绑定成功！已关联平台用户」消息——收到即整链路通")
