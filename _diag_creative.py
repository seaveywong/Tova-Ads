# 验证 creative{body,title} 在 /ads 边扩展（get_ads 实际形态）下可用
import json
from app.core.database import SuperSessionLocal
from app.core.encryption import decrypt
from app.core.fb_client import FbClient
from app.core.fb_tokens import cred_for_account_op

ACT = "1338258757886709"
db = SuperSessionLocal()
cred = cred_for_account_op(db, 1, ACT, "read")
fb = FbClient(decrypt(cred.access_token_enc))
r = fb.get_node("120249455794040413",
                "id,name,creative{id,effective_object_story_id,object_story_spec,thumbnail_url,body,title}")
cre = r.get("creative") or {}
print(json.dumps({"body": (cre.get("body") or "")[:50], "title": (cre.get("title") or "")[:50],
                  "thumb": (cre.get("thumbnail_url") or "")[:40]}, ensure_ascii=False))
db.close()
