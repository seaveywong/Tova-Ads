"""FB 广告创建链公共逻辑（Campaign → AdSet → Creative → Ad）。

从 routers/launch.py 抽出，供 /launch/create（单广告）和 launch_templates 部署 runner（批量）共用。
helper 纯 FB 侧：接收已解析好的 image_hash / video_id / subcode_link / targeting，
per-account 图片上传+缓存的逻辑由调用方处理（ensure_image_hash_for_account）。

文件尾部另有一段 TikTok 平行链路（TK P3）：tt_client_for_account /
ensure_tt_file_id_for_account / deploy_one_account_tt —— FB 函数零改动。
"""
import json
import logging as _logging
from .fb_client import FbClient, FbApiError
from .tt_client import TtApiError
from .ad_builder import (build_campaign, build_adset, build_creative,
                         resolve_adset_destination, is_messaging_destination)

_lg = _logging.getLogger(__name__)

# Meta 官方零小数币种，全仓唯一真相源（FB amount 单位 = 整本币，其余 ×100 进分）。
# 全仓引用：services/ad_ops._NO_DECIMAL / guard_engine._NO_DECIMAL_CURRENCIES / tt_client._TT_ZERO_DECIMAL。
# PYG/XPF（复审C P1）：Meta 官方 offset=1 零小数，曾在换表时被误删——漏列会把预算 100× 放大下发。
ZERO_DECIMAL = {
    "JPY", "KRW", "VND", "CLP", "COP", "HUF", "ISK",
    "IDR", "KHR", "LAK", "MMK", "NGN", "PKR", "TWD",
    "UGX", "XAF", "XOF", "RWF", "VUV",
    "BIF", "DJF", "GNF", "KMF",
    "PYG", "XPF",
}


def usd_to_fb_amount(usd: float, currency: str, fx_rate: float) -> int:
    """美元 → FB daily_budget（账户本币的最小货币单位）。

    fx_rate = CurrencyRate.rate（约定 1 USD = rate × 本币，如 VND≈25400）。
    零小数位币种（VND/JPY/KRW…）单位=整本币；其余（USD/EUR/THB/IDR…）×100=分。
    """
    if (currency or "").upper() != "USD" and not (fx_rate and fx_rate > 0):
        raise ValueError(f"currency {currency} has no fx rate — refusing 1:1 fallback "
                         "(全库审查P2：差两个数量级的错预算)")   # USD 或有汇率才继续
    rate = fx_rate if fx_rate and fx_rate > 0 else 1.0
    amount_local = float(usd or 0) * rate
    factor = 1 if (currency or "").upper() in ZERO_DECIMAL else 100
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
        raise FbApiError("no_id", f"上传图片到 act_{act_id} 未返回 hash")
    _merge_asset_cache(db, asset, "fb_image_hashes", act_id, h)
    # 也兼容旧单列（首个账户）
    if not asset.fb_image_hash:
        asset.fb_image_hash = h
    db.flush()
    return h


def _merge_asset_cache(db, asset, col_name: str, act_id: str, value: str) -> None:
    """行锁下合并写回 Asset 的 {act_id: value} JSON 缓存列。

    并发 job 各自给同一素材上传不同账户时，无锁的整列覆盖会丢先提交方条目
    （下次部署重复上传）。FOR UPDATE + populate_existing 拿到最新已提交值再合并。
    锁持有到调用方 commit。
    """
    from ..models.launch import Asset
    db.query(Asset).filter(Asset.id == asset.id).with_for_update().populate_existing().first()
    merged = {}
    cur = getattr(asset, col_name)
    if cur:
        try:
            merged = json.loads(cur)
        except Exception:
            merged = {}
    merged[act_id] = value
    setattr(asset, col_name, json.dumps(merged, ensure_ascii=False))


