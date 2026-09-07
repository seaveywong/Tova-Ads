# 查测试广告三层状态 + 需要时激活
import json
from app.core.database import SuperSessionLocal
from app.models.fb import Account
from app.core.encryption import decrypt
from app.core.fb_client import FbClient
from app.core.fb_tokens import cred_for_account_op

ACT = "1338258757886709"
AD = "120249455794040413"
CAMP = "120249455791930413"
ADSET = "120249455792580413"

db = SuperSessionLocal()
cred = cred_for_account_op(db, 1, ACT, "write")
fb = FbClient(decrypt(cred.access_token_enc))
db.close()

print("== 三层当前状态 ==")
for label, nid in (("campaign", CAMP), ("adset", ADSET), ("ad", AD)):
    n = fb.get(nid, {"fields": "effective_status,status,name"})
    print(f"  {label}: status={n.get('status')} effective={n.get('effective_status')} ({n.get('name')})")
