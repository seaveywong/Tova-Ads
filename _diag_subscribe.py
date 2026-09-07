# 诊断潜客 webhook 订阅 0/13：复现 /leads/subscribe 逐页抓真实报错
import json
from app.core.database import SuperSessionLocal
from app.core.encryption import decrypt
from app.core.fb_client import FbClient, FbApiError
from app.models.fb import FbCredential

db = SuperSessionLocal()
# 多令牌逐个测（_get_active_cred 取首个 active——先看是哪个 + 换令牌有没有差别）
creds = db.query(FbCredential).filter(FbCredential.tenant_id == 1,
                                      FbCredential.status == "active").all()
print(f"active creds: {[(c.id, c.alias, c.token_type) for c in creds]}")
cred = creds[0]
print(f"selected(首个active): #{cred.id} {cred.alias}")
fb = FbClient(decrypt(cred.access_token_enc))
pages = fb.get_paged("me/accounts", {"fields": "id,name,access_token,permitted_tasks"})
print(f"me/accounts: {len(pages)} pages")
for p in pages[:20]:
    pid, ptoken, pname = p.get("id"), p.get("access_token"), p.get("name")
    tasks = p.get("permitted_tasks") or []
    has_meta = any("METADATA" in str(t).upper() or "ADMIN" in str(t).upper() for t in tasks)
    try:
        page_fb = FbClient(ptoken)
        page_fb.post(f"{pid}/subscribed_apps", {"subscribed_fields": "leadgen"})
        print(f"  OK   {pname}({pid}) meta_task={has_meta}")
    except FbApiError as e:
        print(f"  FAIL {pname}({pid}) meta_task={has_meta}: code={getattr(e,'category','')} {str(e)[:120]}")
db.close()
