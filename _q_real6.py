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
ok = [a for a in accs if not a.get("no_token") and a.get("is_managed") and (a.get("account_status") == 1)]
for a in ok[:6]:
    print("act:", a.get("act_id"), "name:", a.get("name"), "cred:", a.get("fb_credential_id"), "cur:", a.get("currency"))
print("total_ok:", len(ok))
