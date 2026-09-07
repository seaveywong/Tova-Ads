# UX 链路审计 step0：列出全部链接节点（页/子码/像素）
import json
from app.core.database import SuperSessionLocal
from app.models.launch import LandingPage, LandingAdLink
from app.models.landing_lib import LandingPixel

db = SuperSessionLocal()
print("== published pages ==")
for p in db.query(LandingPage).filter(LandingPage.status == "published").all():
    out = {}
    for k in ["id", "title", "custom_domain", "bound_subdomains",
              "last_health_status", "last_fb_status", "ingest_secret"]:
        v = getattr(p, k, None)
        out[k] = str(v)[:80] if v is not None else None
    print(json.dumps(out, ensure_ascii=False))
print("== subcodes (latest 8) ==")
for l in db.query(LandingAdLink).order_by(LandingAdLink.id.desc()).limit(8).all():
    print(f"  /a/{l.slug} status={l.status} ad={l.ad_id} act={str(l.act_id)[-8:]} targets={str(l.target_urls)[:70]}")
print("== active pixels ==")
for p in db.query(LandingPixel).filter(LandingPixel.status == "active").all():
    print(f"  {p.pixel_id[:16]}... plat={p.platform} act={p.act_id} note={str(p.note)[:30]}")
db.close()