def ensure_video_thumb_hash(fb: FbClient, db, asset, act_id: str, video_filepath: str) -> str:
    """视频缩略图的 image_hash（FB API 建视频创意必填 video_data.image_hash——缺失=
    「你的广告缺少视频缩略图」整广告被拒，2026-09-10 用户 12 条视频广告全失败实证）。

    首帧 JPG 落盘 {video}.thumb.jpg（一次抽取多账户/多次部署复用）；hash 按账户缓存进
    asset.fb_image_hashes（视频素材该列只有缩略图会写，与图片素材的正式 hash 不冲突）。
    上传文件名必须是 .jpg（复用 ensure_image_hash_for_account 会带视频的 .mp4 文件名 →
    FB 按 MIME 拒「请求参数错误」——首版 smoke 实证），故这里内联上传。
    抽帧失败抛 FbApiError（明确归因）。"""
    import os
    from .media_util import extract_keyframes
    thumb_path = video_filepath + ".thumb.jpg"
    if not os.path.exists(thumb_path) or os.path.getsize(thumb_path) < 1000:
        frames = extract_keyframes(video_filepath, 1)
        if not frames:
            raise FbApiError("no_id", f"视频抽帧失败（ffmpeg 缺失或视频损坏），无法生成缩略图: {asset.storage_key}")
        with open(thumb_path, "wb") as f:
            f.write(frames[0])
    cache = {}
    if asset.fb_image_hashes:
        try:
            cache = json.loads(asset.fb_image_hashes)
        except Exception:
            cache = {}
    h = cache.get(act_id)
    if h:
        return h
    with open(thumb_path, "rb") as f:
        image_bytes = f.read()
    result = fb.upload_ad_image(act_id, image_bytes, "video-thumb.jpg")
    h = result.get("hash")
    if not h:
        raise FbApiError("no_id", f"上传视频缩略图到 act_{act_id} 未返回 hash")
    _merge_asset_cache(db, asset, "fb_image_hashes", act_id, h)
    db.flush()
    return h


def ensure_video_id_for_account(fb: FbClient, db, asset, act_id: str, filepath: str) -> str:
    """取该账户的视频 video_id（FB 视频按账户隔离，不能跨账户复用）。

    查 asset.fb_video_ids[act_id] 缓存；无 → 上传到该账户 advideos → 写回缓存（调用方 commit）。
    视频上传比图片慢（几秒~几十秒），失败抛 FbApiError。
    """
    cache = {}
    if asset.fb_video_ids:
        try:
            cache = json.loads(asset.fb_video_ids)
        except Exception:
            cache = {}
    v = cache.get(act_id)
    if v:
        return v
    with open(filepath, "rb") as f:
        video_bytes = f.read()
    result = fb.upload_video(act_id, video_bytes, asset.filename or "video.mp4")
    v = result.get("id")
    if not v:
        raise FbApiError("no_id", "上传视频未返回 video_id（视频转码可能失败，请稍后重试）")
    _merge_asset_cache(db, asset, "fb_video_ids", act_id, v)
    db.flush()
    return v


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


def pick_ad_copy(asset, manual_headline: str = "", manual_body: str = "",
                 fallback_headline: str = "", fallback_body: str = "") -> tuple[str, str]:
    """广告文案单一优先级（批次II 修审计 A3）：手填 > 素材 AI 随机 > 模板兜底。

    旧序（AI 随机 > 手填）会把节点/模板里用户手写的文案静默顶掉；FB 口径=手动输入优先，
    自动文案变体属 Advantage+ creative 且需 opt-in。全部部署链（树节点/平铺/重试/TT）统一走此。
    manual_* = 用户手填层（树模式=广告节点，平铺/TT=模板级表单即手填层）；
    fallback_* = 模板级兜底（仅树模式与手填层分离时传）。
    """
    _rh, _rb = pick_random_copy(asset)
    return (((manual_headline or "").strip() or _rh or (fallback_headline or "")),
            ((manual_body or "").strip() or _rb or (fallback_body or "")))


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


