"""目标感知 FB 广告参数构建器（doc 02 + 1.0 经验 + 取长补短）。

根据 objective + conversion_goal 自动构造 Campaign/AdSet/Ad 的正确参数。
覆盖全部主流目标：购物/潜在客户/互动(主页赞)/流量/消息。
"""
from typing import Any

# ── 目标归一化（1.0 经验：旧版名 → 新版名）──
_OBJ_NORMALIZE = {
    "MESSAGES": "OUTCOME_ENGAGEMENT",
    "OUTCOME_MESSAGES": "OUTCOME_ENGAGEMENT",
    "OUTCOME_MESSAGING": "OUTCOME_ENGAGEMENT",
    "CONVERSIONS": "OUTCOME_SALES",
    "OUTCOME_CONVERSIONS": "OUTCOME_SALES",
    "LINK_CLICKS": "OUTCOME_TRAFFIC",
    "LEAD_GENERATION": "OUTCOME_LEADS",
}

# ── (objective, conversion_goal) → optimization_goal 映射（1.0 实测验证）──
_OPT_GOAL_MAP = {
    "OUTCOME_SALES": {
        "offsite_conversions": "OFFSITE_CONVERSIONS",
        "": "OFFSITE_CONVERSIONS",  # 默认
    },
    "OUTCOME_LEADS": {
        "lead_generation": "LEAD_GENERATION",  # Instant Forms → ON_AD
        "offsite_conversions": "OFFSITE_CONVERSIONS",  # 网站线索 → WEBSITE
        "": "LEAD_GENERATION",  # 默认
    },
    "OUTCOME_ENGAGEMENT": {
        "page_likes": "PAGE_LIKES",
        "post_engagement": "POST_ENGAGEMENT",
        "link_clicks": "LINK_CLICKS",
        "reach": "REACH",
        "impressions": "IMPRESSIONS",
        "conversations": "CONVERSATIONS",
        "landing_page_views": "LANDING_PAGE_VIEWS",
        "messaging_purchase_conversion": "MESSAGING_PURCHASE_CONVERSION",
        "messaging_appointment_conversion": "MESSAGING_APPOINTMENT_CONVERSION",
        "": "REACH",  # 默认
    },
    "OUTCOME_TRAFFIC": {
        "link_clicks": "LINK_CLICKS",
        "landing_page_views": "LANDING_PAGE_VIEWS",
        "reach": "REACH",
        "impressions": "IMPRESSIONS",
        "conversations": "CONVERSATIONS",
        "": "LINK_CLICKS",  # 默认
    },
    "OUTCOME_AWARENESS": {
        "reach": "REACH",
        "impressions": "IMPRESSIONS",
        "": "REACH",
    },
}


def normalize_objective(objective: str) -> str:
    return _OBJ_NORMALIZE.get(objective, objective)


# ══════════════════════════════════════════════════════════════════════════
# 转化位置矩阵（批次 I · 2026-09-08）：objective → conv_location →
# (destination_type, optimization_goal, promoted_object 形态)
#
# 一套词表统一三处旧口径（盘点矩阵 B 实锤的死链根因）：
#   ① UI「转化目标」下拉（custom_event_type 词表：Purchase/AddToCart/...）→ conversion_goal 列，
#      经 custom_event_from_goal() 进 promoted_object.custom_event_type（不再恒 PURCHASE/LEAD）；
#   ② _OPT_GOAL_MAP 旧 key（offsite_conversions/...）→ conv_location="" 时的兼容推导路径（存量行为不变）；
#   ③ is_messaging 门 → resolve_adset_destination() 派生 destination_type/optimization_goal 后判定。
# 依据：蓝图_FB广告管理器创建流 §2.1/§5.2（官API v25 实证）+ 方案_版位与转化位置 §3.3 采用矩阵。
# ❓ phone_call / instagram_direct 的 optimization_goal 组合未经真部署实测（蓝图无逐格矩阵）。
# ══════════════════════════════════════════════════════════════════════════

# conv_location 合法值（按 objective）。对齐 Meta 官方「Available Conversion Locations by Objective」
# 矩阵（business/help/2035196643270，2026-09 核对）：销量无单独「通话」位（只有 API 未确认的
# 「网站和通话」组合位）；流量下的 Instagram 位是「Instagram 主页」（进主页资料页）而非 IG 私信
# （IG 私信只出现在 潜客「Instagram」与 互动「消息应用」）；app 链路未建故不含应用位。
CONV_LOCATIONS_BY_OBJECTIVE = {
    "OUTCOME_SALES": {"website", "messenger", "whatsapp"},
    "OUTCOME_LEADS": {"website", "on_ad", "on_ad_messenger", "messenger",
                      "whatsapp", "instagram_direct", "phone_call"},
    "OUTCOME_TRAFFIC": {"website", "messenger", "whatsapp", "instagram_profile", "phone_call"},
    "OUTCOME_ENGAGEMENT": {"website", "on_page", "messenger", "whatsapp", "instagram_direct"},
    "OUTCOME_AWARENESS": set(),        # 无转化位置（官方：广告中，唯一且自动）
    "OUTCOME_APP_PROMOTION": set(),    # 应用链路未建（审计 C3）
}
CONV_LOCATION_ALL = {loc for s in CONV_LOCATIONS_BY_OBJECTIVE.values() for loc in s}

# (objective, conv_location) → (destination_type, 默认 optimization_goal, promoted_object 形态)
# promoted 形态：pixel={pixel_id,custom_event_type} / page={page_id} / None=不带
_CONV_MATRIX = {
    ("OUTCOME_SALES", "website"):     ("WEBSITE", "OFFSITE_CONVERSIONS", "pixel"),
    ("OUTCOME_SALES", "messenger"):   ("MESSENGER", "MESSAGING_PURCHASE_CONVERSION", "page"),
    ("OUTCOME_SALES", "whatsapp"):    ("WHATSAPP", "CONVERSATIONS", "page"),
    ("OUTCOME_LEADS", "website"):     ("WEBSITE", "OFFSITE_CONVERSIONS", "pixel"),
    ("OUTCOME_LEADS", "on_ad"):       ("ON_AD", "LEAD_GENERATION", "page"),
    # Leads 组合位「即时表单+Messenger」（蓝图 §2.1：二选一自动分配）：API 侧与 on_ad 同构
    # （ON_AD+LEAD_GENERATION），分流发生在 FB 投放侧；创意层同时挂表单+问答模板待后续批。
    ("OUTCOME_LEADS", "on_ad_messenger"): ("ON_AD", "LEAD_GENERATION", "page"),
    ("OUTCOME_LEADS", "messenger"):   ("MESSENGER", "LEAD_GENERATION", "page"),
    ("OUTCOME_LEADS", "whatsapp"):    ("WHATSAPP", "CONVERSATIONS", "page"),
    # 官方：Leads 的 Instagram 位优化 LEAD_FROM_IG_DIRECT（IG 私信收线索），非 CONVERSATIONS
    ("OUTCOME_LEADS", "instagram_direct"): ("INSTAGRAM_DIRECT", "LEAD_FROM_IG_DIRECT", "page"),
    # 官方：Calls 位优化 QUALITY_CALL、billing IMPRESSIONS（Call Ads 指南 v26）
    ("OUTCOME_LEADS", "phone_call"):  ("PHONE_CALL", "QUALITY_CALL", "page"),
    ("OUTCOME_TRAFFIC", "website"):   ("WEBSITE", "LINK_CLICKS", None),
    ("OUTCOME_TRAFFIC", "messenger"): ("MESSENGER", "CONVERSATIONS", "page"),
    ("OUTCOME_TRAFFIC", "whatsapp"):  ("WHATSAPP", "CONVERSATIONS", "page"),
    # 官方：Traffic 的 Instagram 位 = Instagram 主页（进资料页），destination INSTAGRAM_PROFILE
    ("OUTCOME_TRAFFIC", "instagram_profile"): ("INSTAGRAM_PROFILE", "VISIT_INSTAGRAM_PROFILE", "page"),
    ("OUTCOME_TRAFFIC", "phone_call"): ("PHONE_CALL", "LINK_CLICKS", "page"),
    ("OUTCOME_ENGAGEMENT", "website"): ("WEBSITE", "LINK_CLICKS", None),
    ("OUTCOME_ENGAGEMENT", "on_page"): ("ON_PAGE", "PAGE_LIKES", "page"),
    ("OUTCOME_ENGAGEMENT", "messenger"): ("MESSENGER", "CONVERSATIONS", "page"),
    ("OUTCOME_ENGAGEMENT", "whatsapp"): ("WHATSAPP", "CONVERSATIONS", "page"),
    ("OUTCOME_ENGAGEMENT", "instagram_direct"): ("INSTAGRAM_DIRECT", "CONVERSATIONS", "page"),
}

