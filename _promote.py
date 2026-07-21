"""一次性：把 fbreal@toveads.com 提升为平台超管（测域名分配用）。用完即删。"""
import sys
sys.path.insert(0, "/opt/toveads/backend")
from app.core.database import SuperSessionLocal
from app.models.auth import User
db = SuperSessionLocal()
u = db.query(User).filter(User.email == "fbreal@toveads.com").first()
if not u:
    print("NO USER"); sys.exit(1)
u.is_superadmin = True
db.commit()
print(f"promoted: {u.email} is_superadmin={u.is_superadmin}")