def bind_link_ad_id(link, ad_id) -> bool:
    """子码回绑守卫（批次III 修 last-wins）：链接已绑不同 ad_id 时不覆盖，返 False（调用方留痕）。
    同 ad_id 重绑（重试/重部署同一广告）照常生效；空链接/空 ad_id 返 False。
    背景：手动同 slug 多广告（树跨节点/平铺跨账户共享）时旧逻辑无条件覆盖，1:1 台账失真。"""
    if link is None or not ad_id:
        return False
    old = str(getattr(link, "ad_id", "") or "")
    if old and old != str(ad_id):
        return False
    link.ad_id = ad_id
    link.status = "active"
    return True


def post_adset_resilient(fb, act_id: str, payload: dict) -> dict:
    """建 adset + 两类自动降级（canonical，全部署路径共用；重试一次，响应带留痕标记）。

    ① 1870227：dev App 下 FB 强制 Advantage+ 受众，经典受众字段一律拒收。降级 = 剥
      targeting 至纯 geo + Advantage+ 开（批U3 实测定论）。
    ② 1487429（批AZ 实测）：模板引用的像素当前令牌无权使用（共享 BM 像素+令牌更换后
      高发）→ 换该账户实际可用的第一个像素重试。调用方按 "_pixel_swapped"/"_advantage_forced"
      留痕并回写落地页像素（worker fire 页自身像素——只换 adset 页还发旧像素=FB 零转化）。"""
    try:
        return fb.post(f"act_{act_id}/adsets", payload)
    except FbApiError as e:
        raw = getattr(e, "raw", None) or {}
        sub = raw.get("error_subcode")
        if sub == 1870227:
            p2 = dict(payload)
            geo = (p2.get("targeting") or {}).get("geo_locations")
            p2["targeting"] = {"geo_locations": geo} if geo else {}
            p2["targeting"]["targeting_automation"] = {"advantage_audience": 1}   # 嵌套（顶层=白发）
            r = fb.post(f"act_{act_id}/adsets", p2)
            if isinstance(r, dict):
                r["_advantage_forced"] = True
            return r
        if sub == 1487429:
            pxs = []
            try:
                pxs = fb.get(f"act_{act_id}/adspixels", {"fields": "id", "limit": 10}).get("data") or []
            except Exception:
                pxs = []
            if pxs:
                new_px = str(pxs[0].get("id") or "")
                if new_px:
                    p2 = dict(payload)
                    po = dict(p2.get("promoted_object") or {})
                    po["pixel_id"] = new_px
                    p2["promoted_object"] = po
                    r = fb.post(f"act_{act_id}/adsets", p2)
                    if isinstance(r, dict):
                        r["_pixel_swapped"] = new_px
                    return r
        raise


