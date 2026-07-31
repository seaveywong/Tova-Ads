"""FB 广告创建链公共逻辑（Campaign → AdSet → Creative → Ad）。

从 routers/launch.py 抽出，供 /launch/create（单广告）和 launch_templates 部署 runner（批量）共用。
helper 纯 FB 侧：接收已解析好的 image_hash / video_id / subcode_link / targeting，
per-account 图片上传+缓存的逻辑由调用方处理（ensure_image_hash_for_account）。
"""
import json
from .fb_client import FbClient, FbApiError
from .ad_builder import build_campaign, build_adset, build_creative

# ISO 4217 零小数位币种（FB amount 单位 = 整本币，其余 ×100 进分）
_ZERO_DECIMAL_CURRENCIES = {
    "VND", "JPY", "KRW", "CLP", "ISK", "PYG", "UGX", "VUV",
    "XAF", "XOF", "XPF", "BIF", "DJF", "GNF", "KMF", "KPW", "RWF", "CLF",
}


def usd_to_fb_amount(usd: float, currency: str, fx_rate: float) -> int:
    """美元 → FB daily_budget（账户本币的最小货币单位）。

    fx_rate = CurrencyRate.rate（约定 1 USD = rate × 本币，如 VND≈25400）。
    零小数位币种（VND/JPY/KRW…）单位=整本币；其余（USD/EUR/THB/IDR…）×100=分。
    """
    rate = fx_rate if fx_rate and fx_rate > 0 else 1.0  # 兜底（USD 账户或汇率缺失）
    amount_local = float(usd or 0) * rate
    factor = 1 if (currency or "").upper() in _ZERO_DECIMAL_CURRENCIES else 100
    return max(1, int(round(amount_local * factor)))


def ensure_image_hash_for_account(fb: FbClient, db, asset, act_id: str, filepath: str) -> str:
    """取该账户的 image_hash（FB hash 按账户，不能跨账户复用）。

    查 asset.fb_image_hashes[act_id] 缓存；无 → 上传到该账户 adimages → 写回缓存（调用方 commit）。
    """
    from ..models.launch import Asset
    cache = {}
    if asset.fb_image_hashes:
        try:
            cache = json.loads(asset.fb_image_hashes)
        except Exception:
            cache = {}
    h = cache.get(act_id)
    if h:
        return h
    with open(filepath, "rb") as f:
        image_bytes = f.read()
    result = fb.upload_ad_image(act_id, image_bytes, asset.filename or "image.jpg")
    h = result.get("hash")
    if not h:
        raise FbApiError(f"上传图片到 act_{act_id} 未返回 hash", 0)
    cache[act_id] = h
    asset.fb_image_hashes = json.dumps(cache, ensure_ascii=False)
    # 也兼容旧单列（首个账户）
    if not asset.fb_image_hash:
        asset.fb_image_hash = h
    db.flush()
    return h


def pick_random_copy(asset) -> tuple[str, str]:
    """从素材 AI 文案随机挑 (headline, body) 组合。无 AI 文案→("", "")。
    投放/保活每条广告随机组合素材库的标题+文案，增加多样性。"""
    import random
    try:
        ac = json.loads(asset.ai_copy_json) if asset.ai_copy_json else {}
    except Exception:
        ac = {}
    hs = [str(h).strip() for h in (ac.get("headlines") or []) if str(h).strip()
          and str(h).strip().lower() not in ("none", "null")]
    bs = [str(b).strip() for b in (ac.get("bodies") or []) if str(b).strip()
          and str(b).strip().lower() not in ("none", "null")]
    h = random.choice(hs)[:200] if hs else ""
    b = random.choice(bs)[:500] if bs else ""
    return h, b


def pick_cta(body: str, objective: str) -> str:
    """根据文案内容 + 广告目标选最合适的 CTA 类型。"""
    b = (body or "").lower()
    obj = (objective or "").upper()
    if obj == "OUTCOME_ENGAGEMENT":
        return "LIKE_PAGE"
    if any(k in b for k in ["shop", "buy", "order", "purchase", "deal", "price", "sale", "store"]):
        return "SHOP_NOW"
    if any(k in b for k in ["sign up", "register", "subscribe", "book", "reserve"]):
        return "SIGN_UP"
    if any(k in b for k in ["contact", "message", "reach", "call", "whatsapp"]):
        return "CONTACT_US"
    if obj == "OUTCOME_SALES":
        return "SHOP_NOW"
    if obj == "OUTCOME_LEADS":
        return "SIGN_UP"
    return "LEARN_MORE"


