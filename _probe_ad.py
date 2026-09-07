# 定位 POST /ads invalid_param：复现 build_ad 完整 payload + 读 FB 完整错误
import json
from app.core.database import SuperSessionLocal
from app.core.encryption import decrypt
from app.core.fb_client import FbClient, FbApiError
from app.core.fb_tokens import cred_for_account_op
from app.core.ad_builder import build_campaign, build_adset, build_creative
from sqlalchemy import text
import httpx

ACT = "1052568664219129"
db = SuperSessionLocal()
cred = cred_for_account_op(db, 1, ACT, "write")
fb = FbClient(decrypt(cred.access_token_enc))
# 素材2 的 image_hash 缓存（job#13 刚上传成功，hash 在哪？assets 表 ai/hash 或 adimages 缓存——直接现传一张）
from app.core.ad_ops import ensure_image_hash_for_account
import os
from app.core.config import settings
from app.models.launch import Asset
asset = db.query(Asset).filter(Asset.id == 2).first()
path = os.path.join(getattr(settings, "asset_dir", None) or "/opt/toveads/backend/uploads", asset.storage_key)
print("asset path exists:", os.path.exists(path), path)
ih = ensure_image_hash_for_account(fb, db, asset, ACT, path)
db.commit()
print("image_hash:", str(ih)[:24], "...")

# 1) campaign（PAUSED 探针）
from app.core.ad_builder import build_campaign
cp = build_campaign(name="PROBE-C1", objective="OUTCOME_TRAFFIC")
cp["status"] = "PAUSED"
c = fb.post(f"act_{ACT}/campaigns", cp)
cid = c["id"]
print("campaign:", cid)
# 2) adset（TRAFFIC/LINK_CLICKS）
r = httpx.get("http://127.0.0.1:8000/launch-templates/32", timeout=15)
try:
    aset = build_adset(name="PROBE-SET", campaign_id=cid, daily_budget=500, objective="OUTCOME_TRAFFIC",
                       page_id="1321046704419472", landing_url="https://example.com", optimization_goal="LINK_CLICKS")
except Exception as e:
    print("build_adset err:", str(e)[:200]); raise
a = fb.post(f"act_{ACT}/adsets", aset)
aid = a["id"]
print("adset:", aid)
# 3) creative
cr = build_creative(page_id="1321046704419472", objective="OUTCOME_TRAFFIC",
                     landing_url="https://example.com", headline="Test Headline", body="Test body",
                     cta_type="", image_hash=ih)
print("creative payload:", json.dumps(cr, ensure_ascii=False)[:300])
cc = fb.post(f"act_{ACT}/adcreatives", cr)
crid = cc["id"]
print("creative:", crid)
# 4) ad ← 目标步骤
try:
    ad = fb.post(f"act_{ACT}/ads", {"name": "PROBE-AD", "adset_id": aid,
                                    "creative": {"creative_id": crid}, "status": "PAUSED"})
    print("AD OK:", ad)
except FbApiError as e:
    print("AD FAIL category:", getattr(e, "category", ""))
    print("raw:", json.dumps(getattr(e, "raw", None) or str(e), ensure_ascii=False, default=str)[:800])
# 清理
for x in (("ads", None),):
    pass
try:
    fb.delete(crid)
except Exception:
    pass
try:
    fb.delete(aid)
except Exception:
    pass
try:
    fb.delete(cid)
except Exception:
    pass
print("cleaned")
db.close()
