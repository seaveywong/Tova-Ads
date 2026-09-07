# 诊断 live_fetch_degraded 告警根因：逐账户跑 worker 的 live 拉取分支
import json
from app.core.database import SuperSessionLocal
from app.models.fb import Account
from app.core.encryption import decrypt
from app.core.fb_client import FbClient, FbApiError
from app.core.fb_tokens import cred_for_account_op

db = SuperSessionLocal()
accs = db.query(Account).filter(
    Account.is_managed == True, (Account.platform or "fb") != "tt").all()  # noqa: E712
print(f"managed fb accounts: {len(accs)}")
for a in accs:
    if a.account_status in (2, 8, 100, 101):
        print(f"  {a.act_id} {a.name}: 跳过(死状态 {a.account_status})")
        continue
    try:
        cred = cred_for_account_op(db, a.tenant_id, a.act_id, "read")
    except Exception as e:
        print(f"  {a.act_id}: 无令牌({str(e)[:40]})")
        continue
    if not cred:
        print(f"  {a.act_id} {a.name}: ❌ 无读令牌 → 走兜底")
        continue
    fb = FbClient(decrypt(cred.access_token_enc))
    try:
        ads = fb.get_active_ads(a.act_id)
        print(f"  {a.act_id} {a.name}: live={len(ads)} 条 (cred#{cred.id})")
    except FbApiError as e:
        print(f"  {a.act_id} {a.name}: ❌ {getattr(e, 'category', '')} {str(e)[:60]} (cred#{cred.id})")
db.close()