# 优化目标 × objective 兼容表（蓝图 §2.2 成效目标全表 + §5.2 CTM/CTW 实证枚举交集；
# 校验树节点 optimization_goal 用——非法值保存时 422，不再等 FB 400）
OPT_GOALS_BY_OBJECTIVE = {
    "OUTCOME_AWARENESS": {"REACH", "IMPRESSIONS", "THRUPLAY", "TWO_SECOND_CONTINUOUS_VIDEO_VIEWS"},
    "OUTCOME_TRAFFIC": {"LINK_CLICKS", "LANDING_PAGE_VIEWS", "REACH", "IMPRESSIONS", "CONVERSATIONS",
                        "VISIT_INSTAGRAM_PROFILE"},
    "OUTCOME_ENGAGEMENT": {"REACH", "IMPRESSIONS", "LINK_CLICKS", "LANDING_PAGE_VIEWS",
                           "POST_ENGAGEMENT", "PAGE_LIKES", "CONVERSATIONS",
                           "MESSAGING_PURCHASE_CONVERSION", "MESSAGING_APPOINTMENT_CONVERSION",
                           "THRUPLAY", "TWO_SECOND_CONTINUOUS_VIDEO_VIEWS", "EVENT_RESPONSES",
                           "OFFSITE_CONVERSIONS"},
    "OUTCOME_LEADS": {"LEAD_GENERATION", "QUALITY_LEAD", "OFFSITE_CONVERSIONS", "CONVERSATIONS",
                      "LINK_CLICKS", "LANDING_PAGE_VIEWS", "REACH", "IMPRESSIONS",
                      "LEAD_FROM_IG_DIRECT", "QUALITY_CALL"},
    "OUTCOME_SALES": {"OFFSITE_CONVERSIONS", "VALUE", "CONVERSATIONS", "LINK_CLICKS",
                      "LANDING_PAGE_VIEWS", "IMPRESSIONS", "REACH", "MESSAGING_PURCHASE_CONVERSION"},
    "OUTCOME_APP_PROMOTION": {"APP_INSTALLS", "VALUE", "LINK_CLICKS"},
}

# 优化目标 × conv_location 兼容表（蓝图 §5.2 CTW 按目标枚举 + §2.2；节点同时显式设置两者时校验）
OPT_GOALS_BY_LOCATION = {
    "website": {"OFFSITE_CONVERSIONS", "VALUE", "LINK_CLICKS", "LANDING_PAGE_VIEWS",
                "REACH", "IMPRESSIONS", "POST_ENGAGEMENT"},
    "on_ad": {"LEAD_GENERATION", "QUALITY_LEAD", "CONVERSATIONS"},
    "on_ad_messenger": {"LEAD_GENERATION", "QUALITY_LEAD", "CONVERSATIONS"},
    "messenger": {"CONVERSATIONS", "LEAD_GENERATION", "QUALITY_LEAD",
                  "MESSAGING_PURCHASE_CONVERSION", "LINK_CLICKS"},
    "whatsapp": {"CONVERSATIONS", "OFFSITE_CONVERSIONS", "LINK_CLICKS", "IMPRESSIONS",
                 "REACH", "LANDING_PAGE_VIEWS", "POST_ENGAGEMENT"},
    "instagram_direct": {"CONVERSATIONS", "LEAD_FROM_IG_DIRECT"},
    "instagram_profile": {"VISIT_INSTAGRAM_PROFILE", "LINK_CLICKS", "LANDING_PAGE_VIEWS",
                          "IMPRESSIONS", "REACH"},
    "phone_call": {"LINK_CLICKS", "QUALITY_CALL", "CONVERSATIONS", "REACH", "IMPRESSIONS"},
    "on_page": {"PAGE_LIKES", "REACH", "IMPRESSIONS"},
}

# conv_location="" 时的兼容推导（存量行为原样保留 + 消息类覆盖组合补全——蓝图 §5.2）：
# (objective, optimization_goal) → destination_type（与下方 build_adset 旧分支一一对应）
_LEGACY_DEST = {
    ("OUTCOME_SALES", "OFFSITE_CONVERSIONS"): "WEBSITE",
    ("OUTCOME_SALES", "VALUE"): "WEBSITE",
    ("OUTCOME_SALES", "LINK_CLICKS"): "WEBSITE",
    ("OUTCOME_SALES", "LANDING_PAGE_VIEWS"): "WEBSITE",
    ("OUTCOME_SALES", "CONVERSATIONS"): "MESSENGER",
    ("OUTCOME_SALES", "MESSAGING_PURCHASE_CONVERSION"): "MESSENGER",
    ("OUTCOME_LEADS", "LEAD_GENERATION"): "ON_AD",
    ("OUTCOME_LEADS", "OFFSITE_CONVERSIONS"): "WEBSITE",
    ("OUTCOME_LEADS", "CONVERSATIONS"): "MESSENGER",
    ("OUTCOME_ENGAGEMENT", "PAGE_LIKES"): "ON_PAGE",
    ("OUTCOME_ENGAGEMENT", "CONVERSATIONS"): "MESSENGER",
    ("OUTCOME_ENGAGEMENT", "MESSAGING_PURCHASE_CONVERSION"): "MESSENGER",
    ("OUTCOME_ENGAGEMENT", "MESSAGING_APPOINTMENT_CONVERSION"): "MESSENGER",
    ("OUTCOME_ENGAGEMENT", "LINK_CLICKS"): "WEBSITE",
    ("OUTCOME_ENGAGEMENT", "LANDING_PAGE_VIEWS"): "WEBSITE",
    ("OUTCOME_TRAFFIC", "LINK_CLICKS"): "WEBSITE",
    ("OUTCOME_TRAFFIC", "LANDING_PAGE_VIEWS"): "WEBSITE",
    ("OUTCOME_TRAFFIC", "CONVERSATIONS"): "MESSENGER",
}

