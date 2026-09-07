# 批G PART2b：deploy_one_account 扩参 + 平铺/树部署链 + 预检透传
import io

edits = []

# ── 7. core/ad_ops.py: deploy_one_account 扩 kwargs ──
p = "backend/app/core/ad_ops.py"
s = io.open(p, encoding="utf-8").read()
old = '''                       destination_type_override: str = "",
                       page_post_id: str = "",
                       advanced_config: dict | None = None) -> dict:'''
new = '''                       destination_type_override: str = "",
                       page_post_id: str = "",
                       advanced_config: dict | None = None,
                       budget_type: str = "daily",
                       lifetime_budget: int | None = None,
                       start_time: str = "",
                       end_time: str = "",
                       pacing: str = "",
                       bid_amount: int | None = None,
                       minimum_roas: float | None = None,
                       special_ad_categories: list | None = None,
                       description: str = "") -> dict:'''
assert old in s, "doa_sig"; s = s.replace(old, new, 1); edits.append("doa_sig")

old = '''    camp_payload = build_campaign(
        name=name_prefix, objective=objective,
        daily_budget=daily_budget if budget_mode.upper() == "CBO" else None,
        budget_mode=budget_mode, bid_strategy=bid_strategy,
    )'''
new = '''    camp_payload = build_campaign(
        name=name_prefix, objective=objective,
        daily_budget=(daily_budget if (budget_mode.upper() == "CBO"
                                       and budget_type.lower() != "lifetime") else None),
        lifetime_budget=(lifetime_budget if (budget_mode.upper() == "CBO"
                                             and budget_type.lower() == "lifetime") else None),
        budget_mode=budget_mode, bid_strategy=bid_strategy,
        special_ad_categories=special_ad_categories,
    )'''
assert old in s, "doa_camp"; s = s.replace(old, new, 1); edits.append("doa_camp")

old = '''        optimization_goal=optimization_goal, billing_event=billing_event,
        destination_type_override=destination_type_override,
        extra=advanced_config,
    )'''
new = '''        optimization_goal=optimization_goal, billing_event=billing_event,
        destination_type_override=destination_type_override,
        extra=advanced_config,
        budget_type=budget_type, lifetime_budget=lifetime_budget,
        start_time=start_time, end_time=end_time, pacing=pacing,
        bid_amount=bid_amount, minimum_roas=minimum_roas,
    )'''
assert old in s, "doa_adset"; s = s.replace(old, new, 1); edits.append("doa_adset")

io.open(p, "w", encoding="utf-8", newline="\n").write(s)
print("PART2b-adops:", edits)

# ── 8. launch_templates.py：平铺 _deploy_series_fb 调用点透传 ──
p = "backend/app/routers/launch_templates.py"
s = io.open(p, encoding="utf-8").read()

# 8a. 平铺：换算新字段（lifetime/bid）并透传
old = '''    return deploy_one_account(
        fb, act_id=item.act_id, objective=tpl.objective, conversion_goal=tpl.conversion_goal,
        page_id=page_id, pixel_id=pixel_id, landing_url=_lp_url,
        daily_budget=daily_budget_fb, budget_mode=tpl.budget_mode, bid_strategy=tpl.bid_strategy,
        name_prefix=series_name or tpl.name_prefix, headline=_headline, body=_body, cta_type=tpl.cta_type,'''
new = '''    # 批G 新字段：总预算/出价额按账户本币换算（排期/投放方式/ROAS/类别/描述直传）
    _btype = (tpl.budget_type or "daily").lower()
    _lifetime_fb = (_usd_to_account_minor(sdb, item.act_id, float(tpl.lifetime_budget_usd), tenant_id)
                    if _btype == "lifetime" and tpl.lifetime_budget_usd else None)
    _bid_fb = (_usd_to_account_minor(sdb, item.act_id, float(tpl.bid_amount_usd), tenant_id)
               if tpl.bid_amount_usd else None)
    try:
        _cats = json.loads(tpl.special_ad_categories or "[]")
    except Exception:
        _cats = []
    return deploy_one_account(
        fb, act_id=item.act_id, objective=tpl.objective, conversion_goal=tpl.conversion_goal,
        page_id=page_id, pixel_id=pixel_id, landing_url=_lp_url,
        daily_budget=daily_budget_fb, budget_mode=tpl.budget_mode, bid_strategy=tpl.bid_strategy,
        name_prefix=series_name or tpl.name_prefix, headline=_headline, body=_body, cta_type=tpl.cta_type,'''
assert old in s, "flat_newfld"; s = s.replace(old, new, 1); edits.append("flat_newfld")

old = '''        lead_form_id=lead_form_id, message_template=message_template,
    )'''
new = '''        lead_form_id=lead_form_id, message_template=message_template,
        budget_type=_btype, lifetime_budget=_lifetime_fb,
        start_time=(tpl.schedule_start or ""), end_time=(tpl.schedule_end or ""),
        pacing=(tpl.pacing or ""), bid_amount=_bid_fb,
        minimum_roas=(tpl.minimum_roas if tpl.minimum_roas else None),
        special_ad_categories=_cats, description=(tpl.link_description or ""),
    )'''
assert old in s, "flat_call"; s = s.replace(old, new, 1); edits.append("flat_call")

io.open(p, "w", encoding="utf-8", newline="\n").write(s)
print("PART2b-router:", edits)
