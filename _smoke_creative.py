# smoke: 同步 Roly 账户 ads_cache → 断言 creative.body/title/thumbnail_url 落库
import json
from app.core.database import SessionLocal, SuperSessionLocal
from app.core.encryption import decrypt
from app.core.fb_client import FbClient
from app.core.fb_tokens import cred_for_account_op
from app.models.ads_cache import AdsCache
from app.routers.ads import _sync_one

ACT = "1338258757886709"
sdb = SuperSessionLocal()
cred = cred_for_account_op(sdb, 1, ACT, "read")
sdb.close()
fb = FbClient(decrypt(cred.access_token_enc))
db = SuperSessionLocal()
r = _sync_one(db, 1, ACT, fb)
print("sync_one:", r)
row = db.query(AdsCache).filter(AdsCache.tenant_id == 1, AdsCache.act_id == ACT).first()
ads = json.loads(row.ads_json or "[]")
target = next((a for a in ads if str(a.get("id")) == "120249455794040413"), None)
assert target, "ad 120249455794040413 not in ads_cache"
cre = target.get("creative") or {}
assert cre.get("body"), "creative.body missing!"
assert cre.get("title"), "creative.title missing!"
assert cre.get("thumbnail_url"), "creative.thumbnail_url missing!"
print("PASS body:", (cre["body"] or "")[:60])
print("PASS title:", (cre["title"] or "")[:60])
print("PASS thumb:", (cre["thumbnail_url"] or "")[:60])
db.close()
