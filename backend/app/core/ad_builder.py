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
) -> dict:
    obj = normalize_objective(objective)
    payload: dict[str, Any] = {
        "name": name,
        "objective": obj,
        "status": "ACTIVE",
        "special_ad_categories": [],
        "buying_type": "AUCTION",
    }

    if budget_mode.upper() == "CBO":
        if not daily_budget or daily_budget <= 0:
            raise ValueError("CBO 模式必须配置系列日预算")
        payload["daily_budget"] = str(daily_budget)
        # CBO: bid_strategy 在系列级
        if target_cpa and float(target_cpa) > 0 and bid_strategy in ("COST_CAP", "BID_CAP"):
            payload["bid_strategy"] = "COST_CAP"
        else:
            payload["bid_strategy"] = "LOWEST_COST_WITHOUT_CAP"
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
    conversion_event: str = "PURCHASE",
    bid_strategy: str = "LOWEST_COST_WITHOUT_CAP",
    target_cpa: float | None = None,
    budget_mode: str = "ABO",
    targeting: dict | None = None,
) -> dict:
    obj = normalize_objective(objective)
    opt_goal = get_optimization_goal(obj, conversion_goal)

    payload: dict[str, Any] = {
        "name": name,
        "campaign_id": campaign_id,
        "billing_event": "IMPRESSIONS",
        "optimization_goal": opt_goal,
        "bid_strategy": bid_strategy,
        "targeting": targeting or {"geo_locations": {"countries": ["US"]}, "age_min": 18, "age_max": 65},
        "status": "ACTIVE",
    }

    # ABO: 广告组级预算
    if budget_mode.upper() != "CBO":
        payload["daily_budget"] = str(daily_budget)

    # COST_CAP 需要 bid_amount（v1 简化：不设 COST_CAP，默认 LOWEST_COST_WITHOUT_CAP）
    # 后续完善：if bid_strategy == "COST_CAP" and target_cpa: payload["bid_amount"] = ...

    # ── promoted_object（按目标+转化目的）──
    # doc 02 + 1.0 经验：不同目标需要不同的 promoted_object
    if obj == "OUTCOME_SALES" and opt_goal == "OFFSITE_CONVERSIONS":
        if not pixel_id:
            raise ValueError("购物目标（OFFSITE_CONVERSIONS）需要 pixel_id")
        payload["promoted_object"] = {
            "pixel_id": pixel_id,
            "custom_event_type": conversion_event or "PURCHASE",
        }
        payload["destination_type"] = "WEBSITE"

    elif obj == "OUTCOME_LEADS":
        if opt_goal == "LEAD_GENERATION":
            # Instant Forms → ON_AD
            if not page_id:
                raise ValueError("潜在客户（Instant Forms）需要 page_id")
            payload["promoted_object"] = {"page_id": page_id}
            payload["destination_type"] = "ON_AD"
        elif opt_goal == "OFFSITE_CONVERSIONS":
            # 网站线索 → WEBSITE
            if not pixel_id:
                raise ValueError("潜在客户（网站）需要 pixel_id")
            payload["promoted_object"] = {
                "pixel_id": pixel_id,
                "custom_event_type": "LEAD",
            }
            payload["destination_type"] = "WEBSITE"

    elif obj == "OUTCOME_ENGAGEMENT":
        if opt_goal == "PAGE_LIKES":
            if not page_id:
                raise ValueError("主页赞需要 page_id")
            payload["promoted_object"] = {"page_id": page_id}
            payload["destination_type"] = "ON_PAGE"
        elif opt_goal == "POST_ENGAGEMENT":
            if page_id:
                payload["promoted_object"] = {"page_id": page_id}
        elif opt_goal in ("CONVERSATIONS", "MESSAGING_PURCHASE_CONVERSION",
                          "MESSAGING_APPOINTMENT_CONVERSION"):
            if not page_id:
                raise ValueError("消息类目标需要 page_id")
            payload["promoted_object"] = {"page_id": page_id}
            payload["destination_type"] = "MESSENGER"
            # FB 要求 MESSENGER 时 publisher_platforms 含 messenger
            payload["targeting"]["publisher_platforms"] = ["messenger"]
        elif opt_goal in ("LINK_CLICKS", "LANDING_PAGE_VIEWS"):
            payload["destination_type"] = "WEBSITE"

    elif obj == "OUTCOME_TRAFFIC":
        if opt_goal in ("LINK_CLICKS", "LANDING_PAGE_VIEWS"):
            payload["destination_type"] = "WEBSITE"

    elif obj == "OUTCOME_AWARENESS":
        pass  # REACH/IMPRESSIONS 不需要 promoted_object

    return payload


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
    lead_form_id: str = "",
    welcome_message: dict | None = None,
) -> dict:
    """构造广告创意（object_story_spec）。

    支持图片/视频创意 + CTA 按钮 + headline/body + Messenger 欢迎语。
    headline/body 优先用户自定义，空则用默认。
    welcome_message：已构造好的 page_welcome_message VISUAL_EDITOR dict（消息广告用）。
    """
    obj = normalize_objective(objective)
    opt_goal = get_optimization_goal(obj, conversion_goal)

    link = landing_url or f"https://facebook.com/{page_id}"
    msg = body or "Check this out!"
    hd = headline or ""
    cta = cta_type or _DEFAULT_CTA.get(obj, "LEARN_MORE")

    # Lead Form 引用：CTA 固定 SIGN_UP + value.lead_gen_form_id（02_附录 §2.8 不变量10）
    cta_value: dict[str, Any] = {"link": link}
    if lead_form_id:
        cta = "SIGN_UP"
        cta_value = {"lead_gen_form_id": lead_form_id}

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
        story_spec = {
            "page_id": page_id,
            "video_data": video_data,
        }

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
    primary = default_contact_field(target_countries or [])
    questions: list[dict] = [
        {"type": "FIRST_NAME", "name": "first_name"},
        {"type": primary, "name": primary.lower()},
    ]
    for f in (extra_contact_fields or []):
        f_up = f.upper().strip()
        if f_up in _CONTACT_FIELD_TYPES and f_up not in (primary, "FIRST_NAME"):
            questions.append({"type": f_up, "name": f_up.lower()})
    has_custom_options = False
    for q in (custom_questions or []):
        item = {"type": "CUSTOM"}
        key = q.get("key") or q.get("label", "").lower().replace(" ", "_")
        item["key"] = key
        item["label"] = q.get("label", "")
        if q.get("placeholder"):
            item["placeholder"] = q["placeholder"]
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


