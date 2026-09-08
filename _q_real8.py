from app.core.database import SuperSessionLocal as S
from app.models.auth import User
from app.core.security import create_access_token
import httpx, json
db = S()
u = db.query(User).filter(User.email == "seavey@tovaads.com").first()
TOK = create_access_token(user_id=u.id, email=u.email, tenant_id=1, role="owner", is_superadmin=u.is_superadmin)
db.close()
H = {"Authorization": f"Bearer {TOK}"}
ACT = "1609045077342605"
# 用批2新端点给测试账户建像素（免费，同时验证 create-pixel 链路）
r = httpx.post(f"http://127.0.0.1:8000/fb/accounts/{ACT}/create-pixel", headers=H, json={"name": "Tova-RealTest"}, timeout=60)
print("create-pixel:", r.status_code, r.text[:200])