def deploy_one_account(fb: FbClient, *, act_id: str, objective: str, conversion_goal: str,
                       page_id: str, pixel_id: str, landing_url: str,
                       daily_budget: int, budget_mode: str, bid_strategy: str,
                       name_prefix: str, headline: str, body: str, cta_type: str,
                       image_hash: str = "", video_id: str = "", video_thumb_hash: str = "",
                       subcode_slug: str = "", subcode_link=None,
                       targeting=None, ad_language: str = "",
                       lead_form_id: str = "", message_template: str = "",
                       dsa_beneficiary: str = "", dsa_payor: str = "",
                       optimization_goal: str = "", billing_event: str = "",
                       destination_type_override: str = "",
                       page_post_id: str = "",
                       advanced_config: dict | None = None,
                       budget_type: str = "daily",
                       lifetime_budget: int | None = None,
                       start_time: str = "",
                       end_time: str = "",
                       pacing: str = "",
                       bid_amount: int | None = None,
                       minimum_roas: float | None = None,
                       special_ad_categories: list | None = None,
                       description: str = "",
                       spend_cap: int | None = None,
                       instagram_actor_id: str = "",
                       conv_location: str = "",
                       whatsapp_phone_number: str = "",
                       placements: dict | None = None) -> dict:
    """Campaign → AdSet → Creative → Ad。返回 {campaign_id, adset_id, ad_id, page_post_id}。失败 raise FbApiError。

    subcode_link：预先解析好的 LandingAdLink（或 None）；用于 effective_url + 回绑 ad_id。
    page_post_id：dev app 走 object_story_id（调用方已建/复用主页帖传入）；空=走 object_story_spec（standard app）。
    conv_location / placements / whatsapp_phone_number：批次I 转化位置/版位/CTW 号码（空=存量行为）。
    """
    from .ad_builder import parse_message_template  # 局部 import 避免循环
    act = f"act_{act_id}"
    # 统一派生目的地/成效目标（批次I）：is_messaging 门与消息类 CTA 都以此为准——
    # 旧门只看 conversion_goal 词表（UI 永远给不出）导致欢迎语死链（盘点 A1）
    _dest, _opt = resolve_adset_destination(objective, conv_location, conversion_goal,
                                            optimization_goal)

    # 1. Campaign（目标感知）
    camp_payload = build_campaign(
        name=name_prefix, objective=objective,
        daily_budget=(daily_budget if (budget_mode.upper() == "CBO"
                                       and budget_type.lower() != "lifetime") else None),
        lifetime_budget=(lifetime_budget if (budget_mode.upper() == "CBO"
                                             and budget_type.lower() == "lifetime") else None),
        budget_mode=budget_mode, bid_strategy=bid_strategy,
        special_ad_categories=special_ad_categories,
        spend_cap=spend_cap,
    )
    camp = fb.post(f"{act}/campaigns", camp_payload)
    campaign_id = camp.get("id")
    if not campaign_id:
        raise FbApiError("no_id", f"FB 创建 campaign 未返回 id（响应：{str(camp)[:200]}）")

    # 2. AdSet（目标感知 + 受众）
    # 出价单一管道（批次II 修审计 G2②）：模板出价控制（bid_amount_usd 按账户本币换算后的
    # bid_amount 形参）非空时，advanced_config 里的 adv.bid_amount（旧 CPA 性能目标存的
    # 美分原始值）剥离——深合并会覆盖换算值，非 USD 账户出价额错一个汇率量级。
    # 两者都空维持旧行为（adv.bid_amount 直通）。浅拷贝剥离，不动调用方 dict（跨 item 共享）。
    _adv = advanced_config
    if advanced_config and bid_amount is not None and "bid_amount" in advanced_config:
        _adv = {k: v for k, v in advanced_config.items() if k != "bid_amount"}
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
        extra=_adv,
        # 平铺模式 Advantage+ 受众启发式：手动兴趣（flexible_spec）存在=原始受众（发 0），否则 FB 默认开
        advantage_audience=not bool((targeting or {}).get("flexible_spec")),
        budget_type=budget_type, lifetime_budget=lifetime_budget,
        start_time=start_time, end_time=end_time, pacing=pacing,
        bid_amount=bid_amount, minimum_roas=minimum_roas,
        conv_location=conv_location, placements=placements,
        whatsapp_phone_number=whatsapp_phone_number,
    )
    adset = post_adset_resilient(fb, act_id, adset_payload)
    adset_id = adset.get("id")
    if not adset_id:
        raise FbApiError("no_id", f"FB 创建 adset 未返回 id（响应：{str(adset)[:200]}）")

    # 3. 创意链接（子码集成）。base 必须来自调用方解析好的落地页行/模板 URL——
    # 旧 tovaads.com 兜底是死链（页不在该域），宁可快失败也不让死 URL 进 FB（批次II 修 B5 残留）
    effective_url = landing_url
    if subcode_slug and subcode_link is not None:
        if not landing_url:
            raise FbApiError("no_id", "已选子码但缺少可用落地 URL（模板未绑落地页且落地 URL 为空），请绑定落地页或填写落地 URL")
        effective_url = f"{landing_url}/a/{subcode_slug}?ad=" + "{{ad.id}}"  # FB 宏（双花括号——Meta 文档/1.0 生产口径；单花括号 FB 不替换=归因全死，2026-09-08 调研实证）

    # 3b. 欢迎语（消息类广告前置；批次I 门统一：按派生目的地/成效目标判定，不再查 conversion_goal 词表）
    welcome_msg = None
    _is_msg = is_messaging_destination(_dest, _opt)
    _msg_channel = "whatsapp" if (_dest == "WHATSAPP" or conv_location.strip().lower() == "whatsapp") else "messenger"
    if _is_msg and page_id:
        if _dest == "MESSENGER":
            try:
                pf = fb.get(page_id, {"fields": "messaging_feature_status"})
                mfs = (pf.get("messaging_feature_status") or {})
                if (mfs.get("USER_MESSAGING") or "").upper() != "ENABLED":
                    raise FbApiError("no_id", "主页未开启 messaging，无法投放私信广告")
            except FbApiError:
                raise
            except Exception:
                pass
        allow_cjk = True  # FB 接受消息里的中日韩字符；原 ad_language code 不匹配 bug 已移除
        welcome_msg = parse_message_template(message_template, allow_cjk=allow_cjk,
                                             channel=_msg_channel)

    creative = build_creative(
        page_id=page_id, objective=objective, conversion_goal=conversion_goal,
        landing_url=effective_url, headline=headline, body=body,
        image_hash=image_hash, cta_type=cta_type, video_id=video_id,
        video_thumb_hash=video_thumb_hash,
        lead_form_id=lead_form_id, welcome_message=welcome_msg,
        description=description,
        instagram_actor_id=instagram_actor_id,
        app_destination=(_dest if _is_msg else ""),
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
            raise FbApiError("no_id", f"建 creative(object_story_id) 未返回 id：{str(cr)[:200]}")
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
        raise FbApiError("no_id", f"FB 创建 ad 未返回 id（响应：{str(ad)[:200]}）")

    # 子码标注广告名（可追溯）+ 回绑 ad_id（last-wins 守卫：已绑不同广告不覆盖）
    if subcode_slug and subcode_link is not None:
        try:
            fb.post(ad_id, {"name": f"[子码:{subcode_slug}] {name_prefix}"})
        except Exception:
            pass
        if not bind_link_ad_id(subcode_link, ad_id):
            _lg.warning("子码 %s 已绑广告 %s，跳过回绑新广告 %s（last-wins 守卫）",
                        subcode_slug, getattr(subcode_link, "ad_id", ""), ad_id)

    out = {"campaign_id": campaign_id, "adset_id": adset_id, "ad_id": ad_id, "page_post_id": page_post_id}
    # 像素自愈/受众强制标记透传（调用方留痕+回写落地页，批AZ 统一口径）
    if adset.get("_pixel_swapped"):
        out["pixel_swapped"] = adset["_pixel_swapped"]
    if adset.get("_advantage_forced"):
        out["advantage_forced"] = True
    return out


# ── TikTok 部署链路（TK P3；与上面 FB 链平行，FB 函数零改动）──

def tt_client_for_account(db, tenant_id: int, act_id: str):
    """按账户选 TtClient（写令牌语义）。thin 包装：唯一实现在 fb_tokens（带 app_id +
    refresher——access_token 24h 请求间隙过期自动轮换），这里只保持部署链路旧签名。"""
    from .fb_tokens import tt_client_for_account as _pick
    tt, _cred = _pick(db, tenant_id, act_id, "write")
    return tt


def ensure_tt_file_id_for_account(tt, db, asset, advertiser_id: str, filepath: str) -> str:
    """取该广告主的素材 file_id（TT file_id 按 advertiser 隔离，不能跨账户复用）。

    查 asset.tt_file_ids[advertiser_id] 缓存；无 → 上传到该广告主文件库 → 行锁合并写回缓存
    （调用方 commit）。图片走 upload_ad_image、视频走 upload_ad_video（大文件分块，耗时较长）。
    """
    cache = {}
    if asset.tt_file_ids:
        try:
            cache = json.loads(asset.tt_file_ids)
        except Exception:
            cache = {}
    v = cache.get(str(advertiser_id))
    if v:
        return v
    with open(filepath, "rb") as f:
        file_bytes = f.read()
    if (asset.type or "image") == "video":
        result = tt.upload_ad_video(advertiser_id, file_bytes, asset.filename or "video.mp4")
    else:
        result = tt.upload_ad_image(advertiser_id, file_bytes, asset.filename or "image.jpg")
    fid = result.get("file_id")
    if not fid:
        raise TtApiError("no_id", f"上传素材到 TT advertiser {advertiser_id} 未返回 file_id")
    _merge_asset_cache(db, asset, "tt_file_ids", str(advertiser_id), str(fid))
    db.flush()
    return str(fid)


def deploy_one_account_tt(tt, *, advertiser_id: str, objective: str, conversion_goal: str,
                          pixel_code: str, landing_url: str, daily_budget: int,
                          budget_mode: str, name_prefix: str, headline: str, body: str,
                          cta_type: str, image_file_id: str = "", video_file_id: str = "",
                          subcode_slug: str = "", subcode_link=None, targeting=None) -> dict:
    """TT 三件套：campaign/create → adgroup/create → ad/create。失败 raise TtApiError。

    与 FB deploy_one_account 平行；差异：定向/预算全在 adgroup 层、素材用文件库 file_id、
    广告出生暂停（operation_status=DISABLE，对应 FB 的 status=PAUSED）。
    page_post/表单/消息模板为 FB 专属，TT 链路不涉及。
    """
    from .tt_ad_builder import (build_tt_campaign, build_tt_adgroup, build_tt_creative)

    # 1. Campaign（objective 映射 FB 枚举 → TT）
    camp_payload = build_tt_campaign(
        name=name_prefix, objective=objective,
        daily_budget=daily_budget if budget_mode.upper() == "CBO" else None,
        budget_mode=budget_mode,
    )
    camp = tt.create_campaign(advertiser_id, camp_payload)
    campaign_id = camp["campaign_id"]

    # 2. AdGroup（定向/优化/预算全在此层；转化目标绑像素 code）
    adgroup_payload = build_tt_adgroup(
        name=f"{name_prefix} 组", campaign_id=campaign_id, daily_budget=daily_budget,
        objective=objective, conversion_goal=conversion_goal, pixel_code=pixel_code,
        budget_mode=budget_mode, targeting=targeting,
    )
    adgroup = tt.create_adgroup(advertiser_id, adgroup_payload)
    adgroup_id = adgroup["adgroup_id"]

    # 3. 创意链接（子码集成：TT 广告 ID 宏是 __AID__，对应 FB 的 {ad.id}）
    effective_url = landing_url
    if subcode_slug and subcode_link is not None:
        base = landing_url or "https://tovaads.com"
        effective_url = f"{base}/a/{subcode_slug}?ad=__AID__"

    creative_payload = build_tt_creative(
        ad_text=body, cta_type=cta_type, landing_url=effective_url,
        video_file_id=video_file_id, image_file_id=image_file_id,
    )
    # 广告出生暂停（对齐 FB PAUSED 出生）：审核前绝不投放，用户在 TT 后台审核通过后手动开
    ad = tt.create_ad(advertiser_id, {
        "ad_name": f"{name_prefix} 广告",
        "adgroup_id": adgroup_id,
        **creative_payload,
        "operation_status": "DISABLE",
    })
    ad_id = ad["ad_id"]

    # 子码回绑 ad_id（TT 不支持建后改名标注——FB 的 [子码:slug] 改名省略，回绑已保证可追溯；
    # last-wins 守卫：已绑不同广告不覆盖）
    if subcode_slug and subcode_link is not None:
        if not bind_link_ad_id(subcode_link, ad_id):
            _lg.warning("子码 %s 已绑广告 %s，跳过回绑新广告 %s（last-wins 守卫）",
                        subcode_slug, getattr(subcode_link, "ad_id", ""), ad_id)

    return {"campaign_id": campaign_id, "adgroup_id": adgroup_id, "ad_id": ad_id}
