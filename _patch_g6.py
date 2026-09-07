import io
edits = []
p = "backend/app/routers/launch_templates.py"
s = io.open(p, encoding="utf-8").read()

# 1) _budget_guard_400：lifetime 模式免日预算（总预算块自己校验）
old = '''    if not ((t.budget_usd or 0) > 0 or (t.daily_budget or 0) > 0):
        raise HTTPException(400, "模板未配置预算，请先在模板编辑器填写日预算再部署")'''
new = '''    _lt_mode = (t.budget_type or "daily") == "lifetime"
    if not _lt_mode and not ((t.budget_usd or 0) > 0 or (t.daily_budget or 0) > 0):
        raise HTTPException(400, "模板未配置预算，请先在模板编辑器填写日预算再部署")
    if _lt_mode and not ((t.lifetime_budget_usd or 0) > 0 or (t.budget_usd or 0) > 0):
        raise HTTPException(400, "总预算模式未填写总预算金额")'''
assert old in s, "guard"; s = s.replace(old, new, 1); edits.append("guard")

# 2) 平铺 runner：lifetime 跳过日预算解析
old = '''    page_id = item.page_id or tpl.page_id
    pixel_id = item.pixel_id or tpl.pixel_id
    daily_budget_fb = _resolve_budget_fb(sdb, item.act_id, tpl, tenant_id)'''
new = '''    page_id = item.page_id or tpl.page_id
    pixel_id = item.pixel_id or tpl.pixel_id
    # lifetime 模式不解析日预算（无 budget_usd 也能部署；总预算在下方换算）
    daily_budget_fb = (0 if (tpl.budget_type or "daily") == "lifetime"
                       else _resolve_budget_fb(sdb, item.act_id, tpl, tenant_id))'''
assert old in s, "runner"; s = s.replace(old, new, 1); edits.append("runner")

# 3) 平铺预检：同分支
old = '''    try:
        daily_budget_fb = _resolve_budget_fb(db, body.act_id, t, user.tenant_id)
    except ValueError as e:
        logging.getLogger("toveads.launch").warning(f"preflight budget resolve failed: {e}")
        raise HTTPException(400, "预算换算失败：账户币种缺少汇率，请在系统设置配置汇率或改用 USD 模板")'''
new = '''    try:
        daily_budget_fb = (0 if (t.budget_type or "daily") == "lifetime"
                           else _resolve_budget_fb(db, body.act_id, t, user.tenant_id))
    except ValueError as e:
        logging.getLogger("toveads.launch").warning(f"preflight budget resolve failed: {e}")
        raise HTTPException(400, "预算换算失败：账户币种缺少汇率，请在系统设置配置汇率或改用 USD 模板")'''
assert old in s, "pf"; s = s.replace(old, new, 1); edits.append("pf")

io.open(p, "w", encoding="utf-8", newline="\n").write(s)
print("PART6:", edits)
