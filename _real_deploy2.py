# ④ 真投放第二段v2：直连FB拉像素/主页 → 补模板 → preflight → deploy → 轮询
import json, time
import httpx
from app.core.database import SuperSessionLocal
from app.models.auth import User
from app.models.fb import Account
from app.core.security import create_access_token
from app.core.encryption import decrypt
from app.core.fb_client import FbClient
from app.core.fb_tokens import cred_for_account_op

ACT = "1076653111436594"  # BSCH-TD-O350
TPL = 32

db = SuperSessionLocal()
u = db.query(User).filter(User.email == "seavey@tovaads.com").first()
TOK = create_access_token(user_id=u.id, email=u.email, tenant_id=1, role="owner", is_superadmin=u.is_superadmin)
acc = db.query(Account).filter(Account.act_id == ACT).first()
cred = cred_for_account_op(db, 1, ACT, "read")
fb = FbClient(decrypt(cred.access_token_enc))
db.close()
H = {"Authorization": f"Bearer {TOK}"}
BASE = "http://127.0.0.1:8000"

# 1) 直连 FB 拉该账户像素 + 主页
px = fb.get_pixels(ACT)
print("pixels:", json.dumps(px, ensure_ascii=False)[:200])
pixel_id = str(px[0]["id"]) if px else ""
if not pixel_id:
    print("!! 该账户无像素 → 切 TRAFFIC 目标（LINK_CLICKS 无需 pixel，验证建链最短路径）")

pages = fb.get_pages()   # 系统同款：list_credential_pages 的实现（me/accounts）
print("pages:", json.dumps(pages, ensure_ascii=False)[:200])
page_id = str(pages[0]["id"]) if pages else ""
assert page_id, "no page on account"

# 2) 补模板 pixel + page
objective = "OUTCOME_SALES" if pixel_id else "OUTCOME_TRAFFIC"
opt_goal = "" if pixel_id else "LINK_CLICKS"
tpl_upd = {
    "name": "prod-test-01", "name_prefix": "TovaAds-Test", "platform": "fb",
    "objective": objective, "optimization_goal": opt_goal, "billing_event": "IMPRESSIONS" if opt_goal else "",
    "destination_type": "WEBSITE",
    "budget_mode": "ABO", "daily_budget": 500,
    "asset_id": 2, "landing_page_id": 6, "pixel_id": pixel_id, "page_id": page_id,
    "headline": "", "body": "",
}
print("objective:", objective)
r = httpx.put(f"{BASE}/launch-templates/{TPL}", headers=H, json=tpl_upd, timeout=30)
print("update tpl:", r.status_code)

# 3) preflight
r = httpx.post(f"{BASE}/launch-templates/{TPL}/preflight", headers=H, json={"act_id": ACT}, timeout=120)
print("preflight:", r.status_code, json.dumps(r.json(), ensure_ascii=False)[:300])
assert r.status_code == 200, "preflight fail"

# 4) DEPLOY（真实花钱：1账户×1系列×$5/天）
r = httpx.post(f"{BASE}/launch-templates/{TPL}/deploy", headers=H,
               json={"items": [{"act_id": ACT, "page_id": page_id, "pixel_id": pixel_id}]}, timeout=60)
print("deploy:", r.status_code, r.text[:200])
job_id = r.json().get("job_id")
assert job_id, r.text

# 5) 轮询到终态
final = None
for i in range(90):
    time.sleep(5)
    r = httpx.get(f"{BASE}/launch-templates/jobs/{job_id}", headers=H, timeout=30)
    j = r.json()
    if j.get("status") in ("completed", "partial_failed", "failed"):
        final = j
        break
    if i % 4 == 0:
        print(f"  poll {i*5}s: {j.get('status')} ok={j.get('succeeded')} fail={j.get('failed')}")
print("FINAL:", json.dumps(final, ensure_ascii=False)[:900])
