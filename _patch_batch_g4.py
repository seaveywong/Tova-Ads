# 批G PART4：平铺预检新字段（campaign lifetime/类别 + adset 排期/出价 + out 暴露）
import io
edits = []
p = "backend/app/routers/launch_templates.py"
s = io.open(p, encoding="utf-8").read()

old = '''        campaign_payload = build_campaign(
            name=_prefix, objective=t.objective,
            daily_budget=daily_budget_fb if t.budget_mode.upper() == "CBO" else None,
            budget_mode=t.budget_mode, bid_strategy=t.bid_strategy,
        )'''
new = '''        _p_btype = (t.budget_type or "daily").lower()
        _p_lifetime_fb = (usd_to_fb_amount(float(t.lifetime_budget_usd), currency, cr.rate if cr else 1.0)
                          if (_p_btype == "lifetime" and t.lifetime_budget_usd) else None)
        _p_bid_fb = (usd_to_fb_amount(float(t.bid_amount_usd), currency, cr.rate if cr else 1.0)
                     if t.bid_amount_usd else None)
        try:
            _p_cats = json.loads(t.special_ad_categories or "[]")
        except Exception:
            _p_cats = []
        campaign_payload = build_campaign(
            name=_prefix, objective=t.objective,
            daily_budget=(daily_budget_fb if (t.budget_mode.upper() == "CBO" and not _p_lifetime_fb) else None),
            lifetime_budget=_p_lifetime_fb,
            budget_mode=t.budget_mode, bid_strategy=t.bid_strategy,
            special_ad_categories=_p_cats,
        )'''
assert old in s, "pf_camp"; s = s.replace(old, new, 1); edits.append("pf_camp")

old = '''            optimization_goal=t.optimization_goal or "", billing_event=t.billing_event or "",
            destination_type_override=t.destination_type or "", extra=advanced,
        )'''
new = '''            optimization_goal=t.optimization_goal or "", billing_event=t.billing_event or "",
            destination_type_override=t.destination_type or "", extra=advanced,
            budget_type=_p_btype, lifetime_budget=_p_lifetime_fb,
            start_time=(t.schedule_start or ""), end_time=(t.schedule_end or ""),
            pacing=(t.pacing or ""), bid_amount=_p_bid_fb,
            minimum_roas=(t.minimum_roas if t.minimum_roas else None),
        )'''
assert old in s, "pf_adset"; s = s.replace(old, new, 1); edits.append("pf_adset")

old = '''        "subcode_warn_slug": subcode_warn_slug,'''
new = '''        "subcode_warn_slug": subcode_warn_slug,
        "budget_type": (t.budget_type or "daily"),
        "lifetime_budget_usd": t.lifetime_budget_usd, "lifetime_budget_fb": _p_lifetime_fb,
        "schedule_start": (t.schedule_start or ""), "schedule_end": (t.schedule_end or ""),
        "pacing": (t.pacing or ""), "bid_amount_usd": t.bid_amount_usd,
        "bid_amount_fb": _p_bid_fb, "minimum_roas": t.minimum_roas,
        "special_ad_categories": _p_cats, "link_description": (t.link_description or ""),'''
assert old in s, "pf_out"; s = s.replace(old, new, 1); edits.append("pf_out")

io.open(p, "w", encoding="utf-8", newline="\n").write(s)
print("PART4:", edits)
