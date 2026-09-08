from app.core.database import SuperSessionLocal as S
from app.models.auth import User
from app.core.security import create_access_token
import httpx, json
db = S()
u = db.query(User).filter(User.email == "seavey@tovaads.com").first()
TOK = create_access_token(user_id=u.id, email=u.email, tenant_id=1, role="owner", is_superadmin=u.is_superadmin)
db.close()
H = {"Authorization": f"Bearer {TOK}"}
r = httpx.get("http://127.0.0.1:8000/fb/accounts", headers=H, timeout=30)
accs = r.json() if isinstance(r.json(), list) else (r.json().get("accounts") or [])
acc = next((a for a in accs if str(a.get("act_id", "")).endswith("1338258757886709") or a.get("act_id") == "1338258757886709"), None)
print("acc keys:", sorted(acc.keys())[:20] if acc else None)
if acc:
    print("act:", acc.get("act_id"), "cred:", acc.get("fb_credential_id"), "no_token:", acc.get("no_token"), "managed:", acc.get("is_managed"))
