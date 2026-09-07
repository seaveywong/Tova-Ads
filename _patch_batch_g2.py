# 批G 后端补丁 PART2：守卫/换算/部署链透传
import io

edits = []
p = "backend/app/routers/launch_templates.py"
s = io.open(p, encoding="utf-8").read()

# ── 5. _budget_guard_400：lifetime 口径 + 模板级排期约束 ──
old = '''    if (t.budget_mode or "ABO").upper() != "ABO":
        return
    adsets = _parse_structure(t)
    if not adsets:
        return'''
new = '''    # lifetime（总预算）口径：必须有排期 + 上限 $50000（TemplateIn 已拦保存，此处兜底直改库的行）
    if (t.budget_type or "daily") == "lifetime":
        if not ((t.lifetime_budget_usd or 0) > 0):
            raise HTTPException(400, "总预算模式必须填写总预算金额")
        if not (t.schedule_start and t.schedule_end):
            raise HTTPException(400, "总预算必须设置排期（开始+结束时间）——FB 硬约束")
        if t.lifetime_budget_usd > 50000:
            raise HTTPException(400, "总预算超安全上限 $50000")
    if (t.budget_mode or "ABO").upper() != "ABO":
        return
    adsets = _parse_structure(t)
    if not adsets:
        return'''
assert old in s, "guard"; s = s.replace(old, new, 1); edits.append("budget_guard")

# ── 6. 换算 helper：USD → 该账户本币 minor units（预算/出价共用）──
old = '''# ── TikTok 分支 helper（TK P3；platform='tt' 才会走到，FB 路径零改动）──'''
new = '''def _usd_to_account_minor(sdb, act_id: str, usd: float, tenant_id: int) -> int:
    """USD 金额 → 该账户本币最小单位（预算/出价额换算共用——与 _resolve_budget_fb 同汇率管道）。
    缺汇率抛 ValueError（调用方消化为组级/广告级失败）。"""
    acc = sdb.query(Account).filter(Account.tenant_id == tenant_id,
                                    Account.act_id == act_id).first()
    currency = (acc.currency if acc else "USD") or "USD"
    cr = sdb.query(CurrencyRate).filter(CurrencyRate.code == currency.upper()).first()
    if not cr and currency.upper() != "USD":
        raise ValueError(f"缺少 {currency} 汇率（fx_sync 未同步该币种）")
    return usd_to_fb_amount(float(usd), currency, cr.rate if cr else 1.0)


# ── TikTok 分支 helper（TK P3；platform='tt' 才会走到，FB 路径零改动）──'''
assert old in s, "helper"; s = s.replace(old, new, 1); edits.append("usd_minor helper")

io.open(p, "w", encoding="utf-8", newline="\n").write(s)
print("PART2a:", edits)