def parse_message_template(raw, allow_cjk: bool = True) -> dict | None:
    """把客户的 message_template 输入归一为 page_welcome_message dict（02_附录 §四）。

    raw 可能是：
      - dict（已含 text + ice_breakers，或完整 VISUAL_EDITOR）
      - JSON 字符串（完整 VISUAL_EDITOR 或简略）
      - 纯文本字符串（→ welcome_text）
    返回 VISUAL_EDITOR dict，或 None（空输入）。
    """
    import json

    if raw is None or raw == "":
        return None

    # dict 直接用
    if isinstance(raw, dict):
        # 已是完整 VISUAL_EDITOR
        if raw.get("type") == "VISUAL_EDITOR":
            return raw
        # 简略：text + ice_breakers
        return build_welcome_message(
            welcome_text=raw.get("text") or raw.get("welcome_text") or "",
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
            return build_welcome_message(
                welcome_text=obj.get("text") or obj.get("welcome_text") or "",
                ice_breakers=obj.get("ice_breakers") or [],
                allow_cjk=allow_cjk,
            )
        except (json.JSONDecodeError, ValueError):
            pass  # 不是合法 JSON → 当纯文本

    # 纯文本 → welcome_text（无 ice_breakers）
    return build_welcome_message(welcome_text=s, ice_breakers=[], allow_cjk=allow_cjk)
