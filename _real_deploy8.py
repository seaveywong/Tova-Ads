# ④v8：用户指定账户 Roly-V21(act 1338258757886709) 真投放
# 策略：查该账户绑定/池令牌 → 探针找有写权的令牌 → 用其匹配的主页部署 → 轮询到终态 → FB核实
import json, time
import httpx
from sqlalchemy import text
from app.core.database import SuperSessionLocal
from app.models.auth import User
from app.models.fb import FbCredential, Account
from app.core.security import create_access_token
from app.core.encryption import decrypt
from app.core.fb_client import FbClient, FbApiError
from app.core.fb_tokens import cred_for_account_op
from app.core.ad_builder import build_campaign

ACT = "1338258757886709"
TPL = 32
db = SuperSessionLocal()
u = db.query(User).filter(User.email == "seavey@tovaads.com").first()
TOK = create_access_token(user_id=u.id, email=u.email, tenant_id=1, role="owner", is_superadmin=u.is_superadmin)

acc = db.query(Account).filter(Account.act_id == ACT).first()
print(f"账户: {acc.name if acc else '?'} status={acc.account_status if acc else '?'} managed={acc.is_managed if acc else '?'} bind_cred={acc.fb_credential_id if acc else '?'}")
if not acc or not acc.is_managed:
    print("!! 未纳管——需先导入")
    db.close()
    raise SystemExit

print("\n== 该账户候选池 ==")
pool = db.execute(text("""
    SELECT afc.priority, fc.id, fc.alias, fc.token_type FROM account_fb_credentials afc
    JOIN fb_credentials fc ON fc.id = afc.fb_credential_id
    JOIN accounts a ON a.id = afc.account_id WHERE a.act_id = :a
    ORDER BY afc.priority NULLS LAST, fc.id
"""), {"a": ACT}).all()
for r in pool:
    print(f"  priority={r[0]} cred#{r[1]} {r[2]} type={r[3]}")
pool_ids = [r[1] for r in pool] or ([acc.fb_credential_id] if acc.fb_credential_id else [])

# 写权探针（建 PAUSED campaign 立即删——零花费）逐令牌
print("\n== 写权探针 ==")
writer = None
for cid in pool_ids:
    c = db.query(FbCredential).filter(FbCredential.id == cid, FbCredential.status == "active").first()
    if not c:
        continue
    fb = FbClient(decrypt(c.access_token_enc))
    try:
        cp = build_campaign(name="PROBE-W", objective="OUTCOME_TRAFFIC")
        cp["status"] = "PAUSED"
        r = fb.post(f"act_{ACT}/campaigns", cp)
        print(f"  cred#{cid} {c.alias}: ✅ 有写权 campaign={r['id']}")
        try:
            fb.delete(r["id"])
        except Exception:
            pass
        writer = fb
        writer_cid = cid
        break
    except FbApiError as e:
        print(f"  cred#{cid} {c.alias}: ❌ {str(e)[:70]}")
assert writer, "该账户没有任何令牌有写权"

# 主页：该账户的 promoted_pages/assigned_pages（账户可推广对象）
print("\n== 账户可推广主页 ==")
try:
    pages = writer.get_paged(f"act_{ACT}/promote_pages", {"fields": "id,name", "limit": "20"})
except Exception:
    pages = []
if not pages:
    pages = writer.get_pages()   # me/accounts：令牌能管的主页
for p in pages[:5]:
    print(f"  {p.get('id')} {p.get('name')}")
page_id = str(pages[0]["id"]) if pages else ""
assert page_id, "无主页"
db.close()

# DEPLOY（真实花钱：$5/天 TRAFFIC）
H = {"Authorization": f"Bearer {TOK}"}
BASE = "http://127.0.0.1:8000"
print(f"\n== 部署 act {ACT} + page {page_id} ==")
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
        print(f"  poll {i*5}s: {j.get('status')} ok={j.get('succeeded')}")
print("FINAL:", json.dumps(final, ensure_ascii=False)[:900])

# 成功则 FB 核实广告真实存在
if final and final.get("succeeded"):
    item = final["items"][0]
    fb = writer
    ad = fb.get(item["ad_id"], {"fields": "id,name,effective_status,campaign_id"})
    print("\nFB 核实:", json.dumps(ad, ensure_ascii=False))
