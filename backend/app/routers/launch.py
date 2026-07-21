"""铺广告路由：预检 + 多目标创建（Campaign→AdSet→Ad）。

支持全部主流目标（购物/潜在客户/互动/流量/消息），
通过 ad_builder 按目标自动构造正确参数。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from ..core.database import get_db
from ..core.deps import CurrentUser, require_permission
from ..core.encryption import decrypt
from ..core.fb_client import FbClient, FbApiError
from ..core.log_utils import write_log, new_trace_id
from ..core.ad_builder import (
    build_campaign, build_adset, build_creative,
    build_lead_form_payload, lead_form_safe_payload,
    parse_message_template, build_targeting,
)
from ..models.fb import Account, FbCredential
from ..models.launch import LandingAdLink
from ..models.audience import SavedAudience
from ..schemas.launch import PrecheckIn, PrecheckItem, PrecheckOut

router = APIRouter(prefix="/launch", tags=["launch"])

_PIXEL_REQUIRED = {"OUTCOME_SALES", "OUTCOME_CONVERSIONS", "CONVERSIONS", "OUTCOME_PRODUCT_CATALOG_SALES"}
_LANDING_REQUIRED = {"OUTCOME_SALES", "OUTCOME_CONVERSIONS", "CONVERSIONS", "OUTCOME_TRAFFIC", "LINK_CLICKS",
                     "OUTCOME_LEADS", "LEAD_GENERATION"}
_PAGE_REQUIRED = {"OUTCOME_SALES", "OUTCOME_LEADS", "OUTCOME_ENGAGEMENT", "PAGE_LIKES", "OUTCOME_TRAFFIC",
                  "OUTCOME_CONVERSIONS", "OUTCOME_MESSAGES"}


# ── 预检 ──
@router.post("/precheck", response_model=PrecheckOut)
def precheck(body: PrecheckIn, user: CurrentUser = Depends(require_permission("ads.create")),
             db: Session = Depends(get_db)):
    items: list[PrecheckItem] = []
    acc = db.query(Account).filter(Account.act_id == body.act_id).first()
    if not acc:
        items.append(PrecheckItem(key="account", label="广告账户", status="fail", msg=f"未找到账户 act_{body.act_id}"))
    elif acc.account_status != 1:
        items.append(PrecheckItem(key="account", label="广告账户", status="fail", msg=f"账户状态异常"))
    else:
        items.append(PrecheckItem(key="account", label="广告账户", status="pass", msg=f"账户「{acc.name}」正常"))
    cred = db.query(FbCredential).filter(
        FbCredential.tenant_id == user.tenant_id, FbCredential.status == "active"
    ).first()
    items.append(PrecheckItem(key="token", label="FB 凭证", status="pass" if cred else "fail",
                              msg="凭证有效" if cred else "未绑定 FB 凭证"))
    if body.objective in _PAGE_REQUIRED and not body.page_id:
        items.append(PrecheckItem(key="page", label="主页", status="fail", msg="需要主页 page_id"))
    elif body.page_id:
        items.append(PrecheckItem(key="page", label="主页", status="pass", msg=f"已选 {body.page_id}"))
    if body.objective in _PIXEL_REQUIRED and not body.pixel_id:
        items.append(PrecheckItem(key="pixel", label="像素", status="fail", msg="此目标需要像素"))
    elif body.pixel_id:
        items.append(PrecheckItem(key="pixel", label="像素", status="pass", msg=f"已配 {body.pixel_id}"))
    if body.objective in _LANDING_REQUIRED and not body.landing_url and not body.subcode_slug:
        items.append(PrecheckItem(key="landing", label="落地页", status="fail", msg="需要落地页或子码"))
    elif body.subcode_slug:
        items.append(PrecheckItem(key="landing", label="落地页", status="pass", msg=f"子码 /a/{body.subcode_slug}"))
    elif body.landing_url:
        items.append(PrecheckItem(key="landing", label="落地页", status="pass", msg="自定义链接"))
    items.append(PrecheckItem(key="bid", label="竞价", status="pass", msg=body.bid_strategy or "默认"))
    fails = sum(1 for i in items if i.status == "fail")
    return PrecheckOut(pass_=fails == 0, items=items)


# ── 多目标创建 ──
class LaunchAdIn(BaseModel):
    act_id: str
    objective: str = "OUTCOME_SALES"
    conversion_goal: str = ""
    page_id: str = ""
    pixel_id: str = ""
    landing_url: str = ""
    daily_budget: int = 200000  # VND ~$8
    budget_mode: str = "ABO"
    bid_strategy: str = "LOWEST_COST_WITHOUT_CAP"
    name_prefix: str = "Tova Ads"
    headline: str = ""
    body: str = ""
    image_hash: str = ""
    cta_type: str = ""  # SHOP_NOW / SIGN_UP / LEARN_MORE / ...
    video_id: str = ""
    subcode_slug: str = ""  # 子码（自动生成创意链接 + 广告改名标注）
    lead_form_id: str = ""  # Instant Forms 表单 ID（OUTCOME_LEADS + lead_generation 时绑创意 CTA）
    message_template: str = ""  # Messenger 欢迎语（JSON 串 / 纯文本 / dict 的 JSON；OUTCOME_ENGAGEMENT+conversations 用）
    ad_language: str = ""  # "zh"/"en"/... 控制 CJK 守卫（非 CJK 语言禁 CJK 字符）
    audience_id: int = 0  # 受众模板 id（saved_audiences，v1 仅兴趣受众）；0=用默认定向


@router.post("/create")
def launch_ad(body: LaunchAdIn, user: CurrentUser = Depends(require_permission("ads.create")),
              db: Session = Depends(get_db)):
    """多目标创建 FB 广告：Campaign → AdSet → Ad。

    根据 objective + conversion_goal 自动构造正确参数（ad_builder）。
    支持：购物/潜在客户/互动(主页赞/帖子互动/消息)/流量/ awareness。
    """
    from ..core.fb_tokens import client_for_account
    fb = client_for_account(db, user.tenant_id, body.act_id, "write")  # 创建广告用写令牌(operate/manage)
    if not fb:
        raise HTTPException(400, "未绑定 FB 凭证")
    trace_id = new_trace_id()
    act = f"act_{body.act_id}"

    try:
        # 1. Campaign（目标感知）
        camp_payload = build_campaign(
            name=body.name_prefix, objective=body.objective,
            daily_budget=body.daily_budget if body.budget_mode.upper() == "CBO" else None,
            budget_mode=body.budget_mode, bid_strategy=body.bid_strategy,
        )
        camp = fb.post(f"{act}/campaigns", camp_payload)
        campaign_id = camp["id"]

        # 2. AdSet（目标感知：promoted_object + destination_type 自动构造）
        # 受众模板（v1 仅兴趣）：audience_id 给了 → 加载 + build_targeting
        targeting = None
        if body.audience_id:
            import json as _json
            aud = db.query(SavedAudience).filter(
                SavedAudience.id == body.audience_id,
                SavedAudience.tenant_id == user.tenant_id,
                SavedAudience.status == "active",
            ).first()
            if not aud:
                raise HTTPException(400, f"受众模板 {body.audience_id} 不存在或已停用")
            targeting = build_targeting(
                countries=_json.loads(aud.countries or "[]"),
                interests=_json.loads(aud.interests_json or "[]"),
                age_min=aud.age_min, age_max=aud.age_max,
                gender=aud.gender, strategy=aud.strategy or "broad_interest",
            )
        adset_payload = build_adset(
            name=f"{body.name_prefix} 组", campaign_id=campaign_id,
            daily_budget=body.daily_budget, objective=body.objective,
            conversion_goal=body.conversion_goal, page_id=body.page_id,
            pixel_id=body.pixel_id, landing_url=body.landing_url,
            bid_strategy=body.bid_strategy, budget_mode=body.budget_mode,
            targeting=targeting,
        )
        adset = fb.post(f"{act}/adsets", adset_payload)
        adset_id = adset["id"]

        # 3. Ad creative（目标感知 + CTA + 子码链接）
        # 子码集成：如果给了 subcode_slug → 用子码链接做创意链接
        effective_url = body.landing_url
        if body.subcode_slug:
            from ..models.launch import LandingAdLink
            link = db.query(LandingAdLink).filter(
                LandingAdLink.slug == body.subcode_slug).first()
            if link:
                # 子码链接 = landing_url/a/{slug}?ad={{ad.id}}
                # FB 的 {{ad.id}} 宏会在广告上线后自动替换
                base = body.landing_url or "https://tovaads.com"
                effective_url = f"{base}/a/{body.subcode_slug}?ad={{{'{'}ad.id{'}'}}}"
            else:
                raise HTTPException(400, f"子码 /a/{body.subcode_slug} 不存在")

        # 3b. Messenger 欢迎语（消息广告）+ 私信前置校验（02_附录_消息模板 §1.3）
        welcome_msg = None
        is_messaging = (body.objective.upper() in ("OUTCOME_ENGAGEMENT", "OUTCOME_MESSAGES", "MESSAGES")
                        and body.conversion_goal.lower() in ("conversations", "messaging_purchase_conversion",
                                                              "messaging_appointment_conversion"))
        if is_messaging and body.page_id:
            # 私信前置：messaging_feature_status 必须 ENABLED
            try:
                pf = fb.get(body.page_id, {"fields": "messaging_feature_status"})
                mfs = (pf.get("messaging_feature_status") or {})
                if (mfs.get("USER_MESSAGING") or "").upper() != "ENABLED":
                    raise HTTPException(400, "主页未开启 messaging，无法投放私信广告（请在 FB 主页设置开启）")
            except HTTPException:
                raise
            except Exception:
                pass  # 读取失败不阻断（容错），FB 创建时会再校验
            # 解析 message_template（JSON 串 / 纯文本 / 空）
            allow_cjk = not body.ad_language or body.ad_language.lower() in ("zh", "ja", "ko", "zh-cn", "zh-tw")
            try:
                welcome_msg = parse_message_template(body.message_template, allow_cjk=allow_cjk)
            except ValueError as e:
                raise HTTPException(400, str(e))

        creative = build_creative(
            page_id=body.page_id, objective=body.objective,
            conversion_goal=body.conversion_goal, landing_url=effective_url,
            headline=body.headline, body=body.body, image_hash=body.image_hash,
            cta_type=body.cta_type, video_id=body.video_id,
            lead_form_id=body.lead_form_id,
            welcome_message=welcome_msg,
        )
        ad = fb.post(f"{act}/ads", {
            "name": f"{body.name_prefix} 广告",
            "adset_id": adset_id, "status": "ACTIVE",
            "creative": creative,
        })
        ad_id = ad["id"]

        # 子码标注广告名（FB Ads Manager 可追溯）
        if body.subcode_slug:
            try:
                fb.post(ad_id, {"name": f"[子码:{body.subcode_slug}] {body.name_prefix}"})
            except Exception:
                pass  # 改名失败不阻断

        # 回绑子码 ad_id
        if body.subcode_slug and link:
            link.ad_id = ad_id
            link.status = "active"

        write_log(db, tenant_id=user.tenant_id, trace_id=trace_id, actor_type="user",
                  actor_user_id=user.id, target_type="ad", target_id=ad_id,
                  action_type="create", source="fb_api", result="success",
                  metadata={"campaign_id": campaign_id, "adset_id": adset_id,
                            "objective": body.objective, "conversion_goal": body.conversion_goal})
        db.commit()
        return {"campaign_id": campaign_id, "adset_id": adset_id, "ad_id": ad_id,
                "trace_id": trace_id, "status": "ACTIVE",
                "objective": body.objective, "conversion_goal": body.conversion_goal}

    except FbApiError as e:
        write_log(db, tenant_id=user.tenant_id, trace_id=trace_id, actor_type="user",
                  actor_user_id=user.id, target_type="ad", action_type="create",
                  source="fb_api", result="fail",
                  raw_error=str(e.raw), friendly_error=e.friendly)
        db.commit()
        raise HTTPException(400, f"创建失败：{e.friendly}")


# ── Lead Form（Instant Forms）创建 ── 详见 02_附录_表单字段.md
class LeadFormQuestionIn(BaseModel):
    key: str = ""
    label: str = ""
    placeholder: str = ""
    options: list[dict] = []  # [{"key":"morning","value":"上午"}, ...]


class LeadFormIn(BaseModel):
    page_id: str
    form_title: str
    privacy_url: str
    locale: str = "en_US"
    target_countries: list[str] = []
    description: str = ""
    custom_questions: list[LeadFormQuestionIn] = []
    extra_contact_fields: list[str] = []  # EMAIL/PHONE/CITY/...（FB 内置 type，除自动选的以外追加）
    privacy_link_text: str = "Privacy Policy"
    thank_you_title: str = ""
    thank_you_body: str = ""
    thank_you_button_text: str = ""
    thank_you_website_url: str = ""
    follow_up_url: str = ""
    context_card_title: str = ""
    name_prefix: str = "Manual"  # AI 路径传 "AI"，会跳过 context_card


@router.post("/lead-form")
def create_lead_form(body: LeadFormIn, user: CurrentUser = Depends(require_permission("ads.create")),
                     db: Session = Depends(get_db)):
    """创建 Instant Form（潜在客户表单）。返回 form_id 供 /launch/create 的 lead_form_id 用。

    实现规格见 02_附录_表单字段.md：嵌套字段 JSON 编码、安全 URL 过滤、
    368/1346003 风控重试安全版、联系字段国家路由。
    """
    from ..core.fb_tokens import first_client
    fb = first_client(db, user.tenant_id)  # lead-form 是 page 级，无 act_id → 任一 active token
    if not fb:
        raise HTTPException(400, "未绑定 FB 凭证")
    trace_id = new_trace_id()

    payload = build_lead_form_payload(
        form_title=body.form_title, privacy_url=body.privacy_url, locale=body.locale,
        target_countries=body.target_countries, description=body.description,
        custom_questions=[q.model_dump() for q in body.custom_questions],
        extra_contact_fields=body.extra_contact_fields,
        privacy_link_text=body.privacy_link_text,
        thank_you_title=body.thank_you_title, thank_you_body=body.thank_you_body,
        thank_you_button_text=body.thank_you_button_text,
        thank_you_website_url=body.thank_you_website_url,
        follow_up_url=body.follow_up_url,
        context_card_title=body.context_card_title,
        name_prefix=body.name_prefix,
    )

    try:
        result = fb.post(f"{body.page_id}/leadgen_forms", payload)
        form_id = result["id"]

        write_log(db, tenant_id=user.tenant_id, trace_id=trace_id, actor_type="user",
                  actor_user_id=user.id, target_type="leadgen_form", target_id=form_id,
                  action_type="create", source="fb_api", result="success",
                  metadata={"page_id": body.page_id, "locale": body.locale,
                            "questions": len(payload.get("questions", []))})
        db.commit()
        return {"form_id": form_id, "trace_id": trace_id,
                "questions": payload.get("questions", []),
                "locale": body.locale}

    except FbApiError as e:
        # 368/1346003 风控 → 重试安全版（02_附录 §2.9）
        code = (e.raw or {}).get("code", 0)
        retried = False
        if code in (368, 1346003):
            try:
                safe = lead_form_safe_payload(payload)
                result = fb.post(f"{body.page_id}/leadgen_forms", safe)
                form_id = result["id"]
                retried = True
                write_log(db, tenant_id=user.tenant_id, trace_id=trace_id, actor_type="user",
                          actor_user_id=user.id, target_type="leadgen_form", target_id=form_id,
                          action_type="create", source="fb_api", result="success",
                          metadata={"page_id": body.page_id, "safe_retry": True})
                db.commit()
                return {"form_id": form_id, "trace_id": trace_id, "safe_retry": True,
                        "questions": safe.get("questions", []), "locale": body.locale}
            except FbApiError as e2:
                e = e2  # 安全版也失败 → 记失败日志后报错

        write_log(db, tenant_id=user.tenant_id, trace_id=trace_id, actor_type="user",
                  actor_user_id=user.id, target_type="leadgen_form", action_type="create",
                  source="fb_api", result="fail",
                  raw_error=str(e.raw), friendly_error=e.friendly,
                  metadata={"safe_retry_attempted": retried})
        db.commit()
        raise HTTPException(400, f"表单创建失败：{e.friendly}")
