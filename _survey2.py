# 补齐盘点（落地页/模板/AppSecret）—— 用列名探测避免猜字段
from app.core.database import SuperSessionLocal
from app.models.launch import LandingPage
from app.models.launch_template import LaunchTemplate
from app.models.fb_app import FbApp

db = SuperSessionLocal()
try:
    cols = {c.name for c in LandingPage.__table__.columns}
    print("LandingPage cols:", sorted(cols)[:20])
    for p in db.query(LandingPage).filter(LandingPage.status == "published").limit(6).all():
        label = p.slug if "slug" in cols else (p.title if "title" in cols else p.id)
        url = getattr(p, "public_url", "") or getattr(p, "url", "")
        print(f"  lp#{p.id} label={label} url={url}")
    for t in db.query(LaunchTemplate).limit(6).all():
        print(f"  tpl#{t.id} {t.name} status={t.status} asset={t.asset_id} budget={t.daily_budget} lp_id={t.landing_page_id}")
    for a in db.query(FbApp).all():
        print(f"  app {a.app_id} secret={'Y' if a.app_secret_enc else 'N'} level={getattr(a, 'access_level', None)}")
finally:
    db.close()
