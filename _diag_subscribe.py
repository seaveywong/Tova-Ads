# 诊断订阅 0/10：遍历全部活跃令牌的页清单 + permitted_tasks 权限明细
import json
from app.core.database import SuperSessionLocal
from app.core.encryption import decrypt
from app.core.fb_client import FbClient, FbApiError
from app.models.fb import FbCredential

db = SuperSessionLocal()
creds = db.query(FbCredential).filter(FbCredential.tenant_id == 1,
                                      FbCredential.status == "active").all()
print(f"active creds: {[(c.id, (c.alias or '?')[:25], c.token_type) for c in creds]}")
for cred in creds:
    fb = FbClient(decrypt(cred.access_token_enc))
    try:
        pages = fb.get_paged("me/accounts", {"fields": "id,name,permitted_tasks,tasks"})
    except FbApiError as e:
        print(f"  cred#{cred.id} me/accounts FAIL: {e}")
        continue
    print(f"  cred#{cred.id} {(cred.alias or '?')[:25]}: {len(pages)} pages")
    for p in pages[:15]:
        tasks = p.get("permitted_tasks") or p.get("tasks") or []
        meta = any("METADATA" in str(t).upper() or "ADMINISTER" in str(t).upper() for t in tasks)
        print(f"    {'OK ' if meta else 'NO '} {p.get('name','?')[:28]} tasks={[t for t in tasks if t not in ('ANALYZE','ADVERTISE','MESSAGING','MODERATE','CREATE_CONTENT','MANAGE')][:3] or tasks[:4]}")
db.close()
