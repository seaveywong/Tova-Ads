"""查最新个人令牌的权限快照 + 实测 debug_token 当前 scopes。"""
import json
from app.core.database import SuperSessionLocal
from app.core.encryption import decrypt
from app.core.fb_client import FbClient
from app.models.fb import FbCredential

db = SuperSessionLocal()
for cred in db.query(FbCredential).order_by(FbCredential.id.desc()).limit(5).all():
    snap = None
    try:
        snap = json.loads(cred.permission_snapshot or "{}")
    except Exception:
        pass
    scopes = (snap or {}).get("scopes") or []
    print(f"凭证#{cred.id} {cred.fb_user_name} alias={cred.alias} status={cred.status}")
    print(f"  快照 scopes({len(scopes)}): {scopes}")
    # 实时验一次（以当前为准）
    try:
        fb = FbClient(decrypt(cred.access_token_enc))
        d = fb.debug_token().get("data", {})
        live = d.get("scopes") or []
        print(f"  实时 scopes({len(live)}): {live}")
        print(f"  app_id={d.get('app_id')} valid={d.get('is_valid')}")
    except Exception as e:
        print(f"  实时验失败: {str(e)[:100]}")
    NEED = {"ads_management": "写操作(停广告/预算)", "ads_read": "读报表",
            "business_management": "BM 列表(资产抽屉)", "pages_show_list": "主页列表",
            "pages_manage_ads": "建帖/跟帖"}
    miss = [f"{k}({v})" for k, v in NEED.items() if k not in live]
    print(f"  缺: {miss or '无'}")
    print()
db.close()
