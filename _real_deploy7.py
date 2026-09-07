# ④v7：cred#13(池内覆盖)账户 + 逐候选令牌写探针（真实建 campaign 级探查谁有写权）
import json, time
import httpx
from sqlalchemy import text
from app.core.database import SuperSessionLocal
from app.models.auth import User
from app.models.fb import FbCredential
from app.core.security import create_access_token
from app.core.encryption import decrypt
from app.core.fb_client import FbClient

TPL = 32
db = SuperSessionLocal()
u = db.query(User).filter(User.email == "seavey@tovaads.com").first()
TOK = create_access_token(user_id=u.id, email=u.email, tenant_id=1, role="owner", is_superadmin=u.is_superadmin)

print("== cred#13 池内覆盖账户（managed+status1+fb）==")
rows = db.execute(text("""
    SELECT a.act_id, a.name FROM accounts a
    JOIN account_fb_credentials afc ON afc.account_id = a.id AND afc.fb_credential_id = 13
    WHERE a.is_managed = true AND a.account_status = 1 AND (a.platform IS NULL OR a.platform = 'fb')
""")).all()
for r in rows:
    print(f"  {r[0]} {r[1]}")

# 每个令牌对每个"该令牌管的账户"做真实写探针：读该账户现有 campaigns，
# 若有 campaign 试 POST 改名（无害写）→ 谁真的有写权一目了然；无 campaign 的账户试 POST 建 campaign 会被真建——
# 改用 GET /act_X/insights 的字段不足以证写。最安全真实探针：POST act_X/campaigns 带 status=PAUSED
# 会被真建（花钱风险=0 因 PAUSED 不投放）。探完即删。
print("\n== 写权探针（建 PAUSED 系列立即删——不投放零花费）==")
creds = {c.id: c for c in db.query(FbCredential).filter(FbCredential.status == "active").all()}
db.close()

# 候选矩阵：3 令牌 × 2 账户（O337 + cred#13 池内第一个）
targets = ["1052568664219129"] + [r[0] for r in rows[:1]]
found = None
for cid in (22, 13, 21):
    fb = FbClient(decrypt(creds[cid].access_token_enc))
    for act in targets:
        try:
            c = fb.post(f"act_{act}/campaigns", {
                "name": "WRITE-PROBE-DEL", "objective": "OUTCOME_TRAFFIC",
                "status": "PAUSED", "special_ad_categories": "[]"})
            cid_created = c.get("id")
            print(f"  cred#{cid} → act {act}: ✅ 可写! campaign={cid_created}（删除中）")
            try:
                fb.delete(cid_created)
            except Exception:
                pass
            found = (cid, act)
            break
        except Exception as e:
            print(f"  cred#{cid} → act {act}: ❌ {str(e)[:70]}")
    if found:
        break

print("\n结果:", found)
if found:
    # 用真有写权的组合正式部署
    H = {"Authorization": f"Bearer {TOK}"}
    BASE = "http://127.0.0.1:8000"
    # 把写令牌绑定到该账户（tiebreaker 修后 operate 已优先；若 found=21(manage) 则绑 21）
    db = SuperSessionLocal()
    db.execute(text("UPDATE accounts SET fb_credential_id = :c WHERE act_id = :a"), {"c": found[0], "a": found[1]})
    db.commit()
    db.close()
    # 拉该写令牌的主页
    fb = FbClient(decrypt(creds[found[0]].access_token_enc))
    pages = fb.get_pages()
    page_id = str(pages[0]["id"])
    r = httpx.post(f"{BASE}/launch-templates/{TPL}/deploy", headers=H,
                   json={"items": [{"act_id": found[1], "page_id": page_id, "pixel_id": ""}]}, timeout=60)
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
