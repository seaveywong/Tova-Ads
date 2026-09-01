"""TikTok 广告参数构建器（与 FB 的 ad_builder.py 平行；TK 接入 P3）。

TT 与 FB 的关键结构差异（doc/调研结论）：
- 三层 campaign→adgroup→ad 一一对应，但**定向/优化目标/预算全在 adgroup 层**；
- 素材不是 hash 引用而是文件库 file_id（image_id/video_id，按 advertiser 隔离，上传见 tt_client）；
- 预算单位 = **当地币种整数**（无 FB 的 minor units ×100 —— usd_to_tt_amount 与 usd_to_fb_amount 分开）；
- 转化用**像素 code**（TT 术语 pixel_code；adgroup payload 字段名叫 pixel_id，值为像素 code）。

目标/优化事件/版位映射为常识写法，sandbox 校准点已在注释标注。
"""
from typing import Any

# ── FB objective（模板沿用 FB 枚举）→ TT campaign objective（v1.3 经典枚举）──
# sandbox 校准点：TT 新旧两套目标枚举并存，经典枚举（WEB_CONVERSIONS/TRAFFIC/...）
# 在 v1.3 仍接受；若 sandbox 拒绝再切新枚举（SALES/LEADS + 二级目标）。
TT_OBJECTIVE_MAP = {
    "OUTCOME_SALES": "WEB_CONVERSIONS",
    "CONVERSIONS": "WEB_CONVERSIONS",
    "OUTCOME_LEADS": "LEAD_GENERATION",
    "LEAD_GENERATION": "LEAD_GENERATION",
    "OUTCOME_TRAFFIC": "TRAFFIC",
    "LINK_CLICKS": "TRAFFIC",
    # FB 互动（赞/消息）TT 无直接对应——常识取视频观看（TT 主力互动形态）
    "OUTCOME_ENGAGEMENT": "VIDEO_VIEWS",
    "OUTCOME_AWARENESS": "REACH",
    "OUTCOME_APP_PROMOTION": "APP_PROMOTION",
}

# ── TT objective → adgroup optimization_goal ──
_TT_OPT_GOAL_MAP = {
    "WEB_CONVERSIONS": "CONVERSIONS",
    "LEAD_GENERATION": "LEAD_GENERATION",
    "TRAFFIC": "CLICK",
    "VIDEO_VIEWS": "VIDEO_VIEW",
    "REACH": "REACH",
    "APP_PROMOTION": "APP_INSTALL",
}

# ── FB conversion_event（custom_event_type）→ TT optimization_event（web 转化优化事件）──
# TT 网页事件名来自 TikTok Pixel 标准 event（CompletePayment/SubmitForm/...）；
# FB custom_event_type 名与 TT 不通，按语义一一对应。
_TT_OPT_EVENT_MAP = {
    "PURCHASE": "PlaceAnOrder",           # TT 优化下单（成交事件的 TT 命名）
    "ADD_TO_CART": "AddToCart",
    "INITIATE_CHECKOUT": "InitiateCheckout",
    "COMPLETE_REGISTRATION": "CompleteRegistration",
    "LEAD": "SubmitForm",                 # 网站线索 → TT 表单提交事件
    "SUBSCRIBE": "Subscribe",
    "CONTACT": "Contact",
    "START_TRIAL": "StartTrial",
    "SEARCH": "Search",
}
DEFAULT_TT_OPT_EVENT = "PlaceAnOrder"

# ── CTA 映射（FB call_to_action type → TT creative call_to_action）──
# 大多同名直通；FB 专属（主页赞/私信类）回落通用 CTA。
_TT_CTA_MAP = {
    "SHOP_NOW": "SHOP_NOW", "SIGN_UP": "SIGN_UP", "SUBSCRIBE": "SUBSCRIBE",
    "LEARN_MORE": "LEARN_MORE", "DOWNLOAD": "DOWNLOAD", "CONTACT_US": "CONTACT_US",
    "GET_QUOTE": "GET_QUOTES", "BOOK_NOW": "BOOK_NOW", "ORDER_NOW": "ORDER_NOW",
    "ADD_TO_CART": "ADD_TO_CART", "WATCH_MORE": "WATCH_MORE",
}
DEFAULT_TT_CTA = "LEARN_MORE"


def normalize_tt_objective(objective: str) -> str:
    """FB 目标枚举 → TT campaign objective。未收录的回落 WEB_CONVERSIONS（模板主力是销售）。"""
    return TT_OBJECTIVE_MAP.get((objective or "").strip().upper(), "WEB_CONVERSIONS")


def tt_optimization_goal(tt_objective: str) -> str:
    return _TT_OPT_GOAL_MAP.get(tt_objective, "CONVERSIONS")


def tt_optimization_event(conversion_goal: str) -> str:
    return _TT_OPT_EVENT_MAP.get((conversion_goal or "").strip().upper(), DEFAULT_TT_OPT_EVENT)


def tt_cta(cta_type: str) -> str:
    return _TT_CTA_MAP.get((cta_type or "").strip().upper(), DEFAULT_TT_CTA)


def usd_to_tt_amount(usd: float, currency: str, fx_rate: float) -> int:
    """美元 → TT budget（当地币种**整数**，无 minor units）。

    与 FB 的 usd_to_fb_amount 区分：TT 预算字段不带百分单位（USD 20 → 20，VND 500k → 500000），
    无论币种小数位如何都取整到本币整数（TT API 全币种同口径）。
    fx_rate = CurrencyRate.rate（1 USD = rate × 本币）。
    """
    rate = fx_rate if fx_rate and fx_rate > 0 else 1.0  # USD 账户或汇率缺失兜底
    amount_local = float(usd or 0) * rate
    return max(1, int(round(amount_local)))


