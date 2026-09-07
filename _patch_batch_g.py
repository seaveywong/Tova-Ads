# 批G 后端补丁：FB 创建流程 1:1 字段（排期/lifetime/pacing/出价/特殊类别/描述）全链透传
import io, re

edits = []
p = "backend/app/routers/launch_templates.py"
s = io.open(p, encoding="utf-8").read()

# ── 1. _tpl_dict 暴露新字段 ──
old = '''        "post_source": t.post_source or "new", "reuse_post_ref": t.reuse_post_ref or "",
        "structure": t.structure or "",'''
new = '''        "post_source": t.post_source or "new", "reuse_post_ref": t.reuse_post_ref or "",
        "structure": t.structure or "",
        "budget_type": t.budget_type or "daily", "lifetime_budget_usd": t.lifetime_budget_usd,
        "schedule_start": t.schedule_start or "", "schedule_end": t.schedule_end or "",
        "pacing": t.pacing or "", "bid_amount_usd": t.bid_amount_usd,
        "minimum_roas": t.minimum_roas, "special_ad_categories": t.special_ad_categories or "",
        "link_description": t.link_description or "",'''
assert old in s, "tpl_dict"; s = s.replace(old, new, 1); edits.append("tpl_dict")

# ── 2. _COPY_COLS ──
old = '''    "post_source", "reuse_post_ref", "structure",
]'''
new = '''    "post_source", "reuse_post_ref", "structure",
    "budget_type", "lifetime_budget_usd", "schedule_start", "schedule_end", "pacing",
    "bid_amount_usd", "minimum_roas", "special_ad_categories", "link_description",
]'''
assert old in s, "copy_cols"; s = s.replace(old, new, 1); edits.append("copy_cols")

# ── 3. TemplateIn 新字段 + 校验 ──
old = '''    post_source: str = "new"
    reuse_post_ref: str = ""
    structure: str = ""   # 1:1 三层结构 JSON（空 = 平铺模式；校验/规范化见 _validate_structure）
'''
new = '''    post_source: str = "new"
    reuse_post_ref: str = ""
    structure: str = ""   # 1:1 三层结构 JSON（空 = 平铺模式；校验/规范化见 _validate_structure）
    # FB 创建流程 1:1（0089 批G）
    budget_type: str = "daily"          # daily / lifetime
    lifetime_budget_usd: Optional[float] = None
    schedule_start: str = ""
    schedule_end: str = ""
    pacing: str = ""                    # ''=匀速 / accelerated
    bid_amount_usd: Optional[float] = None
    minimum_roas: Optional[float] = None
    special_ad_categories: str = ""     # JSON 数组串（CREDIT/EMPLOYMENT/HOUSING/...）
    link_description: str = ""

    _SPECIAL_CATS = {"CREDIT", "EMPLOYMENT", "HOUSING",
                     "SOCIAL_ISSUES_ELECTIONS_POLITICS", "FINANCIAL_PRODUCTS"}
    _BUDGET_MAX_LIFETIME_USD = 50000.0  # 总预算上限（多日累积，口径高于日预算 $5000）
    _DT_RE = re.compile(r"^\\d{4}-\\d{2}-\\d{2}([T ]\\d{2}:\\d{2}(:\\d{2})?)?(Z|[+-]\\d{2}:?\\d{2})?$")

    @field_validator("budget_type")
    @classmethod
    def _norm_budget_type(cls, v: str) -> str:
        v = (v or "daily").strip().lower()
        return v if v in ("daily", "lifetime") else "daily"

    @field_validator("pacing")
    @classmethod
    def _norm_pacing(cls, v: str) -> str:
        v = (v or "").strip().lower()
        return v if v in ("", "accelerated") else ""

    @field_validator("lifetime_budget_usd")
    @classmethod
    def _cap_lifetime(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v > cls._BUDGET_MAX_LIFETIME_USD:
            raise ValueError(f"总预算超安全上限 ${cls._BUDGET_MAX_LIFETIME_USD:.0f}，请分系列分步投放")
        return v

    @field_validator("schedule_start", "schedule_end")
    @classmethod
    def _check_dt(cls, v: str) -> str:
        v = (v or "").strip()
        if v and not cls._DT_RE.match(v):
            raise ValueError("排期时间格式应为 YYYY-MM-DD 或 YYYY-MM-DD HH:mm")
        return v

    @field_validator("special_ad_categories")
    @classmethod
    def _check_cats(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            return ""
        try:
            cats = json.loads(v)
        except Exception:
            raise ValueError("特殊广告类别需为 JSON 数组（如 [\\"CREDIT\\"]）")
        if not isinstance(cats, list) or any(c not in cls._SPECIAL_CATS for c in cats):
            raise ValueError(f"特殊广告类别仅支持：{sorted(cls._SPECIAL_CATS)}")
        return json.dumps(sorted(set(cats)))
'''
assert old in s, "template_in"; s = s.replace(old, new, 1); edits.append("template_in")

# ── 4. _validate_structure：组节点新覆盖键 + 广告节点 link_description ──
old = '''                "post_source": post_source,
                "reuse_post_ref": reuse_ref,
            })'''
new = '''                "post_source": post_source,
                "reuse_post_ref": reuse_ref,
                "link_description": str(ad.get("link_description") or "")[:200],
            })'''
assert old in s, "node_desc"; s = s.replace(old, new, 1); edits.append("node_desc")

old = '''            "advanced_config": str(adset.get("advanced_config") or ""),
            "ads": out_ads,
        })'''
new = '''            "advanced_config": str(adset.get("advanced_config") or ""),
            "budget_type": ("lifetime" if str(adset.get("budget_type") or "").lower() == "lifetime" else "daily"),
            "lifetime_budget_usd": (float(adset["lifetime_budget_usd"])
                                    if adset.get("lifetime_budget_usd") not in (None, "", 0) else None),
            "schedule_start": str(adset.get("schedule_start") or "")[:25],
            "schedule_end": str(adset.get("schedule_end") or "")[:25],
            "pacing": ("accelerated" if str(adset.get("pacing") or "").lower() == "accelerated" else ""),
            "bid_amount_usd": (float(adset["bid_amount_usd"])
                               if adset.get("bid_amount_usd") not in (None, "", 0) else None),
            "minimum_roas": (float(adset["minimum_roas"])
                             if adset.get("minimum_roas") not in (None, "", 0) else None),
            "ads": out_ads,
        })
        # 组级总预算必须配排期（FB 硬约束：lifetime_budget 需 start/end）；排期格式粗校验
        if out_adsets[-1]["budget_type"] == "lifetime":
            _ss, _se = out_adsets[-1]["schedule_start"], out_adsets[-1]["schedule_end"]
            if not (_ss and _se):
                return {}, f"广告组「{name or len(out_adsets)}」总预算必须设置排期（开始+结束时间）"
            if _ss > _se:
                return {}, f"广告组「{name or len(out_adsets)}」排期开始晚于结束"'''
assert old in s, "node_sched"; s = s.replace(old, new, 1); edits.append("node_sched")

io.open(p, "w", encoding="utf-8", newline="\n").write(s)
print("PART1:", edits)
