# smoke: /leads/subscribe 多令牌遍历路径（服务器 mint token，同 _smoke_batch_f 模式）
import json
import httpx
from app.core.database import SuperSessionLocal as _S
from app.models.auth import User
from app.core.security import create_access_token

BASE = "http://127.0.0.1:8000"
_db = _S()
try:
    _u = _db.query(User).filter(User.email == "seavey@tovaads.com").first()
    TOK = create_access_token(user_id=_u.id, email=_u.email, tenant_id=1,
                              role="owner", is_superadmin=_u.is_superadmin)
finally:
    _db.close()
H = {"Authorization": f"Bearer {TOK}"}
assert httpx.get(f"{BASE}/auth/me", headers=H, timeout=30).status_code == 200, "login/mint fail"
print("login OK")

# 订阅端点：多令牌遍历（现役唯一令牌 Fausto=操作员 → 仍 0/13，但每页必须带 error 原因）
r = httpx.post(f"{BASE}/api/leads/subscribe", headers=H, timeout=120).json()
assert isinstance(r.get("pages"), list) and len(r["pages"]) > 0, f"shape bad: {str(r)[:200]}"
fails = [p for p in r["pages"] if p.get("ok") is False]
if fails:
    assert all(p.get("error") for p in fails), "fail page missing error reason"
print(f"PASS subscribe: {r.get('subscribed')}/{r.get('total_pages')} pages, "
      f"fail_reason_sample: {(fails[0]['error'] if fails else '-')[:60]}")

# 退订端点已注册（openapi）
paths = httpx.get(f"{BASE}/openapi.json", timeout=30).json()["paths"]
assert "/api/leads/unsubscribe" in paths, f"unsubscribe not registered: {list(paths)[:5]}..."
print("PASS unsubscribe endpoint registered")
