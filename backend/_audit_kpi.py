"""报表准确性/规则引擎 实测交叉验证：真实账户 insights → resolver vs FB 自报口径。

用 MGT 令牌挑有消耗的广告，对比：我们算的 conversions vs FB 的 cost_per_action_type 反推/直接对比。
"""
import json
from app.core.database import SuperSessionLocal
from app.core.encryption import decrypt
from app.core.fb_client import FbClient
from app.models.fb import FbCredential
from app.services.kpi_resolver import resolve_kpi
from app.core.kpi_mapping import get_kpi_mapping, field_label

db = SuperSessionLocal()
cred = db.query(FbCredential).order_by(FbCredential.id.desc()).first()
fb = FbClient(decrypt(cred.access_token_enc))
mapping = get_kpi_mapping(db)

# ① 找有消耗的账户（最近 7 天）
accts = fb.get_paged("me/adaccounts", {"fields": "account_id,name,currency,amount_spent", "limit": 30})
cand = [a for a in accts if float(a.get("amount_spent", 0) or 0) > 0][:5]
print(f"候选账户（有花费）: {len(cand)} 个")

tested = 0
for a in cand:
    act = a["account_id"]
    rows = fb.get_ad_insights(act, date_preset="last_7d", only_active=False, limit=15)
    if not rows:
        continue
    # 挑 spend>0 的广告行
    rows = [r for r in rows if float(r.get("spend", 0) or 0) > 0][:5]
    if not rows:
        continue
    # objective 批量取（照抄巡检 _campaign_objectives 的做法）
    cids = {r.get("campaign_id") for r in rows}
    obj_map = {}
    for i in range(0, len(cids), 50):
        batch = list(cids)[i:i + 50]
        try:
            data = fb.get("", {"ids": ",".join(batch), "fields": "id,objective,optimization_goal"})
            for cid, c in (data or {}).items():
                if isinstance(c, dict):
                    obj_map[cid] = ((c.get("objective") or "").upper(), (c.get("optimization_goal") or "").upper())
        except Exception:
            pass
    print(f"\n═══ 账户 act_{act}（{a.get('currency')}）最近7天 {len(rows)} 个广告 ═══")
    for r in rows:
        actions = r.get("actions", []) or []
        obj, og = obj_map.get(r.get("campaign_id", ""), ("", ""))
        kpi = resolve_kpi(db, 1, r.get("campaign_id", ""), obj, og, actions)
        our_conv = kpi["conversions"]
        spend = float(r.get("spend", 0) or 0)
        # FB 自报：cost_per_action_type 里该字段的成本反推（独立口径交叉验证）
        fb_cpa_list = r.get("cost_per_action_type", []) or []
        fb_match = next((c for c in fb_cpa_list if c.get("action_type") == kpi["kpi_field"]), None)
        fb_conv = round(spend / float(fb_match["value"]), 2) if fb_match and float(fb_match.get("value", 0) or 0) > 0 else None
        ok = "✅" if (fb_conv is None or abs(fb_conv - our_conv) <= max(1, our_conv * 0.02)) else "❌"
        print(f"  {ok} {r.get('ad_name','')[:18]:18} obj={obj[:16]:16} KPI={kpi['kpi_field'][:36]:36}({kpi['source'][:4]}) "
              f"我们={our_conv} FB反推={fb_conv} spend={spend:.2f}")
        tested += 1
    if tested >= 12:
        break
print(f"\n交叉验证完成: {tested} 条")
db.close()
