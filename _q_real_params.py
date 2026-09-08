from app.core.database import SuperSessionLocal as S
from sqlalchemy import text as t
db = S()
lp = db.execute(t("SELECT id, title, redirect_mode, status FROM landing_pages WHERE tenant_id=1 AND status='active' AND redirect_mode='display' ORDER BY id DESC LIMIT 3")).fetchall()
ast = db.execute(t("SELECT id, name, type FROM assets WHERE tenant_id=1 AND type='image' ORDER BY id DESC LIMIT 3")).fetchall()
act = "1338258757886709"
pages = db.execute(t(f"SELECT id, alias FROM fb_credentials WHERE tenant_id=1 AND status='active' LIMIT 5")).fetchall()
sub = db.execute(t("SELECT slug, page_id FROM landing_ad_links WHERE tenant_id=1 AND status IN ('reserved','active') ORDER BY id DESC LIMIT 3")).fetchall()
print("LP:", lp)
print("ASSET:", ast)
print("CRED:", pages)
print("SUBCODE:", sub)
db.close()