# UI 词表（转化事件，camelCase 标准事件名）→ FB promoted_object.custom_event_type 枚举
# （蓝图 §2.1 各目标的网站转化事件全集；词表归一后 conversion_goal 列存 UI 原值，部署时经此映射）
# key = 去掉非字母后的大写形态（AddToCart / add_to_cart / ADD_TO_CART 统一命中）
_CUSTOM_EVENT_MAP = {
    "PURCHASE": "PURCHASE", "ADDTOCART": "ADD_TO_CART", "ADDTOWISHLIST": "ADD_TO_WISHLIST",
    "INITIATECHECKOUT": "INITIATE_CHECKOUT", "ADDPAYMENTINFO": "ADD_PAYMENT_INFO",
    "COMPLETEREGISTRATION": "COMPLETE_REGISTRATION", "LEAD": "LEAD", "SUBSCRIBE": "SUBSCRIBE",
    "CONTACT": "CONTACT", "STARTTRIAL": "START_TRIAL", "SEARCH": "SEARCH",
    "VIEWCONTENT": "VIEW_CONTENT", "SCHEDULE": "SCHEDULE", "DONATE": "DONATE",
    "FINDLOCATION": "FIND_LOCATION", "CUSTOMIZEPRODUCT": "CUSTOMIZE_PRODUCT",
    "SUBMITAPPLICATION": "SUBMIT_APPLICATION",
}


def custom_event_from_goal(conversion_goal: str) -> str:
    """conversion_goal（UI 转化事件词表 / FB 大写枚举）→ custom_event_type。
    旧 _OPT_GOAL_MAP key（offsite_conversions 等目的地语义）不是事件 → 返空串。"""
    import re as _re
    cg = (conversion_goal or "").strip()
    if not cg:
        return ""
    return _CUSTOM_EVENT_MAP.get(_re.sub(r"[^A-Za-z]", "", cg).upper(), "")


def resolve_adset_destination(objective: str, conv_location: str = "",
                              conversion_goal: str = "", optimization_goal: str = "") -> tuple[str, str]:
    """统一派生 (destination_type, optimization_goal)——树 runner / deploy_one_account 的
    is_messaging 门、CTA app_destination 都以此为准（不再各自查 conversion_goal 原始词表）。
    conv_location 非空 → 矩阵派生（显式 optimization_goal 覆盖目标值）；
    空 → 存量推导路径（get_optimization_goal + _LEGACY_DEST，行为与旧版一致）。"""
    obj = normalize_objective(objective)
    loc = (conv_location or "").strip().lower()
    opt = (optimization_goal or "").strip()
    if loc:
        row = _CONV_MATRIX.get((obj, loc))
        if not row:
            raise ValueError(f"转化位置「{loc}」不适用于目标 {obj}")
        return row[0], (opt or row[1])
    og = opt or get_optimization_goal(obj, conversion_goal)
    return _LEGACY_DEST.get((obj, og), ""), og


def is_messaging_destination(destination_type: str, optimization_goal: str) -> bool:
    """消息类广告判定（is_messaging 门统一口径）：目的地为消息类，或成效目标为会话/消息转化。"""
    dt = (destination_type or "").upper()
    og = (optimization_goal or "").upper()
    return (dt in ("MESSENGER", "WHATSAPP", "INSTAGRAM_DIRECT")
            or og in ("CONVERSATIONS", "MESSAGING_PURCHASE_CONVERSION",
                      "MESSAGING_APPOINTMENT_CONVERSION"))


# ── 受众定向构造（审计项目16，v1 仅兴趣受众）──
def build_targeting(
    countries: list[str] | None = None,
    interests: list[dict] | None = None,
    age_min: int = 18,
    age_max: int = 65,
    gender: int = 0,
    strategy: str = "broad_interest",
) -> dict:
    """构造 AdSet.targeting（审计项目16：v1 仅 flexible_spec 兴趣，无 custom/lookalike）。

    interests: [{"id":..., "name":...}, ...]（来自 FB adinterest 搜索）
    strategy:
      broad_interest = 兴趣 + 默认宽定向（有 interests 才加 flexible_spec）
      interest_only  = 仅兴趣
      broad_only     = 仅国家/年龄/性别（忽略 interests）
    gender: 0=all 1=male 2=female
    """
    countries = countries or ["US"]
    targeting: dict[str, Any] = {
        "geo_locations": {"countries": countries},
        "age_min": age_min,
        "age_max": age_max,
        "genders": [gender] if gender in (1, 2) else [],
    }
    if strategy != "broad_only" and interests:
        # flexible_spec: [{interests:[{id,name}]}]
        flex_interests = [{"id": str(i["id"]), "name": i.get("name", "")}
                          for i in interests if i.get("id")]
        if flex_interests:
            targeting["flexible_spec"] = [{"interests": flex_interests}]
    return targeting


def get_optimization_goal(objective: str, conversion_goal: str = "") -> str:
    obj = normalize_objective(objective)
    cg = (conversion_goal or "").lower().strip()
    goals = _OPT_GOAL_MAP.get(obj, {})
    return goals.get(cg, goals.get("", "REACH"))


# ── Campaign payload ──
def build_campaign(
    name: str,
    objective: str,
    daily_budget: int | None = None,
    budget_mode: str = "ABO",
    bid_strategy: str = "LOWEST_COST_WITHOUT_CAP",
    target_cpa: float | None = None,
    lifetime_budget: int | None = None,
    special_ad_categories: list | None = None,
    minimum_roas: float | None = None,
    spend_cap: int | None = None,
) -> dict:
    obj = normalize_objective(objective)
    payload: dict[str, Any] = {
        "name": name,
        "objective": obj,
        "status": "ACTIVE",
        # 特殊广告类别（信贷/就业/住房/社会议题选举——投放对应行业广告是 FB 合规硬要求，
        # 声明后定向选项会被强制收窄，由用户显式选择，默认空）
        "special_ad_categories": special_ad_categories or [],
        "buying_type": "AUCTION",
    }

    # 系列支出上限（账户本币 minor units，调用方按汇率换算好）：累计花费达到即停整系列
    # ——与预算（日/总，控制投放节奏）语义不同。可选，None/0=不限。
    if spend_cap is not None and int(spend_cap) > 0:
        payload["spend_cap"] = str(int(spend_cap))

    if budget_mode.upper() == "CBO":
        # CBO 预算在系列级：日预算/总预算二选一（总预算必须配排期，调用方校验）
        if lifetime_budget:
            payload["lifetime_budget"] = str(lifetime_budget)
        elif daily_budget and daily_budget > 0:
            payload["daily_budget"] = str(daily_budget)
        else:
            raise ValueError("CBO 模式必须配置系列预算（日预算或总预算）")
        # CBO: bid_strategy 在系列级（最低成本/成本上限/竞价上限/最小ROAS）
        payload["bid_strategy"] = bid_strategy if bid_strategy in (
            "LOWEST_COST_WITHOUT_CAP", "LOWEST_COST_WITH_BID_CAP", "COST_CAP", "BID_CAP",
            "MIN_ROAS_WITHOUT_CAP", "LOWEST_COST_WITH_MIN_ROAS") else "LOWEST_COST_WITHOUT_CAP"
        if target_cpa and float(target_cpa) > 0 and bid_strategy in ("COST_CAP", "BID_CAP"):
            payload["bid_strategy"] = "COST_CAP"
    else:
        # ABO: 广告组级预算
        payload["is_adset_budget_sharing_enabled"] = False

    return payload


