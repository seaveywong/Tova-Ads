# 批J smoke：已部署模板 force 删除（自建临时模板+job，跑完清理——零生产残留）
import sys
sys.path.insert(0, "/opt/toveads/backend")
from dotenv import load_dotenv; load_dotenv("/opt/toveads/backend/.env")
from types import SimpleNamespace
from fastapi import HTTPException
from app.core.database import SuperSessionLocal
from app.models.launch_template import LaunchTemplate, LaunchJob
from app.routers.launch_templates import hard_delete_template

ok = fail = 0
def check(name, cond, detail=""):
    global ok, fail
    if cond: ok += 1; print("PASS", name)
    else: fail += 1; print("FAIL", name, detail)

db = SuperSessionLocal()
user = SimpleNamespace(tenant_id=1, id=1)
tpl = LaunchTemplate(tenant_id=1, name="[SMOKE批J]force删测-" + str(__import__("random").randint(1000, 9999)),
                     platform="fb", status="draft")
db.add(tpl); db.flush()
job = LaunchJob(tenant_id=1, template_id=tpl.id, template_name=tpl.name, status="completed", total=1)
db.add(job); db.commit()
tid = tpl.id
try:
    # 1) 无 force → 400 拒删
    try:
        hard_delete_template(tid, 0, user, db)
        check("no-force rejected", False, "no HTTPException")
    except HTTPException as e:
        check("no-force rejected", e.status_code == 400, str(e.status_code))
    # 2) force=1 → 删除成功，job 保留且解除关联（template_name 快照在）
    r = hard_delete_template(tid, 1, user, db)
    check("force deleted", r.get("deleted") is True and r.get("jobs_detached") == 1, str(r))
    db.refresh(job)
    check("job kept + detached", job.template_id is None and job.template_name and "[SMOKE批J]" in job.template_name,
          f"{job.template_id}/{job.template_name}")
    check("template row gone", db.query(LaunchTemplate).filter(LaunchTemplate.id == tid).first() is None, "row exists")
finally:
    # 清理：job 行（测试产物）删除
    db.query(LaunchJob).filter(LaunchJob.id == job.id, LaunchJob.template_name.like("[SMOKE批J]%")).delete()
    db.query(LaunchTemplate).filter(LaunchTemplate.id == tid).delete()
    db.commit()
    left = db.query(LaunchJob).filter(LaunchJob.template_name.like("[SMOKE批J]%")).count()
    db.close()
    check("cleanup no residue", left == 0, f"left={left}")
print(f"SMOKE_RESULT: {'ALL_PASS' if fail == 0 else 'FAIL'} ({ok}/{ok+fail})")
sys.exit(0 if fail == 0 else 1)
