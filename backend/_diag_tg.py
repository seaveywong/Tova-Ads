"""TG 绑定现状诊断：谁绑在哪一级、路由会发给谁。只读。"""
from app.core.database import SuperSessionLocal
from app.models.notify import UserTgBinding, TenantTgBinding

db = SuperSessionLocal()
print("═══ 用户级绑定（告警优先发这里）═══")
for b in db.query(UserTgBinding).all():
    print(f"  tenant={b.tenant_id} user={b.user_id} chat_id={b.chat_id} verified={b.verified_at}")
print("\n═══ 租户级绑定（无人级绑定时兜底）═══")
for b in db.query(TenantTgBinding).all():
    print(f"  tenant={b.tenant_id} chat_id={b.chat_id}")

# 成员角色 → 路由推演
from app.models.auth import TenantMembership
print("\n═══ 路由推演 ═══")
for tid in {b.tenant_id for b in db.query(UserTgBinding).all()} | {b.tenant_id for b in db.query(TenantTgBinding).all()}:
    ub = db.query(UserTgBinding).filter(UserTgBinding.tenant_id == tid).all()
    tb = db.query(TenantTgBinding).filter(TenantTgBinding.tenant_id == tid).all()
    print(f"  tenant={tid}: 用户级绑定 {[b.chat_id for b in ub]} → "
          f"{'告警发这些 chat' if ub else f'无用户级→兜底租户级 {[b.chat_id for b in tb]}'}")
db.close()
