"""验证 get_paged 翻页：用 limit=2 拉 2222 的账户（>2 个会翻页）。应返回全部，不只第一页。"""
import sys
sys.path.insert(0, "/opt/toveads/backend")
from app.core.database import SuperSessionLocal
from app.core.encryption import decrypt
from app.core.fb_client import FbClient
from app.models.fb import FbCredential

db = SuperSessionLocal()
for alias in ("2222", "1111"):
    c = db.query(FbCredential).filter(FbCredential.alias == alias, FbCredential.status == "active").first()
    if not c:
        print(alias, "missing"); continue
    fb = FbClient(decrypt(c.access_token_enc))
    full = fb.get_ad_accounts()  # limit=200 默认
    # 强制 limit=2 触发翻页
    paged_small = fb.get_paged("me/adaccounts", {
        "fields": "account_id,name,currency"}, limit=2)
    print(f"{alias}: full={len(full)}  paged(limit=2)={len(paged_small)}  match={len(full)==len(paged_small)}")
    if len(full) != len(paged_small):
        print(f"  ❌ PAGINATION BROKEN: full has {len(full)} but limit=2 traversal got {len(paged_small)}")
    else:
        print(f"  ✅ pagination traverses all pages correctly")
