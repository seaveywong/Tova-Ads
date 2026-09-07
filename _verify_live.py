# P0 验证：live get_active_ads 返回什么（vs cache 有 1 条 ACTIVE）
from app.core.database import SuperSessionLocal
from app.models.fb import Account
from app.core.encryption import decrypt
from app.core.fb_client import FbClient
from app.core.fb_tokens import cred_for_account_op
import json

ACT = "1338258757886709"
db = SuperSessionLocal()
cred = cred_for_account_op(db, 1, ACT, "read")
fb = FbClient(decrypt(cred.access_token_enc))
db.close()

active = fb.get_active_ads(ACT)
print(f"get_active_ads 返回: {len(active)} 条")
for a in active[:3]:
    print(f"  {a.get('id')} {a.get('effective_status')}/{a.get('status')} {a.get('name')}")

# 对照：全状态拉
allads = fb.get_ads(ACT, effective_status=None)
print(f"\n全状态 get_ads 返回: {len(allads)} 条")
for a in allads[:3]:
    print(f"  {a.get('id')} {a.get('effective_status')}/{a.get('status')} {a.get('name')}")
