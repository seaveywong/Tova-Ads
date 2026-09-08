from app.core.database import SuperSessionLocal as S
from sqlalchemy import text as t
db = S()
# job17 在另一个租户? 宽查
j = db.execute(t("SELECT tenant_id, job_id, act_id, campaign_id, ad_id, page_id, pixel_id, page_post_id FROM launch_job_items WHERE job_id IN (16,17) ")).fetchall()
print("JOBS:", j)
# act 1338... 的像素宽查（platform fb, 任意状态）
p2 = db.execute(t("SELECT id, pixel_id, act_id, status FROM landing_pixels WHERE act_id LIKE '%1338258757886709%' OR act_id LIKE '%1338%' LIMIT 5")).fetchall()
print("PIX2:", p2)
# 全部 act 值样本
p3 = db.execute(t("SELECT DISTINCT act_id FROM landing_pixels LIMIT 10")).fetchall()
print("ACTS:", p3)
db.close()
