# ④v5：查池排序真相 + cred#13(老操作号·历史投放成功)的账户部署
import json, time
import httpx
from sqlalchemy import text
from app.core.database import SuperSessionLocal
from app.models.auth import User
from app.models.fb import Account, FbCredential, AccountFbCredential
from app.core.security import create_access_token

TPL = 32
db = SuperSessionLocal()

print("== O337 候选池真实排序（写=priority 取第一）==")
rows = db.execute(text("""
    SELECT afc.priority, afc.status AS pool_status, fc.id, fc.alias, fc.token_type, fc.status
    FROM account_fb_credentials afc JOIN fb_credentials fc ON fc.id = afc.fb_credential_id
    JOIN accounts a ON a.id = afc.account_id
    WHERE a.act_id = '1052568664219129'
    ORDER BY afc.priority NULLS LAST, fc.id
""")).all()
for r in rows:
    print(f"  priority={r[0]} pool_status={r[1]} cred#{r[2]} {r[3]} type={r[4]} status={r[5]}")
if not rows:
    print("  (池空——写走 accounts.fb_credential_id 回退)")

u = db.query(User).filter(User.email == "seavey@tovaads.com").first()
TOK = create_access_token(user_id=u.id, email=u.email, tenant_id=1, role="owner", is_superadmin=u.is_superadmin)

# cred#13（Xinwei·operate·2026-08 真实投放成功过）绑定/池内 managed+status1 账户
print("\n== cred#13 Xinwei 的账户 ==")
acts13 = db.execute(text("""
    SELECT a.act_id, a.name, a.account_status FROM accounts a
    WHERE a.fb_credential_id = 13 AND a.is_managed = true AND a.account_status = 1
      AND (a.platform IS NULL OR a.platform = 'fb')
""")).all()
for r in acts13:
    print(f"  {r[0]} {r[1]}")
target = acts13[0][0] if acts13 else None
db.close()
assert target, "cred#13 no account"

H = {"Authorization": f"Bearer {TOK}"}
BASE = "http://127.0.0.1:8000"
print(f"\n== 部署到 {target}（TRAFFIC/$5）==")
r = httpx.post(f"{BASE}/launch-templates/{TPL}/deploy", headers=H,
               json={"items": [{"act_id": target, "page_id": "1302132919641404", "pixel_id": ""}]}, timeout=60)
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
