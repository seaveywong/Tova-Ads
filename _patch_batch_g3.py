# 批G PART3：树 runner + 树/平铺预检 新字段透传
import io

edits = []
p = "backend/app/routers/launch_templates.py"
s = io.open(p, encoding="utf-8").read()

# ── 9. 树 runner：campaign 层（特殊类别 + CBO 总预算）──
old = '''    campaign_name = (tpl.name_prefix or tpl.name or "Tova Ads")[:100]
    is_cbo = (tpl.budget_mode or "ABO").upper() == "CBO"
    camp_budget_fb = _resolve_budget_fb(sdb, item.act_id, tpl, tenant_id)
    camp_payload = build_campaign(
        name=campaign_name, objective=tpl.objective,
        daily_budget=camp_budget_fb if is_cbo else None,
        budget_mode=tpl.budget_mode, bid_strategy=tpl.bid_strategy)'''
new = '''    campaign_name = (tpl.name_prefix or tpl.name or "Tova Ads")[:100]
    is_cbo = (tpl.budget_mode or "ABO").upper() == "CBO"
    _cats = []
    try:
        _cats = json.loads(tpl.special_ad_categories or "[]")
    except Exception:
        pass
    # 系列预算：CBO lifetime 用总预算（换算本币），否则日预算管道
    _tpl_btype = (tpl.budget_type or "daily").lower()
    if is_cbo and _tpl_btype == "lifetime":
        if not tpl.lifetime_budget_usd:
            raise FbApiError("no_id", "CBO 总预算模式未填总预算金额")
        _camp_lifetime_fb = _usd_to_account_minor(sdb, item.act_id, float(tpl.lifetime_budget_usd), tenant_id)
        camp_budget_fb = _camp_lifetime_fb
    else:
        _camp_lifetime_fb = None
        camp_budget_fb = _resolve_budget_fb(sdb, item.act_id, tpl, tenant_id)
    camp_payload = build_campaign(
        name=campaign_name, objective=tpl.objective,
        daily_budget=(camp_budget_fb if (is_cbo and not _camp_lifetime_fb) else None),
        lifetime_budget=_camp_lifetime_fb,
        budget_mode=tpl.budget_mode, bid_strategy=tpl.bid_strategy,
        special_ad_categories=_cats)'''
assert old in s, "tree_camp"; s = s.replace(old, new, 1); edits.append("tree_camp")

# ── 10. 树 runner：adset 层（节点预算类型/排期/投放方式/出价/ROAS）──
old = '''        # 组预算（ABO）：节点 USD 覆盖 > 模板默认；CBO 组不带预算（系列级）
        if is_cbo:
            adset_budget_fb = camp_budget_fb
        else:
            node_b = snode.get("budget_usd")
            try:
                adset_budget_fb = _resolve_budget_fb(
                    sdb, item.act_id,
                    _view(budget_usd=float(node_b) if node_b else tpl.budget_usd,
                          daily_budget=tpl.daily_budget if not node_b else 0),
                    tenant_id)
            except ValueError as e:
                _fail_group(sname, snode, f"预算换算失败：{e}")
                continue'''
new = '''        # 组预算（ABO）：节点 USD 覆盖 > 模板默认；节点/模板可选 lifetime（总预算须排期，
        # 保存端已校验节点级；模板级 lifetime 在 _budget_guard_400 已拦无排期）。
        # CBO 组不带预算（系列级）。排期/投放方式/出价额/ROAS 节点覆盖 > 模板默认。
        node_btype = (snode.get("budget_type") or tpl.budget_type or "daily").lower()
        node_lt_usd = snode.get("lifetime_budget_usd") or tpl.lifetime_budget_usd
        adset_lifetime_fb = None
        try:
            if is_cbo:
                adset_budget_fb = camp_budget_fb
            elif node_btype == "lifetime":
                if not node_lt_usd:
                    _fail_group(sname, snode, "总预算模式未填总预算金额")
                    continue
                adset_lifetime_fb = _usd_to_account_minor(sdb, item.act_id, float(node_lt_usd), tenant_id)
                adset_budget_fb = 0
            else:
                node_b = snode.get("budget_usd")
                adset_budget_fb = _resolve_budget_fb(
                    sdb, item.act_id,
                    _view(budget_usd=float(node_b) if node_b else tpl.budget_usd,
                          daily_budget=tpl.daily_budget if not node_b else 0),
                    tenant_id)
        except ValueError as e:
            _fail_group(sname, snode, f"预算换算失败：{e}")
            continue
        s_sched_start = snode.get("schedule_start") or tpl.schedule_start or ""
        s_sched_end = snode.get("schedule_end") or tpl.schedule_end or ""
        s_pacing = snode.get("pacing") or tpl.pacing or ""
        _bid_usd = snode.get("bid_amount_usd")
        if _bid_usd in (None, ""):
            _bid_usd = tpl.bid_amount_usd
        try:
            s_bid_fb = (_usd_to_account_minor(sdb, item.act_id, float(_bid_usd), tenant_id)
                        if _bid_usd else None)
        except ValueError as e:
            _fail_group(sname, snode, f"出价额换算失败：{e}")
            continue
        s_min_roas = snode.get("minimum_roas")
        if s_min_roas in (None, ""):
            s_min_roas = tpl.minimum_roas'''
