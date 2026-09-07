# ④ 真投放v3：换 cred#22（新授权 Fausto）管的账户重试部署
import json, time
import httpx
from app.core.database import SuperSessionLocal
from app.models.auth import User
from app.models.fb import Account, FbCredential
from app.models.fb import AccountFbCredential
from app.core.security import create_access_token
from app.core.encryption import decrypt
from app.core.fb_client import FbClient

TPL = 32

db = SuperSessionLocal()
u = db.query(User).filter(User.email == "seavey@tovaads.com").first()
TOK = create_access_token(user_id=u.id, email=u.email, tenant_id=1, role="owner", is_superadmin=u.is_superadmin)

# cred#22 能管的账户池（绑定 + 候选池）
cand = {r.act_id for r in db.query(Account).filter(Account.fb_credential_id == 22).all()}
for r in db.query(AccountFbCredential).filter(AccountFbCredential.fb_credential_id == 22).all():
    cand.add(db.query(Account).filter(Account.id == r.account_id).first().act_id)
print("cred#22 candidates:", len(cand))

# 找 managed + status=1 + 有写令牌可用的
target = None
for act in cand:
    a = db.query(Account).filter(Account.act_id == act).first()
    if a and a.is_managed and a.account_status == 1 and (a.platform or "fb") == "fb":
        target = a
        print(f"target: {a.act_id} {a.name} status={a.account_status} bind={a.fb_credential_id}")
        break
if not target:
    # 池里没有就直接看 cred#22 用户 /me/adaccounts
    c22 = db.query(FbCredential).filter(FbCredential.id == 22).first()
    fb = FbClient(decrypt(c22.access_token_enc))
    accts = fb.get_ad_accounts()
    print("cred#22 /me/adaccounts:", json.dumps([{k: x.get(k) for k in ('account_id', 'name')} for x in accts[:8]], ensure_ascii=False))
    db.close()
    raise SystemExit("pool empty — 需要把 cred#22 能管的账户导入")
db.close()
assert target, "no target"
ACT = target.act_id

H = {"Authorization": f"Bearer {TOK}"}
BASE = "http://127.0.0.1:8000"

# 拉主页（部署需要）
c22 = FbCredential  # noqa
db = SuperSessionLocal()
from app.core.fb_tokens import cred_for_account_op
cred = cred_for_account_op(db, 1, ACT, "read")
fb = FbClient(decrypt(cred.access_token_enc))
db.close()
pages = fb.get_pages()
page_id = str(pages[0]["id"]) if pages else ""
assert page_id, "no page"
print("page:", page_id, pages[0].get("name"))

# 部署（TRAFFIC 模板已就绪）
r = httpx.post(f"{BASE}/launch-templates/{TPL}/deploy", headers=H,
               json={"items": [{"act_id": ACT, "page_id": page_id, "pixel_id": ""}]}, timeout=60)
print("deploy:", r.status_code, r.text[:150])
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
