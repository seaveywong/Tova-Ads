# ④v6：分流修复后重投 O337（写令牌应选 cred#22 Fausto·operate）
import json, time
import httpx
from app.core.database import SuperSessionLocal
from app.models.auth import User
from app.core.security import create_access_token
from app.core.fb_tokens import cred_for_account_op

ACT = "1052568664219129"
TPL = 32

db = SuperSessionLocal()
u = db.query(User).filter(User.email == "seavey@tovaads.com").first()
TOK = create_access_token(user_id=u.id, email=u.email, tenant_id=1, role="owner", is_superadmin=u.is_superadmin)

# 断言：修复后写令牌选的是 22（operate）
w = cred_for_account_op(db, 1, ACT, "write")
print(f"写令牌选择: cred#{w.id} {w.alias} type={w.token_type}")
assert w.id == 22, f"仍选 {w.id}——tiebreaker 未生效"
db.close()

H = {"Authorization": f"Bearer {TOK}"}
BASE = "http://127.0.0.1:8000"
# 用写令牌(cred#22)自己管理的主页（曾硬编码 cred#21 的主页 → "令牌不管该页"）
from app.core.encryption import decrypt
from app.core.fb_client import FbClient
db2 = SuperSessionLocal()
from app.models.fb import FbCredential as FC
c22 = db2.query(FC).filter(FC.id == 22).first()
pages22 = [{"id": "1302132919641404", "name": "Bennett Gibbonsrwx(BSCH账户绑定主页)"}]  # 账户可推广对象用账户绑定页，非令牌自己的页
db2.close()
print("cred#22 pages:", json.dumps([{k: p.get(k) for k in ("id", "name")} for p in pages22[:5]], ensure_ascii=False))
page_id = str(pages22[0]["id"]) if pages22 else ""
assert page_id, "cred#22 no pages"
r = httpx.post(f"{BASE}/launch-templates/{TPL}/deploy", headers=H,
               json={"items": [{"act_id": ACT, "page_id": page_id, "pixel_id": ""}]}, timeout=60)
print("deploy:", r.status_code, r.text[:120])
job_id = r.json().get("job_id")
final = None
for i in range(90):
    time.sleep(5)
    j = httpx.get(f"{BASE}/launch-templates/jobs/{job_id}", headers=H, timeout=30).json()
    if j.get("status") in ("completed", "partial_failed", "failed"):
        final = j
        break
    if i % 4 == 0:
        print(f"  poll {i*5}s: {j.get('status')}")
print("FINAL:", json.dumps(final, ensure_ascii=False)[:900])
