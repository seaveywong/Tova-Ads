from app.core.database import SuperSessionLocal as S
from app.models.auth import User
from app.core.security import create_access_token
import httpx, json
db = S()
u = db.query(User).filter(User.email == "seavey@tovaads.com").first()
TOK = create_access_token(user_id=u.id, email=u.email, tenant_id=1, role="owner", is_superadmin=u.is_superadmin)
db.close()
H = {"Authorization": f"Bearer {TOK}"}
ACT = "1609045077342605"  # BSCH-TD-O322
# 1. 账户像素
r = httpx.get(f"http://127.0.0.1:8000/fb/credentials/25/pixels", headers=H, timeout=60)
pix = r.json() if isinstance(r.json(), list) else []
mine = [p for p in pix if p.get("account_id", "").endswith(ACT) or True]
print("pixels(first3):", json.dumps(pix[:3], ensure_ascii=False)[:400])
# 2. 该令牌主页（取一个能发帖的）
r2 = httpx.get(f"http://127.0.0.1:8000/fb/credentials/25/pages", headers=H, timeout=60)
pages = r2.json() if isinstance(r2.json(), list) else []
for p in pages[:5]:
    print("page:", p.get("id"), p.get("name"), "can_post:", p.get("can_post"), "tasks:", p.get("tasks"))
