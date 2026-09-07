# ② webhook 订阅实测 + ③ 巡检速度实测
import time, json
import httpx
from app.core.database import SuperSessionLocal
from app.models.auth import User
from app.core.security import create_access_token

db = SuperSessionLocal()
u = db.query(User).filter(User.email == "seavey@tovaads.com").first()
TOK = create_access_token(user_id=u.id, email=u.email, tenant_id=1, role="owner", is_superadmin=u.is_superadmin)
db.close()
H = {"Authorization": f"Bearer {TOK}"}
BASE = "http://127.0.0.1:8000"

print("== ② webhook 订阅实测（/leads/subscribe）==")
r = httpx.get(f"{BASE}/leads", headers=H, params={"limit": 1}, timeout=30)
print("leads GET status:", r.status_code)
r = httpx.post(f"{BASE}/leads/subscribe", headers=H, json={}, timeout=60)
print("subscribe:", r.status_code, json.dumps(r.json(), ensure_ascii=False)[:400])

print("\n== ③ 巡检速度实测（force + 计时）==")
t0 = time.time()
r = httpx.post(f"{BASE}/guard/inspect?force=true", headers=H, timeout=300)
dt = time.time() - t0
j = r.json() if r.status_code == 200 else {}
print(f"inspect: {r.status_code} 耗时 {dt:.1f}s → {json.dumps(j, ensure_ascii=False)[:200]}")
