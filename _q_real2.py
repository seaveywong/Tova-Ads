from app.core.database import SuperSessionLocal as S
from sqlalchemy import text as t
db = S()
lp = db.execute(t("SELECT id, title, redirect_mode, status, pixel_ids FROM landing_pages WHERE tenant_id=1 ORDER BY id DESC LIMIT 5")).fetchall()
pix = db.execute(t("SELECT id, pixel_id, act_id, platform FROM landing_pixels WHERE tenant_id=1 ORDER BY id DESC LIMIT 8")).fetchall()
job = db.execute(t("SELECT id, act_id, page_id, pixel_id, status FROM launch_job_items WHERE tenant_id=1 AND status='success' ORDER BY id DESC LIMIT 2")).fetchall()
print("LP:", lp)
print("PIX:", pix)
print("LASTJOB:", job)
db.close()
