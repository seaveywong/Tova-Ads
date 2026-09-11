"""验证 #200 是否令牌特定：同一批账户(O311~O315)分别用每个覆盖令牌读一次。
若 Kritins Rae 成功而 Noorhlha/Gia 报 #200 → 权限墙（BM 共享侧令牌被拒）；
若所有令牌都成功 → 当晚是瞬时限流类；若都 #200 → 全局墙。"""
from app.core.database import SuperSessionLocal
from app.core.encryption import decrypt
from app.models.fb import FbCredential, Account
from app.core.fb_client import FbClient

ACTS = ["1108267155197598", "1575921667913409", "1378531087136917",
        "976293262142317", "1774674520210840"]
db = SuperSessionLocal()
creds = db.query(FbCredential).filter(FbCredential.status == "active").all()
for c in creds:
    fb = FbClient(decrypt(c.access_token_enc))
    print(f"\n===== {c.alias} (cred {c.id}) =====")
    for aid in ACTS:
        try:
            node = fb.get(f"act_{aid}", {"fields": "account_id,name,account_status"})
            print(f"  {aid}: OK status={node.get('account_status')} {node.get('name', '')[:20]}")
        except Exception as e:
            cat = getattr(e, "category", "?")
            print(f"  {aid}: FAIL [{cat}] {str(getattr(e, 'friendly', e))[:60]}")
db.close()