# ── AdSet payload ──
def build_adset(
    name: str,
    campaign_id: str,
    daily_budget: int,
    objective: str,
    conversion_goal: str = "",
    page_id: str = "",
    pixel_id: str = "",
    landing_url: str = "",
    conversion_event: str = "",             # 显式 custom_event_type（空=按 conversion_goal 映射，再空=目标默认）
    bid_strategy: str = "LOWEST_COST_WITHOUT_CAP",
    target_cpa: float | None = None,
    budget_mode: str = "ABO",
    targeting: dict | None = None,
    dsa_beneficiary: str = "",
    dsa_payor: str = "",
    optimization_goal: str = "",            # 显式覆盖（空=按 conv_location 矩阵 / objective+conversion_goal 推）
    billing_event: str = "",                # 显式覆盖（空=IMPRESSIONS）
    destination_type_override: str = "",    # 显式覆盖 destination_type（仅 conv_location 为空时生效——批次I 修隐患A）
    extra: dict | None = None,              # 高级字段（advanced_config JSON），深合并进 payload
    budget_type: str = "daily",             # daily / lifetime（总预算必须配排期——端点守卫先拦）
    lifetime_budget: int | None = None,     # budget_type=lifetime 时用（本币 minor units）
    start_time: str = "",                   # 排期开始（'YYYY-MM-DD HH:mm' 或 ISO；空=不传=立即）
    end_time: str = "",                     # 排期结束
    pacing: str = "",                       # ""=standard 匀速 / accelerated 加速投放
    bid_amount: int | None = None,          # COST_CAP/BID_CAP 出价额（本币 minor units）
    minimum_roas: float | None = None,      # 最小 ROAS（SALES 用）
    conv_location: str = "",                # 转化位置（组节点字段；空=存量推导路径，行为不变）
    placements: dict | None = None,         # 结构化版位 {publisher_platforms,device_platforms,facebook/instagram/messenger_positions}；None=省略（Advantage+ 自动版位）
    whatsapp_phone_number: str = "",        # CTW 显式号码（仅 ENGAGEMENT 下进 promoted_object；蓝图：Traffic/Sales 随主页不传）
    advantage_audience: bool = True,        # Advantage+ 受众（组级）：FB 默认开=省略字段；显式 False=原始受众（targeting_automation.advantage_audience=0，手动定向全量生效）
) -> dict:
    obj = normalize_objective(objective)
    loc = (conv_location or "").strip().lower()
    if loc and loc not in CONV_LOCATION_ALL:
        raise ValueError(f"未知转化位置「{conv_location}」")
    if loc and (obj, loc) not in _CONV_MATRIX:
        raise ValueError(f"转化位置「{loc}」不适用于目标 {obj}")
    opt_override = (optimization_goal or "").strip()
    dest_type = ""
    if loc:
        dest_type, matrix_goal, _kind = _CONV_MATRIX[(obj, loc)]
        opt_goal = opt_override or matrix_goal
    else:
        opt_goal = opt_override or get_optimization_goal(obj, conversion_goal)

    payload: dict[str, Any] = {
        "name": name,
        "campaign_id": campaign_id,
        "billing_event": billing_event.strip() if billing_event and billing_event.strip() else "IMPRESSIONS",
        "optimization_goal": opt_goal,
        "bid_strategy": bid_strategy,
        # 深拷贝 targeting：build_adset 内会 mutate（MESSENGER 加 publisher_platforms），不能污染调用方的共享 dict（多账户部署循环）
        "targeting": _deep_copy(targeting) if targeting else {"geo_locations": {"countries": ["US"]}, "age_min": 18, "age_max": 65},
        "status": "ACTIVE",
    }

    # Advantage+ 受众开关在 extra 深合并后统一写入（见下方 return 前）——批V。

    # 受益人/付款人披露（EU/泰国/印度/巴西/台湾/澳洲/新加坡等强制；不填 FB 会拒）
    if dsa_beneficiary:
        payload["dsa_beneficiary"] = dsa_beneficiary
    if dsa_payor:
        payload["dsa_payor"] = dsa_payor

    # ABO: 广告组级预算（日/总二选一；lifetime 必须配排期——端点守卫先拦）
    if budget_mode.upper() != "CBO":
        if budget_type.lower() == "lifetime" and lifetime_budget:
            payload["lifetime_budget"] = str(lifetime_budget)
        else:
            payload["daily_budget"] = str(daily_budget)

    # 排期（ISO 化：'YYYY-MM-DD HH:mm' → 'T'；带时区偏移的原样透传——FB 用广告账户时区解释无偏移时间）
    if start_time:
        payload["start_time"] = start_time.strip().replace(" ", "T")
    if end_time:
        payload["end_time"] = end_time.strip().replace(" ", "T")

    # 投放方式：匀速（FB 默认，不传即 standard）/ 加速（no_pacing）
    if pacing.strip().lower() == "accelerated":
        payload["pacing_type"] = ["no_pacing"]

    # 出价额与最小 ROAS（COST_CAP/BID_CAP/MIN_ROAS 系列配套；金额由调用方按账户本币换算好）
    if bid_amount is not None and int(bid_amount) > 0:
        payload["bid_amount"] = str(int(bid_amount))
    if minimum_roas is not None and float(minimum_roas) > 0:
        payload["minimum_roas"] = str(minimum_roas)

    # COST_CAP 需要 bid_amount（v1 简化：不设 COST_CAP，默认 LOWEST_COST_WITHOUT_CAP）
    # 后续完善：if bid_strategy == "COST_CAP" and target_cpa: payload["bid_amount"] = ...

    # ── promoted_object / destination_type ──
    # conversion_event 接线（批次I）：显式形参 > conversion_goal（UI 转化事件词表）映射 > 目标默认
    evt = (conversion_event or "").strip() or custom_event_from_goal(conversion_goal)
    if not evt:
        evt = "LEAD" if obj == "OUTCOME_LEADS" else "PURCHASE"
    promo: dict | None = None

    if loc:
        # 矩阵路径（conv_location 显式）：destination_type/optimization_goal/promoted_object 全由矩阵派生
        _dest, _goal, kind = _CONV_MATRIX[(obj, loc)]
        if kind == "pixel":
            if not pixel_id:
                raise ValueError(f"转化位置「{loc}」（{obj}）需要 pixel_id")
            promo = {"pixel_id": pixel_id, "custom_event_type": evt}
        elif kind == "page":
            if not page_id:
                raise ValueError(f"转化位置「{loc}」（{obj}）需要 page_id（消息/表单类主页身份）")
            promo = {"page_id": page_id}
            # CTW 显式号码：仅 Engagement 目标传（蓝图 §3.1/§5.2：Traffic/Sales 用主页绑定号，选主页即隐式）
            if loc == "whatsapp" and obj == "OUTCOME_ENGAGEMENT" and (whatsapp_phone_number or "").strip():
                promo["whatsapp_phone_number"] = whatsapp_phone_number.strip()
    else:
        # 存量推导路径（conv_location 空 = 行为与旧版一致；destination_type 查表与旧分支同源）
        dest_type = _LEGACY_DEST.get((obj, opt_goal), "")
        if obj == "OUTCOME_SALES" and opt_goal in ("OFFSITE_CONVERSIONS", "VALUE"):
            if not pixel_id:
                raise ValueError("购物目标（OFFSITE_CONVERSIONS）需要 pixel_id")
            promo = {"pixel_id": pixel_id, "custom_event_type": evt}
        elif obj == "OUTCOME_LEADS":
            if opt_goal == "LEAD_GENERATION":
                # Instant Forms → ON_AD
                if not page_id:
                    raise ValueError("潜在客户（Instant Forms）需要 page_id")
                promo = {"page_id": page_id}
            elif opt_goal == "OFFSITE_CONVERSIONS":
                # 网站线索 → WEBSITE
                if not pixel_id:
                    raise ValueError("潜在客户（网站）需要 pixel_id")
                promo = {"pixel_id": pixel_id, "custom_event_type": evt}
        elif obj == "OUTCOME_ENGAGEMENT":
            if opt_goal == "PAGE_LIKES":
                if not page_id:
                    raise ValueError("主页赞需要 page_id")
                promo = {"page_id": page_id}
            elif opt_goal == "POST_ENGAGEMENT":
                if page_id:
                    promo = {"page_id": page_id}
            elif opt_goal in ("CONVERSATIONS", "MESSAGING_PURCHASE_CONVERSION",
                              "MESSAGING_APPOINTMENT_CONVERSION"):
                if not page_id:
                    raise ValueError("消息类目标需要 page_id")
                promo = {"page_id": page_id}

    # 消息类目的地兜底（legacy 覆盖路径）：destination=消息类但无 promoted_object → page_id 必填
    # （蓝图 §5.2：CTM/CTW/CTI 的 promoted_object={page_id} 必填）
    if dest_type in ("MESSENGER", "WHATSAPP", "INSTAGRAM_DIRECT") and promo is None:
        if not page_id:
            raise ValueError(f"消息类目的地（{dest_type}）需要 page_id")
        promo = {"page_id": page_id}
    # SALES 兜底（批次I 修隐患B）：SALES 系列任何优化目标都必须带 promoted_object——
    # 转化类走像素（上方），其余（CONVERSATIONS/LINK_CLICKS/REACH...）用 page_id，缺则 400 快失败
    if obj == "OUTCOME_SALES" and promo is None:
        if not page_id:
            raise ValueError("SALES 目标该优化组合需要 promoted_object：提供 pixel_id（转化类）或 page_id（消息/主页类）")
        promo = {"page_id": page_id}
    if promo is not None:
        payload["promoted_object"] = promo
    if dest_type:
        payload["destination_type"] = dest_type

    # 用户显式覆盖 destination_type（高级设置 / 模板指定）——仅 conv_location 为空时生效：
    # 矩阵派生值是用户显式选的转化位置，无条件顶掉会造出矛盾组合（批次I 修隐患A：
    # 组覆盖 CONVERSATIONS 派生 MESSENGER 后被模板残留 destination_type=ON_PAGE 顶掉）
    if destination_type_override and destination_type_override.strip() and not loc:
        payload["destination_type"] = destination_type_override.strip()

    # 结构化版位（组节点 placement_mode=manual）：写进 targeting（在 extra 深合并之前，
    # advanced_config 仍可兜底覆盖——保持既有优先级约定）；auto/空 = 省略全部版位键（Advantage+ 版位）
    if placements:
        _pp = [str(p) for p in (placements.get("publisher_platforms") or []) if str(p).strip()]
        if _pp:
            payload["targeting"]["publisher_platforms"] = _pp
        _dp = [str(d) for d in (placements.get("device_platforms") or []) if str(d).strip()]
        if _dp:
            payload["targeting"]["device_platforms"] = _dp
        # 细分版位（批次III）：省略=该平台全部位置（FB 官方语义）；值合法性由 _validate_structure 白名单把关
        for _pk in ("facebook_positions", "instagram_positions", "messenger_positions"):
            _pv = [str(x) for x in (placements.get(_pk) or []) if str(x).strip()]
            if _pv:
                payload["targeting"][_pk] = _pv

    # MESSENGER 目的地需 publisher_platforms 含 messenger：并入既有选择（去重），不再整体覆盖
    if payload.get("destination_type") == "MESSENGER":
        _pp = list(payload["targeting"].get("publisher_platforms") or [])
        if "messenger" not in _pp:
            _pp.append("messenger")
            payload["targeting"]["publisher_platforms"] = _pp

    # 高级字段深合并（advanced_config：bid_amount/attribution_spec/placements/dayparting/...）
    if extra:
        # is_dynamic_creative 一律剥掉（批U3 实证）：DC 组要求多素材创意，本链创意恒单素材
        # ——模板 advanced_config 残留该键时 adset 建成但 ads 全灭 1885702/invalid_param
        extra = {k: v for k, v in extra.items() if k != "is_dynamic_creative"}
        _deep_merge(payload, extra)
    # Advantage+ 受众（组级开关，批V+批W 实测定稿）：v23.0 起 targeting_automation 必须嵌在
    # targeting 内且显式发 1/0。**非默认定向（自定义年龄/性别/受众/兴趣）必须=0**——显式 1 或
    # 不发键在非默认取向下都会被拒（1870227/1870188 实测）。规则：开关关 或 targeting 含任何
    # 非默认收窄 → 0（原始受众，手动定向全量生效）；仅默认宽定向（geo+18-65+全性别）才 1。
    # 放 extra 合并后写，防 advanced_config 残留键顶掉。
    payload.setdefault("targeting", {})
    if isinstance(payload["targeting"], dict):
        _t = payload["targeting"]
        _non_default = bool(
            _t.get("flexible_spec") or _t.get("excluded_connections")
            or _t.get("custom_audiences") or _t.get("excluded_custom_audiences")
            or _t.get("behaviors") or _t.get("life_events")
            or _t.get("genders") not in (None, [], [0, 1, 2])   # []=build_targeting 全性别
            or _t.get("age_min") not in (None, 18)
            or _t.get("age_max") not in (None, 65))
        payload["targeting"]["targeting_automation"] = {
            "advantage_audience": 0 if (advantage_audience is False or _non_default) else 1}
    return payload


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并 override 进 base（override 覆盖同 key；dict 深合并）。"""
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def _deep_copy(d):
    """JSON 往返深拷贝（避免共享引用 mutation）。"""
    import json as _j
    return _j.loads(_j.dumps(d)) if d else d


# ── Ad creative ──

# CTA 类型全集（1.0 实测验证 16 种 link CTA + 5 种 msg CTA）
LINK_CTA_TYPES = [
    "SHOP_NOW", "SIGN_UP", "LEARN_MORE", "SUBSCRIBE", "DOWNLOAD",
    "BOOK_NOW", "CONTACT_US", "GET_QUOTE", "SEE_MENU", "SHOP_NOW",
    "ADD_TO_CART", "BUY_TICKETS", "INSTALL_MOBILE_APP", "USE_APP",
    "WATCH_MORE", "LISTEN_NOW",
]

# 默认 CTA（按目标自动选）
_DEFAULT_CTA = {
    "OUTCOME_SALES": "SHOP_NOW",
    "OUTCOME_LEADS": "SIGN_UP",
    "OUTCOME_TRAFFIC": "LEARN_MORE",
    "OUTCOME_ENGAGEMENT": "LIKE_PAGE",
    "OUTCOME_AWARENESS": "LEARN_MORE",
}


def build_creative(
    page_id: str,
    objective: str,
    conversion_goal: str = "",
    landing_url: str = "",
    headline: str = "",
    body: str = "",
    image_hash: str = "",
    cta_type: str = "",
    video_id: str = "",
    video_thumb_hash: str = "",            # 视频缩略图 image_hash（API 建视频创意必填，缺失=FB 拒"缺少视频缩略图"）
    lead_form_id: str = "",
    welcome_message: dict | None = None,
    description: str = "",                  # 链接描述（正文下方灰色小字，FB「描述」字段）
    instagram_actor_id: str = "",           # IG 账号 ID（object_story_spec 外层；空=用主页关联 IG）
    app_destination: str = "",              # 消息目的地（MESSENGER/WHATSAPP/INSTAGRAM_DIRECT）→ 默认消息类 CTA（显式 cta_type 优先）
) -> dict:
    """构造广告创意（object_story_spec）。

    支持图片/视频创意 + CTA 按钮 + headline/body + Messenger/WhatsApp 欢迎语。
    headline/body 优先用户自定义，空则用默认。
    welcome_message：已构造好的 page_welcome_message VISUAL_EDITOR dict（消息广告用）。
    app_destination：消息类目的地（CTM/CTW/CTI）——cta_type 为空时默认消息类 CTA
    （MESSENGER/INSTAGRAM_DIRECT→MESSAGE_PAGE、WHATSAPP→WHATSAPP_MESSAGE）+
    value.app_destination（蓝图 §4.2）；用户显式选了 CTA 则不覆盖。
    """
    obj = normalize_objective(objective)

    link = landing_url or f"https://facebook.com/{page_id}"
    msg = body or "Check this out!"
    hd = headline or ""
    cta = cta_type or _DEFAULT_CTA.get(obj, "LEARN_MORE")

    # Lead Form 引用：CTA 固定 SIGN_UP + value.lead_gen_form_id（02_附录 §2.8 不变量10）
    cta_value: dict[str, Any] = {"link": link}
    if lead_form_id:
        cta = "SIGN_UP"
        cta_value = {"lead_gen_form_id": lead_form_id}
    elif app_destination.upper() in ("MESSENGER", "WHATSAPP", "INSTAGRAM_DIRECT") and not cta_type:
        cta = "WHATSAPP_MESSAGE" if app_destination.upper() == "WHATSAPP" else "MESSAGE_PAGE"
        cta_value = {"app_destination": app_destination.upper()}

    link_data: dict[str, Any] = {
        "link": link,
        "message": msg,
        "call_to_action": {
            "type": cta,
            "value": cta_value,
        },
    }
    if hd:
        link_data["name"] = hd
    if description and description.strip():
        link_data["description"] = description.strip()
    if image_hash:
        link_data["image_hash"] = image_hash
    # Messenger 欢迎语注入到 link_data（02_附录 §2.1）
    if welcome_message:
        link_data["page_welcome_message"] = welcome_message

    story_spec: dict[str, Any] = {
        "page_id": page_id,
        "link_data": link_data,
    }

    # 视频创意（优先于图片）
    if video_id:
        video_data: dict[str, Any] = {
            "video_id": video_id,
            "message": msg,
            "title": hd or "",
            "call_to_action": {
                "type": cta,
                "value": cta_value,
            },
        }
        if welcome_message:
            video_data["page_welcome_message"] = welcome_message  # 02_附录 §2.1
        if video_thumb_hash:
            video_data["image_hash"] = video_thumb_hash  # 缩略图必填（用户 12 条视频广告全拒实证）
        story_spec = {
            "page_id": page_id,
            "video_data": video_data,
        }

    # IG 身份（可选）：与 link_data/video_data 同层（object_story_spec 外层）。
    # 空=不传，FB 用主页关联的 Instagram 账号。
    if instagram_actor_id and instagram_actor_id.strip():
        story_spec["instagram_actor_id"] = instagram_actor_id.strip()

    return {"object_story_spec": story_spec}


# ── Lead Form（Instant Forms）── 详见 02_附录_表单字段.md

# 内置联系字段 type（FB 预置）
_CONTACT_FIELD_TYPES = (
    "EMAIL", "PHONE", "FIRST_NAME", "LAST_NAME", "CITY", "STATE",
    "ZIP_CODE", "COUNTRY", "DATE_OF_BIRTH", "MARITAL_STATUS", "GENDER",
)

# 电话优先国家（见 02_附录 §1.4）—— 这些国家默认联系字段用 PHONE，否则 EMAIL
_PHONE_FIRST_COUNTRIES = {
    "PH", "TH", "ID", "MY", "VN", "IN", "BR", "MX", "NG", "CO", "EG", "PK", "BD",
}

# 安全 URL 过滤：follow_up / thank_you 禁止指向 FB 域（02_附录 §1.5 不变量2）
_FB_HOSTS = ("facebook.com", "fb.com", "m.me", "wa.me", "t.me")


def _is_safe_external_url(url: str) -> bool:
    """follow_up / thank_you.website_url 必须是外部安全站点（非 FB 域）。"""
    if not url:
        return False
    u = url.lower().strip()
    return not any(h in u for h in _FB_HOSTS)


def default_contact_field(target_countries: list[str]) -> str:
    """按目标国家路由联系字段（02_附录 §1.4）。"""
    if any(c.upper() in _PHONE_FIRST_COUNTRIES for c in (target_countries or [])):
        return "PHONE"
    return "EMAIL"


def build_lead_form_payload(
    form_title: str,
    privacy_url: str,
    locale: str = "en_US",
    target_countries: list[str] | None = None,
    description: str = "",
    custom_questions: list[dict] | None = None,
    extra_contact_fields: list[str] | None = None,
    privacy_link_text: str = "Privacy Policy",
    thank_you_title: str = "",
    thank_you_body: str = "",
    thank_you_button_text: str = "",
    thank_you_website_url: str = "",
    follow_up_url: str = "",
    context_card_title: str = "",
    name_prefix: str = "AI",
    is_optimized_for_quality: bool = False,
    welcome_message: str = "",
    only_visible_to_target_countries: bool = False,
) -> dict:
    """构造 leadgen_forms 创建 payload（02_附录 §2.2）。

    嵌套字段（questions/privacy_policy/thank_you_page/context_card）
    返回为 dict——由 FbClient.post 在 form-encode 时 json.dumps。
    """
    import json

    if not form_title:
        raise ValueError("表单标题 form_title 必填")
    if not privacy_url:
        raise ValueError("privacy_url 必填（02_附录 §四 不变量3）")

    # ── questions：联系字段（按国家路由）+ 客户自选 + 自定义问题 ──
    # 批W 实测修正：questions 项不支持 "name" 键（v25 #100 Invalid keys "name"）——
    # 预置联系字段用 type+key，自定义问题用 key+label（下方原样）
    primary = default_contact_field(target_countries or [])
    questions: list[dict] = [
        {"type": "FIRST_NAME", "key": "first_name"},
        {"type": primary, "key": primary.lower()},
    ]
    for f in (extra_contact_fields or []):
        f_up = f.upper().strip()
        if f_up in _CONTACT_FIELD_TYPES and f_up not in (primary, "FIRST_NAME"):
            questions.append({"type": f_up, "key": f_up.lower()})
    has_custom_options = False
    for q in (custom_questions or []):
        item = {"type": "CUSTOM"}
        key = q.get("key") or q.get("label", "").lower().replace(" ", "_")
        item["key"] = key
        item["label"] = q.get("label", "")
        # placeholder 是编辑器本地概念，LeadGenQuestion 无此键（批W 实测 #100 Invalid keys）
        opts = q.get("options")
        if opts:
            has_custom_options = True
            item["options"] = [{"key": o.get("key", f"opt_{i}"),
                                "value": o.get("value", str(o))} for i, o in enumerate(opts)]
        questions.append(item)

    payload: dict[str, Any] = {
        "name": f"[{name_prefix}] {form_title}",
        "questions": questions,
        "privacy_policy": {"url": privacy_url, "link_text": privacy_link_text or "Privacy Policy"},
        "locale": locale,
    }
    # 带选项的自定义问题必须 ON_DELIVERY（02_附录 §四 不变量4）
    if has_custom_options:
        payload["flexible_delivery"] = "ON_DELIVERY"

    # 表单模板编辑器三开关（原 UI 存而不用——payload 不带 = 配置无效无提示）
    if is_optimized_for_quality:
        payload["is_optimized_for_quality"] = True
    if welcome_message:
        payload["welcome_message"] = {"text": welcome_message[:500]}
    if only_visible_to_target_countries and target_countries:
        payload["target_countries"] = target_countries   # 仅选中国家可见（需先有国家）

    if description:
        payload["description"] = description

    # ── 感谢页（安全 URL 过滤）──
    if thank_you_title:
        typ_page: dict[str, Any] = {"title": thank_you_title}
        if thank_you_body:
            typ_page["body"] = thank_you_body
        if thank_you_button_text and _is_safe_external_url(thank_you_website_url):
            typ_page["button_type"] = "VIEW_WEBSITE"
            typ_page["button_text"] = thank_you_button_text
            typ_page["website_url"] = thank_you_website_url
        else:
            typ_page["button_type"] = "NONE"
        payload["thank_you_page"] = typ_page

    # ── 跟进链接（安全 URL 才写，02_附录 §四 不变量2）──
    if _is_safe_external_url(follow_up_url):
        payload["follow_up_action_url"] = follow_up_url

    # ── 上下文卡片（仅手动路径传，AI 路径不传 → 02_附录 §四 不变量7）──
    if context_card_title and name_prefix != "AI":
        payload["context_card"] = {
            "style": "LIST_STYLE",
            "title": context_card_title,
            "content": {"button_text": "Learn more"},
        }

    return payload


def lead_form_safe_payload(payload: dict) -> dict:
    """368/1346003 风控重试用的"安全版"（02_附录 §2.9）。

    裁剪：自定义问题选项 / context_card / thank_you_page / follow_up_action_url / description。
    只留 name + questions(联系字段+简答) + privacy_policy + locale。
    """
    kept = {}
    for k in ("name", "privacy_policy", "locale"):
        if k in payload:
            kept[k] = payload[k]
    safe_q = []
    for q in payload.get("questions", []):
        if q.get("type") == "CUSTOM":
            q2 = {"type": "CUSTOM", "key": q.get("key"), "label": q.get("label")}
            if q.get("placeholder"):
                q2["placeholder"] = q["placeholder"]
            safe_q.append(q2)  # 丢 options
        else:
            safe_q.append(q)
    kept["questions"] = safe_q
    return kept


# ── TikTok Instant Form（表单模板 platform='tt' 用；编辑器 config 与 FB 共用一套）──
# 字段映射为常识版（官方 Business API v1.3 Lead Gen 文档结构），sandbox 校准点：
# 端点路径 lead/form/create/、question_type 枚举、choices/键名以 sandbox 实测为准，
# 不符只改本函数（调用方 launch_templates/_resolve_lead_form 与 form_templates.deploy）。

# FB 编辑器联系字段 → TT 内置 question_type（小写）。不在表内的 FB 字段 TT 无对应 → 丢弃。
_TT_CONTACT_FIELD_MAP = {
    "EMAIL": "email", "PHONE": "phone", "FIRST_NAME": "name", "LAST_NAME": "last_name",
    "CITY": "city", "STATE": "state", "ZIP_CODE": "zip_code", "COUNTRY": "country",
    "DATE_OF_BIRTH": "date_of_birth", "GENDER": "gender", "MARITAL_STATUS": "marital_status",
}


def build_tt_lead_form_payload(
    form_title: str,
    privacy_url: str,
    target_countries: list[str] | None = None,
    description: str = "",
    custom_questions: list[dict] | None = None,
    extra_contact_fields: list[str] | None = None,
    thank_you_title: str = "",
    thank_you_body: str = "",
    name_prefix: str = "Tova",
    display_name: str = "",
) -> dict:
    """构造 TikTok Instant Form 创建 payload（lead/form/create/）。

    与 build_lead_form_payload 平行：同一套编辑器 config 进，按平台出各自 payload。
    映射：name→form_name；questions type→TT 枚举（CUSTOM+options→single_choice、
    CUSTOM 无 options→open_text、联系字段→内置类型）；privacy_policy.url→privacy_policy_url；
    thank_you_*→成功页文案。FB 特有项（welcome_message/is_optimized_for_quality/
    follow_up_url 等）不迁移——TT 表单无对应概念。locale 不带（TT 表单语言跟随广告主）。
    """
    if not form_title:
        raise ValueError("表单标题 form_title 必填")
    if not privacy_url:
        raise ValueError("privacy_url 必填")

    # ── questions：联系字段（按国家路由，同 FB 逻辑）+ 自定义问题 ──
    primary = default_contact_field(target_countries or [])
    questions: list[dict] = [
        {"question_type": "name", "label": "Name"},                      # sandbox 校准：内置字段 label 是否必填
        {"question_type": primary, "label": "Email" if primary == "email" else "Phone"},
    ]
    seen = {"name", primary}
    for f in (extra_contact_fields or []):
        tt_type = _TT_CONTACT_FIELD_MAP.get((f or "").upper().strip(), "")
        if tt_type and tt_type not in seen:
            seen.add(tt_type)
            questions.append({"question_type": tt_type})
    for q in (custom_questions or []):
        opts = [str(o.get("value", o)).strip() for o in (q.get("options") or []) if str(o.get("value", o)).strip()]
        if opts:
            questions.append({"question_type": "single_choice",
                              "label": q.get("label", ""), "choices": opts})
        else:
            questions.append({"question_type": "open_text", "label": q.get("label", "")})

    payload: dict[str, Any] = {
        "form_name": f"[{name_prefix}] {form_title}",
        "display_name": display_name or form_title,   # 对外显示名（不挂内部前缀）
        "privacy_policy_url": privacy_url,
        "questions": questions,
    }
    if description:
        payload["description"] = description
    if thank_you_title or thank_you_body:
        payload["thank_you"] = {"title": thank_you_title, "body": thank_you_body}  # sandbox 校准：成功页文案键名
    return payload


def tt_lead_form_id_from_result(result: dict) -> str:
    """解析 lead/form/create/ 响应的 form_id（键名容错：form_id / form_ids[0]）。

    sandbox 校准点：官方返回结构以实测为准，不符只改这里。
    """
    data = (result or {}).get("data") or {}
    fid = data.get("form_id")
    if not fid:
        ids = data.get("form_ids") or []
        fid = ids[0] if ids else None
    return str(fid) if fid else ""


# ── Messenger 消息模板（page_welcome_message / VISUAL_EDITOR）── 详见 02_附录_消息模板.md

# CJK 字符检测（AI 守卫：非 CJK 语言禁 CJK 字符，02_附录 §3.2）
def _contains_cjk(s: str) -> bool:
    if not s:
        return False
    for ch in s:
        cp = ord(ch)
        if (0x4E00 <= cp <= 0x9FFF) or (0x3040 <= cp <= 0x30FF) or (0xAC00 <= cp <= 0xD7AF):
            return True
    return False


def build_welcome_message(
    welcome_text: str,
    ice_breakers: list[dict] | None = None,
    allow_cjk: bool = True,
) -> dict:
    """构造 page_welcome_message 的 VISUAL_EDITOR dict（02_附录 §2.2）。

    返回 dict——由 FbClient.post 在 form-encode 时 json.dumps 成字符串。
    ice_breakers: [{"title":..., "response":...}, ...]
    """
    if not welcome_text:
        raise ValueError("欢迎语 welcome_text 必填")
    if not allow_cjk and _contains_cjk(welcome_text):
        raise ValueError("非 CJK 语言禁用中/日/韩字符（02_附录 §3.2）")

    msg: dict[str, Any] = {
        "text": welcome_text,
        "ice_breakers": [],
        "quick_replies": [],  # v1 固定空（02_附录 §五 不变量3）
    }
    for ib in (ice_breakers or []):
        title = (ib.get("title") or "").strip()
        response = (ib.get("response") or "").strip()
        if not title or not response:
            raise ValueError("ice_breakers 每项必须含非空 title + response（02_附录 §五 不变量4）")
        if not allow_cjk and (_contains_cjk(title) or _contains_cjk(response)):
            raise ValueError("非 CJK 语言禁用中/日/韩字符（02_附录 §3.2）")
        msg["ice_breakers"].append({"title": title, "response": response})

    return {
        "type": "VISUAL_EDITOR",
        "version": 2,
        "landing_screen_type": "welcome_message",
        "media_type": "text",
        "text_format": {
            "customer_action_type": "ice_breakers",
            "message": msg,
        },
        "user_edit": False,
        "surface": "visual_editor_new",
    }


def build_wa_welcome_message(welcome_text: str, allow_cjk: bool = True) -> dict:
    """Click-to-WhatsApp 的 page_welcome_message（VISUAL_EDITOR v2 预填消息形态）。

    蓝图 §4.2 CTW（官API 2026-06 快照）：landing_screen_type=welcome_message +
    customer_action_type=autofill_message + autofill_message.content（预填句）。
    与 Messenger 的 ice_breakers 形态互斥（WA 预填是单条文本）。
    实测校准点：text_format/autofill_message 键名以真部署回读为准，不符只改本函数。"""
    if not welcome_text:
        raise ValueError("欢迎语 welcome_text 必填")
    if not allow_cjk and _contains_cjk(welcome_text):
        raise ValueError("非 CJK 语言禁用中/日/韩字符（02_附录 §3.2）")
    return {
        "type": "VISUAL_EDITOR",
        "version": 2,
        "landing_screen_type": "welcome_message",
        "media_type": "text",
        "text_format": {
            "customer_action_type": "autofill_message",
            "autofill_message": {"content": welcome_text},
        },
        "user_edit": False,
        "surface": "visual_editor_new",
    }


def parse_message_template(raw, allow_cjk: bool = True, channel: str = "messenger") -> dict | None:
    """把客户的 message_template 输入归一为 page_welcome_message dict（02_附录 §四）。

    raw 可能是：
      - dict（已含 text + ice_breakers，或完整 VISUAL_EDITOR）
      - JSON 字符串（完整 VISUAL_EDITOR 或简略）
      - 纯文本字符串（→ welcome_text）
    channel="whatsapp"（MessageTemplate.type=whatsapp / conv_location=whatsapp）→ CTW 预填
    形态（build_wa_welcome_message，忽略 ice_breakers）；messenger → ice_breakers 形态。
    返回 VISUAL_EDITOR dict，或 None（空输入）。
    """
    import json

    if raw is None or raw == "":
        return None

    def _wa(text: str) -> dict:
        return build_wa_welcome_message(text, allow_cjk=allow_cjk)

    # dict 直接用
    if isinstance(raw, dict):
        # 已是完整 VISUAL_EDITOR
        if raw.get("type") == "VISUAL_EDITOR":
            return raw
        text = raw.get("text") or raw.get("welcome_text") or ""
        if channel == "whatsapp":
            return _wa(text)
        return build_welcome_message(
            welcome_text=text,
            ice_breakers=raw.get("ice_breakers") or [],
            allow_cjk=allow_cjk,
        )

    # 字符串
    s = str(raw).strip()
    if not s:
        return None

    # 尝试 JSON 解析
    if s.startswith("{"):
        try:
            obj = json.loads(s)
            if obj.get("type") == "VISUAL_EDITOR":
                return obj
            text = obj.get("text") or obj.get("welcome_text") or ""
            if channel == "whatsapp":
                return _wa(text)
            return build_welcome_message(
                welcome_text=text,
                ice_breakers=obj.get("ice_breakers") or [],
                allow_cjk=allow_cjk,
            )
        except (json.JSONDecodeError, ValueError):
            pass  # 不是合法 JSON → 当纯文本

    # 纯文本 → welcome_text（无 ice_breakers）
    if channel == "whatsapp":
        return _wa(s)
    return build_welcome_message(welcome_text=s, ice_breakers=[], allow_cjk=allow_cjk)
