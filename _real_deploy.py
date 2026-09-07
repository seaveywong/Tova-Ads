# ④ 真投放前置：disarm 哨兵 + 建生产测试模板 + preflight
import json, time
import httpx
from app.core.database import SuperSessionLocal
from app.models.auth import User
from app.models.fb import Account
from app.core.security import create_access_token

db = SuperSessionLocal()
u = db.query(User).filter(User.email == "seavey@tovaads.com").first()
TOK = create_access_token(user_id=u.id, email=u.email, tenant_id=1, role="owner", is_superadmin=u.is_superadmin)
db.close()
H = {"Authorization": f"Bearer {TOK}"}
BASE = "http://127.0.0.1:8000"

# 0) 选投放账户：acc_status=1 且有绑定令牌（cred#22/21）的 BSCH-TD-O350
db = SuperSessionLocal()
target = None
for act in ["1076653111436594", "1609045077342605", "1542049827223512"]:
    a = db.query(Account).filter(Account.act_id == act).first()
    if a and a.account_status == 1 and a.is_managed:
        target = a.act_id
        print(f"target: {a.act_id} {a.name} status={a.account_status} cred={a.fb_credential_id}")
        break
db.close()
assert target, "no usable account"

# 1) disarm 全部哨兵（真投放前必须：armed=新广告3分钟内被全停）
r = httpx.post(f"{BASE}/guard/sentinel/disarm", headers=H, json={}, timeout=30)
print("disarm:", r.status_code, r.text[:80])

# 2) 建生产测试模板（asset#2 / $5 USD=500 分 / lp#6 已发布）
tpl = {
    "name": "prod-test-01", "name_prefix": "TovaAds-Test", "platform": "fb",
    "objective": "OUTCOME_SALES", "budget_mode": "ABO", "daily_budget": 500,
    "asset_id": 2, "landing_page_id": 6, "headline": "", "body": "",
}
r = httpx.post(f"{BASE}/launch-templates", headers=H, json=tpl, timeout=30)
print("create tpl:", r.status_code, r.text[:150])
tpl_id = r.json().get("id")
assert tpl_id, r.text

# 3) preflight（自动解析 page/pixel，看缺什么）
r = httpx.post(f"{BASE}/launch-templates/{tpl_id}/preflight", headers=H,
               json={"act_id": target}, timeout=120)
print("preflight:", r.status_code, json.dumps(r.json(), ensure_ascii=False)[:600])
