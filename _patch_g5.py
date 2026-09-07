import io, re as _re
p = "backend/app/routers/launch_templates.py"
s = io.open(p, encoding="utf-8").read()

old = '''    _SPECIAL_CATS = {"CREDIT", "EMPLOYMENT", "HOUSING",
                     "SOCIAL_ISSUES_ELECTIONS_POLITICS", "FINANCIAL_PRODUCTS"}
    _BUDGET_MAX_LIFETIME_USD = 50000.0  # 总预算上限（多日累积，口径高于日预算 $5000）
    _DT_RE = _re.compile(r"\\d{4}-\\d{2}-\\d{2}([T ]\\d{2}:\\d{2}(:\\d{2})?)?(Z|[+-]\\d{2}:?\\d{2})?$")
'''
if old not in s:
    # 兼容实际写入形态（regex 部分可能无 ^ 前缀差异）——定位类属性行块
    i = s.index("    _SPECIAL_CATS = ")
    j = s.index("\n\n", i)
    old = s[i:j]
s = s.replace(old, "", 1)
s = s.replace("cls._BUDGET_MAX_LIFETIME_USD", "_BUDGET_MAX_LIFETIME_USD")
s = s.replace("cls._SPECIAL_CATS", "_SPECIAL_CATS")
s = s.replace("cls._DT_RE", "_DT_RE")
anchor = "_BUDGET_MAX_USD = 5000.0\n"
assert anchor in s
s = s.replace(anchor, anchor +
    "# 批G（0089）：总预算上限（多日累积）/特殊广告类别白名单/排期格式（模块级——pydantic 类内下划线属性会被当 ModelPrivateAttr）\n"
    "_BUDGET_MAX_LIFETIME_USD = 50000.0\n"
    "_SPECIAL_CATS = {\"CREDIT\", \"EMPLOYMENT\", \"HOUSING\",\n"
    "                 \"SOCIAL_ISSUES_ELECTIONS_POLITICS\", \"FINANCIAL_PRODUCTS\"}\n"
    "_DT_RE = _re.compile(r\"^\\d{4}-\\d{2}-\\d{2}([T ]\\d{2}:\\d{2}(:\\d{2})?)?(Z|[+-]\\d{2}:?\\d{2})?$\")\n", 1)
io.open(p, "w", encoding="utf-8", newline="\n").write(s)
print("const hoisted ok")
