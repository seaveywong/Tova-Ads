"""一次性：把 fb_credential_id 指向失效/空凭证的账户，重新绑到 1111(id=4)。
SC33 账户原绑在已失效的旧 token 上 → 改指 1111（Connor BM）。用完即删。"""
import sys
sys.path.insert(0, "/opt/toveads/backend")
# 导入所有 model 模块，让 Base.metadata 注册全部 FK 目标表（防 NoReferencedTableError）
from app.models import auth, fb, log, guard, notify, ticket, launch, compliance, audience  # noqa: F401
from app.core.database import SuperSessionLocal
from app.models.fb import FbCredential, Account

db = SuperSessionLocal()
active_ids = [c.id for c in db.query(FbCredential).filter(FbCredential.status == "active").all()]
print("active cred ids:", active_ids)
# 找 1111
c1111 = db.query(FbCredential).filter(FbCredential.alias == "1111", FbCredential.status == "active").first()
if not c1111:
    print("NO 1111"); sys.exit(1)
orphans = db.query(Account).filter(
    (Account.fb_credential_id.is_(None)) | (Account.fb_credential_id.notin_(active_ids))
).all()
print(f"orphan accounts to repoint to 1111 (id={c1111.id}): {len(orphans)}")
for a in orphans:
    print(f"  act_{a.act_id} [{a.name[:30]}] cred {a.fb_credential_id} -> {c1111.id}")
    a.fb_credential_id = c1111.id
db.commit()
print("done")
