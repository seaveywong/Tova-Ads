"""预算预警实测：用 alias=1111 token 在 act_534950738534455 上跑真实 check_account_budget_progress。
该账户有广告系列预算已超 50%。验证告警是否正确触发。用完即删。"""
import sys
sys.path.insert(0, "/opt/toveads/backend")
from app.core.database import SuperSessionLocal
from app.core.encryption import decrypt
from app.core.fb_client import FbClient
from app.core.log_utils import new_trace_id
from app.models.fb import FbCredential, Account
from app.services.budget_alerts import check_account_budget_progress

ACT_ID = "534950738534455"

class _Acc:
    """Account stand-in（若 DB 没有该行也能跑）。"""
    def __init__(self, act_id, name, currency, tz):
        self.act_id = act_id; self.name = name; self.currency = currency; self.timezone_name = tz; self.account_status = 1

def main():
    db = SuperSessionLocal()
    cred = db.query(FbCredential).filter(FbCredential.alias == "1111", FbCredential.status == "active").first()
    if not cred:
        print("NO_1111"); return
    fb = FbClient(decrypt(cred.access_token_enc))
    # 优先用 DB 里的 Account 行；没有就用 stand-in
    acc = db.query(Account).filter(Account.act_id == ACT_ID).first()
    if not acc:
        acc = _Acc(ACT_ID, "Surge-SC33-VND-(GMT+7)-042", "VND", "Asia/Ho_Chi_Minh")
        print("(account not in DB, using stand-in)")
    print(f"account: act_{acc.act_id} | {acc.name} | {acc.currency} | {acc.timezone_name}")
    # 先看原始 adset + spend（诊断）
    adsets = fb.get_adsets(ACT_ID)
    spend_map = {i.get("adset_id"): float(i.get("spend", 0)) for i in fb.get_adset_insights(ACT_ID, "today")}
    print(f"=== {len(adsets)} active adset(s) ===")
    for ad in adsets:
        aid = ad["id"]; db_daily = ad.get("daily_budget"); sp = spend_map.get(aid, 0.0)
        prog = (sp / float(db_daily) * 100) if db_daily else 0
        print(f"  adset {aid} [{(ad.get('name') or '')[:30]}] daily_budget={db_daily} spend={sp} progress={prog:.1f}%")
    # 跑真实告警逻辑
    tid = new_trace_id()
    alerts = check_account_budget_progress(db, tenant_id=1, fb=fb, acc=acc, trace_id=tid)
    print(f"=== alerts fired: {len(alerts)} ===")
    for a in alerts:
        print(f"  adset {a['adset_id']} tier={a['tier']}% progress={a['progress']}% spend={a['spend']}/{a['budget']}")
    print(f"trace_id={tid}")

if __name__ == "__main__":
    main()
