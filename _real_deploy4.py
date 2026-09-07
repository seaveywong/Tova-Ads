# ④v4：诊断写令牌格局 + 切 cred#22 为写令牌重试
import json, time
import httpx
from app.core.database import SuperSessionLocal
from app.models.auth import User
from app.models.fb import Account, FbCredential
from app.core.security import create_access_token
from app.core.encryption import decrypt
from app.core.fb_client import FbClient

ACT = "1052568664219129"  # BSCH-TD-O337
TPL = 32

db = SuperSessionLocal()
print("== 令牌类型/优先级 ==")
for c in db.query(FbCredential).filter(FbCredential.id.in_([13, 21, 22])).all():
    print(f"  cred#{c.id} {c.alias or c.fb_user_name}: token_type={getattr(c,'token_type',None)} priority={getattr(c,'priority',None)} status={c.status}")

u = db.query(User).filter(User.email == "seavey@tovaads.com").first()
TOK = create_access_token(user_id=u.id, email=u.email, tenant_id=1, role="owner", is_superadmin=u.is_superadmin)

# cred#22 直接试写该账户：用 cred#22 的 token 直连 FB 建 campaign（最小写测试）
c22 = db.query(FbCredential).filter(FbCredential.id == 22).first()
fb22 = FbClient(decrypt(c22.access_token_enc))
from sqlalchemy import text
db.execute(text("UPDATE accounts SET fb_credential_id = 22 WHERE act_id = :a"), {"a": ACT})
db.commit()
print(f"\nO337 写令牌已切绑 cred#22")

# 先直连试一次最小写探针（pause 一个不存在的 campaign 无副作用——只看错误类别是 permissions 还是 not_found）
try:
    fb22.post("120000000000000000", {"status": "PAUSED"})
except Exception as e:
    print("cred#22 写探针:", str(e)[:120])
db.close()

H = {"Authorization": f"Bearer {TOK}"}
BASE = "http://127.0.0.1:8000"
r = httpx.post(f"{BASE}/launch-templates/{TPL}/deploy", headers=H,
               json={"items": [{"act_id": ACT, "page_id": "1302132919641404", "pixel_id": ""}]}, timeout=60)
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