assert old in s, "tree_adset_budget"; s = s.replace(old, new, 1); edits.append("tree_adset_budget")

# ── 11. 树 runner：build_adset 调用点透传 ──
old = '''            optimization_goal=(snode.get("optimization_goal") or tpl.optimization_goal or ""),
            billing_event=(snode.get("billing_event") or tpl.billing_event or ""),
            destination_type_override=tpl.destination_type or "",
            extra=merged_adv or None)'''
new = '''            optimization_goal=(snode.get("optimization_goal") or tpl.optimization_goal or ""),
            billing_event=(snode.get("billing_event") or tpl.billing_event or ""),
            destination_type_override=tpl.destination_type or "",
            extra=merged_adv or None,
            budget_type=node_btype, lifetime_budget=adset_lifetime_fb,
            start_time=s_sched_start, end_time=s_sched_end, pacing=s_pacing,
            bid_amount=s_bid_fb,
            minimum_roas=(float(s_min_roas) if s_min_roas else None))'''
assert old in s, "tree_adset_call"; s = s.replace(old, new, 1); edits.append("tree_adset_call")

# ── 12. 树 runner：creative 描述（节点覆盖>模板）──
old = '''                    creative = build_creative(
                        page_id=_page_id, objective=tpl.objective, conversion_goal=tpl.conversion_goal,
                        landing_url=effective_url, headline=_headline, body=_body,
                        cta_type=(anode.get("cta_type") or tpl.cta_type or ""),
                        image_hash=image_hash, video_id=video_id,
                        lead_form_id=lead_form_id, welcome_message=welcome_msg)'''
new = '''                    creative = build_creative(
                        page_id=_page_id, objective=tpl.objective, conversion_goal=tpl.conversion_goal,
                        landing_url=effective_url, headline=_headline, body=_body,
                        cta_type=(anode.get("cta_type") or tpl.cta_type or ""),
                        image_hash=image_hash, video_id=video_id,
                        lead_form_id=lead_form_id, welcome_message=welcome_msg,
                        description=(anode.get("link_description") or tpl.link_description or ""))'''
assert old in s, "tree_creative"; s = s.replace(old, new, 1); edits.append("tree_creative")

# ── 13. 树预检：tree_out 每组补新字段 + 顶层补类别/排期 ──
old = '''        tree_out.append({
            "name": sname, "enabled": s_enabled,
            "budget_usd": float(node_b) if node_b else (t.budget_usd if not is_cbo else None),
            "budget_local_fb": adset_budget_fb,
            "audience_id": snode.get("audience_id") or 0,
            "optimization_goal": snode.get("optimization_goal") or "",
            "ads": ads_out,
        })'''
new = '''        tree_out.append({
            "name": sname, "enabled": s_enabled,
            "budget_usd": float(node_b) if node_b else (t.budget_usd if not is_cbo else None),
            "budget_local_fb": adset_budget_fb,
            "budget_type": (snode.get("budget_type") or t.budget_type or "daily"),
            "lifetime_budget_usd": (snode.get("lifetime_budget_usd") or t.lifetime_budget_usd),
            "schedule_start": (snode.get("schedule_start") or t.schedule_start or ""),
            "schedule_end": (snode.get("schedule_end") or t.schedule_end or ""),
            "pacing": (snode.get("pacing") or t.pacing or ""),
            "bid_amount_usd": (snode.get("bid_amount_usd") or t.bid_amount_usd),
            "minimum_roas": (snode.get("minimum_roas") or t.minimum_roas),
            "audience_id": snode.get("audience_id") or 0,
            "optimization_goal": snode.get("optimization_goal") or "",
            "ads": ads_out,
        })'''
assert old in s, "tree_pf"; s = s.replace(old, new, 1); edits.append("tree_pf")

io.open(p, "w", encoding="utf-8", newline="\n").write(s)
print("PART3:", edits)
