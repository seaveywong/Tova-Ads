"""FB 广告创建链公共逻辑（Campaign → AdSet → Creative → Ad）。

从 routers/launch.py 抽出，供 /launch/create（单广告）和 launch_templates 部署 runner（批量）共用。
helper 纯 FB 侧：接收已解析好的 image_hash / video_id / subcode_link / targeting，
per-account 图片上传+缓存的逻辑由调用方处理（ensure_image_hash_for_account）。
"""
import json
from .fb_client import FbClient, FbApiError
from .ad_builder import build_campaign, build_adset, build_creative


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


def deploy_one_account(fb: FbClient, *, act_id: str, objective: str, conversion_goal: str,
                       page_id: str, pixel_id: str, landing_url: str,
                       daily_budget: int, budget_mode: str, bid_strategy: str,
                       name_prefix: str, headline: str, body: str, cta_type: str,
                       image_hash: str = "", video_id: str = "",
                       subcode_slug: str = "", subcode_link=None,
                       targeting=None, ad_language: str = "",
                       lead_form_id: str = "", message_template: str = "") -> dict:
    """Campaign → AdSet → Creative → Ad。返回 {campaign_id, adset_id, ad_id}。失败 raise FbApiError。

    subcode_link：预先解析好的 LandingAdLink（或 None）；用于 effective_url + 回绑 ad_id。
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
    campaign_id = camp["id"]

    # 2. AdSet（目标感知 + 受众）
    adset_payload = build_adset(
        name=f"{name_prefix} 组", campaign_id=campaign_id,
        daily_budget=daily_budget, objective=objective,
        conversion_goal=conversion_goal, page_id=page_id,
        pixel_id=pixel_id, landing_url=landing_url,
        bid_strategy=bid_strategy, budget_mode=budget_mode,
        targeting=targeting,
    )
    adset = fb.post(f"{act}/adsets", adset_payload)
    adset_id = adset["id"]

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
        allow_cjk = not ad_language or ad_language.lower() in ("zh", "ja", "ko", "zh-cn", "zh-tw")
        welcome_msg = parse_message_template(message_template, allow_cjk=allow_cjk)

    creative = build_creative(
        page_id=page_id, objective=objective, conversion_goal=conversion_goal,
        landing_url=effective_url, headline=headline, body=body,
        image_hash=image_hash, cta_type=cta_type, video_id=video_id,
        lead_form_id=lead_form_id, welcome_message=welcome_msg,
    )
    ad = fb.post(f"{act}/ads", {
        "name": f"{name_prefix} 广告", "adset_id": adset_id, "status": "ACTIVE", "creative": creative,
    })
    ad_id = ad["id"]

    # 子码标注广告名（可追溯）+ 回绑 ad_id
    if subcode_slug and subcode_link is not None:
        try:
            fb.post(ad_id, {"name": f"[子码:{subcode_slug}] {name_prefix}"})
        except Exception:
            pass
        subcode_link.ad_id = ad_id
        subcode_link.status = "active"

    return {"campaign_id": campaign_id, "adset_id": adset_id, "ad_id": ad_id}
