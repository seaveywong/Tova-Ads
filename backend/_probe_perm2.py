"""区分：令牌级问题 vs 账户级墙。每令牌读自己名下(status=1)的 2 个其他账户 + 查 /me/permissions。"""
from app.core.database import SuperSessionLocal
from app.core.encryption import decrypt
from app.models.fb import FbCredential, Account
from app.core.fb_client import FbClient

db = SuperSessionLocal()
creds = db.query(FbCredential).filter(FbCredential.status == "active").all()
for c in creds:
    fb = FbClient(decrypt(c.access_token_enc))
    print(f"\n===== {c.alias} (cred {c.id}) =====")
    try:
        perms = fb.get("me/permissions", {"fields": "permission,status"})
        granted = [p["permission"] for p in perms.get("data", []) if p.get("status") == "granted"]
        print("  granted:", granted)
        print("  ads_read granted:", "ads_read" in granted, "| ads_management:", "ads_management" in granted)
    except Exception as e:
        print("  /me/permissions FAIL:", str(getattr(e, "friendly", e))[:80])
    others = db.query(Account).filter(
        Account.fb_credential_id == c.id, Account.account_status == 1,
        Account.is_managed.is_(True)).limit(2).all()
    for a in others:
        try:
            node = fb.get(f"act_{a.act_id}", {"fields": "account_id,name"})
            print(f"  自有账户 {a.name}: OK")
        except Exception as e:
            print(f"  自有账户 {a.name}: FAIL [{getattr(e, 'category', '?')}] {str(getattr(e, 'friendly', e))[:50]}")
db.close()