# ── Campaign payload（ advertiser_id 由 deploy 侧合并进 payload）──
def build_tt_campaign(name: str, objective: str, daily_budget: int | None = None,
                      budget_mode: str = "ABO") -> dict:
    """campaign/create/ payload。TT 无 FB 的 special_ad_categories/buying_type 概念。
    CBO（campaign 层日预算）→ BUDGET_MODE_DAY + budget；ABO → BUDGET_MODE_INFINITE（组层预算）。"""
    obj = normalize_tt_objective(objective)
    payload: dict[str, Any] = {
        "campaign_name": name,
        "objective": obj,
        # ABO：系列不设预算（无限），预算在 adgroup；CBO：系列日预算
        "budget_mode": "BUDGET_MODE_DAY" if budget_mode.upper() == "CBO" else "BUDGET_MODE_INFINITE",
        "operation_status": "ENABLE",
    }
    if budget_mode.upper() == "CBO":
        if not daily_budget or daily_budget <= 0:
            raise ValueError("CBO 模式必须配置系列日预算")
        payload["budget"] = int(daily_budget)
    return payload


# ── AdGroup payload（定向/优化/预算全在此层——TT 术语核心差异）──
def build_tt_adgroup(name: str, campaign_id: str, daily_budget: int, objective: str,
                     conversion_goal: str = "", pixel_code: str = "",
                     budget_mode: str = "ABO", targeting: dict | None = None,
                     placement: str = "PLACEMENT_TYPE_AUTOMATIC") -> dict:
    """adgroup/create/ payload。

    pixel_code：TikTok 像素 code（payload 字段名 pixel_id，值为 code）——web 转化目标必填。
    placement：PLACEMENT_TYPE_AUTOMATIC（TT 推荐自动版位）或 ["PLACEMENT_TIKTOK"] 等显式列表。
    """
    obj = normalize_tt_objective(objective)
    opt_goal = tt_optimization_goal(obj)
    payload: dict[str, Any] = {
        "campaign_id": str(campaign_id),
        "adgroup_name": name,
        "placement": placement,  # sandbox 校准点：自动版位常量 vs 列表形态
        "optimization_goal": opt_goal,
        "schedule_type": "SCHEDULE_START_NOW",
        "targeting": targeting if targeting is not None else build_tt_targeting(),
        "operation_status": "ENABLE",
    }
    if budget_mode.upper() == "CBO":
        # 系列预算模式下组层不设预算（无限），由系列 BUDGET_MODE_DAY 承担
        payload["budget_mode"] = "BUDGET_MODE_INFINITE"
    else:
        payload["budget_mode"] = "BUDGET_MODE_DAY"
        payload["budget"] = int(daily_budget)

    # web 转化：绑定像素 + 优化事件（sandbox 校准点：字段名 pixel_id/optimization_event）
    if opt_goal == "CONVERSIONS":
        if not pixel_code:
            raise ValueError("TikTok 转化目标需要像素 code（pixel_code）")
        payload["pixel_id"] = str(pixel_code)
        payload["optimization_event"] = tt_optimization_event(conversion_goal)
    return payload


# ── 定向构造（TT v1.3 targeting 形状）──
def build_tt_targeting(countries: list[str] | None = None,
                       age_min: int = 18, age_max: int = 65,
                       gender: int = 0, languages: list[str] | None = None,
                       interest_category_ids: list[str] | None = None) -> dict:
    """构造 adgroup.targeting。gender: 0=全部 1=男 2=女（FB 语义入口 → TT FEMALE/MALE 枚举）。

    注意：FB adinterest 兴趣 ID 与 TT 兴趣词库（/tool/interest_category/）不互通，
    interest_category_ids 只接 TT 词库 ID——P3 部署链路不迁移 FB 兴趣词（防错 ID 静默错定向）。
    """
    targeting: dict[str, Any] = {
        "location": {"countries": [c.upper() for c in (countries or ["US"])]},
        "age": {"age_min": int(age_min), "age_max": int(age_max)},
        "genders": ["MALE"] if gender == 1 else (["FEMALE"] if gender == 2 else []),
    }
    if languages:
        targeting["languages"] = [str(l) for l in languages]
    if interest_category_ids:
        targeting["interest_categories"] = [str(i) for i in interest_category_ids]
    return targeting


# ── Creative payload（素材 file_id + 文案 + CTA + 落地页，全在 ad 层）──
def build_tt_creative(ad_text: str, cta_type: str, landing_url: str,
                      video_file_id: str = "", image_file_id: str = "") -> dict:
    """ad/create/ 的 creatives 元素。视频优先（TT 主力）；ad_text 上限 100 字符（TT 规范）。"""
    if not landing_url:
        raise ValueError("TikTok 广告需要落地页 URL")
    text = (ad_text or "").strip()[:100] or "Check this out!"
    creative: dict[str, Any] = {
        "ad_text": text,
        "call_to_action": tt_cta(cta_type),
        "landing_page_url": landing_url,
    }
    if video_file_id:
        creative["creative_type"] = "SINGLE_VIDEO"
        creative["video_id"] = str(video_file_id)
    elif image_file_id:
        creative["creative_type"] = "SINGLE_IMAGE"
        creative["image_id"] = str(image_file_id)
    else:
        raise ValueError("TikTok 创意需要素材 file_id（视频或图片）")
    return {"creatives": [creative]}