def deploy_one_account(fb: FbClient, *, act_id: str, objective: str, conversion_goal: str,
                       page_id: str, pixel_id: str, landing_url: str,
                       daily_budget: int, budget_mode: str, bid_strategy: str,
                       name_prefix: str, headline: str, body: str, cta_type: str,
                       image_hash: str = "", video_id: str = "",
                       subcode_slug: str = "", subcode_link=None,
                       targeting=None, ad_language: str = "",
                       lead_form_id: str = "", message_template: str = "",
                       dsa_beneficiary: str = "", dsa_payor: str = "",
                       optimization_goal: str = "", billing_event: str = "",
                       destination_type_override: str = "",
                       page_post_id: str = "",
                       advanced_config: dict | None = None) -> dict:
    """Campaign → AdSet → Creative → Ad。返回 {campaign_id, adset_id, ad_id, page_post_id}。失败 raise FbApiError。

    subcode_link：预先解析好的 LandingAdLink（或 None）；用于 effective_url + 回绑 ad_id。
    page_post_id：dev app 走 object_story_id（调用方已建/复用主页帖传入）；空=走 object_story_spec（standard app）。
    """
    from .ad_builder import parse_message_template  # 局部 import 避免循环
    act = f"act_{act_id}"

    # 1. Campaign（目标感知）
    camp_payload = build_campaign(
        name=name_prefix, objective=objective,
        daily_budget=daily_budget if budget_mode.upper() == "CBO" else None,
        budget_mode=budget_mode, bid_strategy=bid_strategy,
    )
    camp = fb.post(f"{act}/campaigns", camp_payload)
    campaign_id = camp.get("id")
    if not campaign_id:
        raise FbApiError(f"FB 创建 campaign 未返回 id（响应：{str(camp)[:200]}）", 0)

    # 2. AdSet（目标感知 + 受众）
    adset_payload = build_adset(
        name=f"{name_prefix} 组", campaign_id=campaign_id,
        daily_budget=daily_budget, objective=objective,
        conversion_goal=conversion_goal, page_id=page_id,
        pixel_id=pixel_id, landing_url=landing_url,
        bid_strategy=bid_strategy, budget_mode=budget_mode,
        targeting=targeting,
        dsa_beneficiary=dsa_beneficiary, dsa_payor=dsa_payor,
        optimization_goal=optimization_goal, billing_event=billing_event,
        destination_type_override=destination_type_override,
        extra=advanced_config,
    )
    adset = fb.post(f"{act}/adsets", adset_payload)
    adset_id = adset.get("id")
    if not adset_id:
        raise FbApiError(f"FB 创建 adset 未返回 id（响应：{str(adset)[:200]}）", 0)

    # 3. 创意链接（子码集成）
    effective_url = landing_url
    if subcode_slug and subcode_link is not None:
        base = landing_url or "https://tovaads.com"
        effective_url = f"{base}/a/{subcode_slug}?ad=" + "{ad.id}"  # FB 宏，上线后自动替换

    # 3b. Messenger 欢迎语（私信广告前置）
    welcome_msg = None
    is_messaging = (objective.upper() in ("OUTCOME_ENGAGEMENT", "OUTCOME_MESSAGES", "MESSAGES")
                    and conversion_goal.lower() in ("conversations", "messaging_purchase_conversion",
                                                     "messaging_appointment_conversion"))
    if is_messaging and page_id:
        try:
            pf = fb.get(page_id, {"fields": "messaging_feature_status"})
            mfs = (pf.get("messaging_feature_status") or {})
            if (mfs.get("USER_MESSAGING") or "").upper() != "ENABLED":
                raise FbApiError("主页未开启 messaging，无法投放私信广告", 0)
        except FbApiError:
            raise
        except Exception:
            pass
        allow_cjk = True  # FB 接受 Messenger 消息里的中日韩字符；原 ad_language code 不匹配 bug 已移除
        welcome_msg = parse_message_template(message_template, allow_cjk=allow_cjk)

    creative = build_creative(
        page_id=page_id, objective=objective, conversion_goal=conversion_goal,
        landing_url=effective_url, headline=headline, body=body,
        image_hash=image_hash, cta_type=cta_type, video_id=video_id,
        lead_form_id=lead_form_id, welcome_message=welcome_msg,
    )
    if page_post_id:
        # dev app：object_story_id（引用调用方已建/复用的主页帖）→ 先 /adcreatives 拿 creative_id
        _cta_t = cta_type or pick_cta(body, objective)
        _cta_val = {"page": page_id} if _cta_t == "LIKE_PAGE" else {"link": effective_url or f"https://facebook.com/{page_id}"}
        cr = fb.post(f"{act}/adcreatives", {
            "name": f"{name_prefix} creative", "object_story_id": page_post_id,
            "call_to_action": json.dumps({"type": _cta_t, "value": _cta_val}),
        })
        creative_id = cr.get("id")
        if not creative_id:
            raise FbApiError(f"建 creative(object_story_id) 未返回 id：{str(cr)[:200]}", 0)
        ad = fb.post(f"{act}/ads", {
            "name": f"{name_prefix} 广告", "adset_id": adset_id, "status": "PAUSED",
            "creative": {"creative_id": creative_id},
        })
    else:
        # standard app：object_story_spec 内联（creative dict 由 fb 自动 json 编码）
        ad = fb.post(f"{act}/ads", {
            "name": f"{name_prefix} 广告", "adset_id": adset_id, "status": "PAUSED", "creative": creative,
        })
    ad_id = ad.get("id")
    if not ad_id:
        raise FbApiError(f"FB 创建 ad 未返回 id（响应：{str(ad)[:200]}）", 0)

    # 子码标注广告名（可追溯）+ 回绑 ad_id
    if subcode_slug and subcode_link is not None:
        try:
            fb.post(ad_id, {"name": f"[子码:{subcode_slug}] {name_prefix}"})
        except Exception:
            pass
        subcode_link.ad_id = ad_id
        subcode_link.status = "active"

    return {"campaign_id": campaign_id, "adset_id": adset_id, "ad_id": ad_id, "page_post_id": page_post_id}
