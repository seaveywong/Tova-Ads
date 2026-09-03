"""诊断导入令牌两问题：①/me 返回的 ID 与 DB 存的 ②逐个资产调用的真实 FB 响应。"""
import json
from app.core.database import SuperSessionLocal
from app.core.encryption import decrypt
from app.core.fb_client import FbClient
from app.models.fb import FbCredential

db = SuperSessionLocal()
cred = db.query(FbCredential).order_by(FbCredential.id.desc()).first()
print(f"最新凭证 #{cred.id}: fb_user_id={cred.fb_user_id} alias={cred.alias} status={cred.status}")
tok = decrypt(cred.access_token_enc)
fb = FbClient(tok)

print("\n═══ /me（应用作用域 ID 实测）═══")
me = fb.me()
print(f"  /me → id={me.get('id')} name={me.get('name')}")
print(f"  DB 存的 fb_user_id={cred.fb_user_id} → {'一致' if me.get('id') == cred.fb_user_id else '不一致!'}")
print(f"  末10位（卡片显示值）= {str(cred.fb_user_id)[-10:]}")

print("\n═══ 资产逐项实测 ═══")
import httpx
G = "https://graph.facebook.com/v25.0"


def raw(path, params):
    r = httpx.get(f"{G}/{path}", params={**params, "access_token": tok}, timeout=30)
    b = r.json()
    ok = b.get("data") is not None or isinstance(b, list) or (isinstance(b, dict) and "id" in b)
    errs = b.get("error", {})
    n = len(b.get("data", [])) if isinstance(b.get("data"), list) else "-"
    print(f"  {path:36} fields={params.get('fields','')[:40]:40} → {'OK ' + str(n) + ' 条' if not errs else 'ERR code=' + str(errs.get('code')) + ' msg=' + str(errs.get('message'))[:80]}")
    return b


raw("me/adaccounts", {"fields": "account_id,name,currency,account_status,spend_cap,amount_spent,offset_info", "limit": 100})
raw("me/adaccounts", {"fields": "account_id,name,currency,account_status,spend_cap,amount_spent", "limit": 100})
raw("me/accounts", {"fields": "id,name,category,can_post,fan_count,tasks", "limit": 100})
raw("me/accounts", {"fields": "id,name,category,fan_count", "limit": 100})
raw("me/businesses", {"fields": "id,name,permitted_tasks", "limit": 100})
db.close()
