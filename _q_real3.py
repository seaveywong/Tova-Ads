from app.core.database import SuperSessionLocal as S
from sqlalchemy import text as t
db = S()
p = db.execute(t("SELECT id, pixel_id, act_id FROM landing_pixels WHERE tenant_id=1 AND act_id='1338258757886709' LIMIT 5")).fetchall()
j = db.execute(t("SELECT i.campaign_id, i.adset_id, i.ad_id, i.page_post_id, i.page_id, i.pixel_id FROM launch_job_items i WHERE i.job_id=17")).fetchall()
print("ACTPIX:", p)
print("JOB17:", j)
db.close()
