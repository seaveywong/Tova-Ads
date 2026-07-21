"""一次性：停用旧失效 token + 列当前凭证 + 查 2222 可见账户。用完即删。"""
import sys
sys.path.insert(0, "/opt/toveads/backend")
from app.core.database import SuperSessionLocal
from app.core.encryption import decrypt
from app.core.fb_client import FbClient, FbApiError
from app.models.fb import FbCredential

def main():
    db = SuperSessionLocal()
    creds = db.query(FbCredential).all()
    print("=== current creds ===")
    for c in creds:
        print(f"  id={c.id} alias={c.alias} status={c.status} user={c.fb_user_name}")
    # 停用所有无 alias 的（旧的）
    n = db.query(FbCredential).filter(FbCredential.alias.is_(None)).update({FbCredential.status: "inactive"})
    db.commit()
    print(f"deactivated {n} no-alias (old) credential(s)")
    print("=== after ===")
    for c in db.query(FbCredential).all():
        print(f"  id={c.id} alias={c.alias} status={c.status}")
    # 用每个 active token 查可见账户 + 是否能看到 act_534950738534455
    TARGET = "534950738534455"
    for c in db.query(FbCredential).filter(FbCredential.status == "active").all():
        fb = FbClient(decrypt(c.access_token_enc))
        try:
            accts = fb.get_ad_accounts()
            ids = [a.get("account_id") for a in accts]
            print(f"=== alias={c.alias} sees {len(ids)} accounts; target {TARGET} accessible: {TARGET in ids} ===")
            for a in accts[:8]:
                print(f"    act_{a.get('account_id')} {a.get('name')[:40]} {a.get('currency')}")
        except FbApiError as e:
            print(f"=== alias={c.alias} READ FAIL: {e.friendly} ===")

if __name__ == "__main__":
    main()
