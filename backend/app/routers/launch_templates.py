"""投放模板 + 批量部署路由。

模板 = 可复用的广告结构 + 素材 + 文案（[[auto-launch-architecture-plan]] 模块 2）。
部署 = 选模板 + 选 N 账户 → BackgroundTasks 异步逐账户建广告（Campaign→AdSet→Ad），per-item 状态。
"""
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from ..core.database import get_db, SessionLocal, SuperSessionLocal
from ..core.deps import CurrentUser, require_permission
from ..core.log_utils import write_log, new_trace_id
from ..core.fb_tokens import client_for_account
from ..core.fb_client import FbApiError
from ..core.ad_builder import build_targeting, build_campaign, build_adset, build_creative
from ..core.ad_ops import deploy_one_account, ensure_image_hash_for_account, usd_to_fb_amount
from ..models.launch_template import LaunchTemplate, LaunchJob, LaunchJobItem
from ..models.launch import Asset, LandingAdLink
from ..models.audience import SavedAudience
from ..models.fb import Account
from ..models.perf import CurrencyRate
import os

router = APIRouter(prefix="/launch-templates", tags=["launch-templates"])

ASSET_DIR = os.environ.get("ASSET_DIR", "/opt/toveads/assets")


def _tpl_dict(t: LaunchTemplate) -> dict:
    return {
        "id": t.id, "name": t.name, "description": t.description or "",
        "objective": t.objective, "conversion_goal": t.conversion_goal or "",
        "budget_mode": t.budget_mode, "bid_strategy": t.bid_strategy,
        "daily_budget": t.daily_budget, "budget_usd": t.budget_usd, "name_prefix": t.name_prefix,
        "optimization_goal": t.optimization_goal or "", "billing_event": t.billing_event or "",
        "destination_type": t.destination_type or "",
        "audience_id": t.audience_id or 0, "audience_json": t.audience_json or "",
        "advanced_config": t.advanced_config or "",
        "asset_id": t.asset_id,
        "headline": t.headline or "", "body": t.body or "",
        "page_id": t.page_id or "", "pixel_id": t.pixel_id or "",
        "landing_url": t.landing_url or "", "cta_type": t.cta_type or "",
        "subcode_slug": t.subcode_slug or "", "ad_language": t.ad_language or "",
        "message_template": t.message_template or "", "lead_form_id": t.lead_form_id or "",
        "beneficiary": t.beneficiary or "", "payer": t.payer or "",
        "status": t.status, "deploy_count": t.deploy_count or 0,
        "created_at": str(t.created_at) if t.created_at else "",
    }


# ── 模板 CRUD ──
class TemplateIn(BaseModel):
    name: str
    description: str = ""
    objective: str = "OUTCOME_SALES"
    conversion_goal: str = ""
    budget_mode: str = "ABO"
    bid_strategy: str = "LOWEST_COST_WITHOUT_CAP"
    daily_budget: int = 0
    budget_usd: Optional[float] = None
    name_prefix: str = "Tova Ads"
    optimization_goal: str = ""
    billing_event: str = ""
    destination_type: str = ""
    audience_id: int = 0
    audience_json: str = ""
    advanced_config: str = ""
    asset_id: Optional[int] = None
    headline: str = ""
    body: str = ""
    page_id: str = ""
    pixel_id: str = ""
    landing_url: str = ""
    cta_type: str = ""
    subcode_slug: str = ""
    ad_language: str = ""
    message_template: str = ""
    lead_form_id: str = ""
    beneficiary: str = ""
    payer: str = ""


@router.get("")
def list_templates(user: CurrentUser = Depends(require_permission("ads.create")),
                   db: Session = Depends(get_db)):
    rows = db.query(LaunchTemplate).filter(
        LaunchTemplate.tenant_id == user.tenant_id,
        LaunchTemplate.status != "archived",
    ).order_by(LaunchTemplate.id.desc()).all()
    return [_tpl_dict(t) for t in rows]


@router.post("")
def create_template(body: TemplateIn,
                    user: CurrentUser = Depends(require_permission("ads.create")),
                    db: Session = Depends(get_db)):
    t = LaunchTemplate(tenant_id=user.tenant_id, created_by=user.id, status="draft", **body.model_dump())
    db.add(t)
    db.flush()
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, target_type="launch_template", target_id=str(t.id),
              action_type="create", source="user", result="success", metadata={"name": body.name})
    db.commit()
    return _tpl_dict(t)


@router.put("/{tid}")
def update_template(tid: int, body: TemplateIn,
                    user: CurrentUser = Depends(require_permission("ads.create")),
                    db: Session = Depends(get_db)):
    t = db.query(LaunchTemplate).filter(LaunchTemplate.id == tid, LaunchTemplate.tenant_id == user.tenant_id).first()
    if not t:
        raise HTTPException(404, "模板不存在")
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    db.commit()
    return _tpl_dict(t)


@router.delete("/{tid}")
def delete_template(tid: int, user: CurrentUser = Depends(require_permission("ads.create")),
                    db: Session = Depends(get_db)):
    t = db.query(LaunchTemplate).filter(LaunchTemplate.id == tid, LaunchTemplate.tenant_id == user.tenant_id).first()
    if not t:
        raise HTTPException(404, "模板不存在")
    t.status = "archived"  # 软删（保留部署历史）
    db.commit()
    return {"id": tid, "archived": True}


# ── 部署 ──
class DeployItem(BaseModel):
    act_id: str
    page_id: str = ""
    pixel_id: str = ""


class DeployIn(BaseModel):
    items: list[DeployItem]


@router.post("/{tid}/deploy")
def deploy_template(tid: int, body: DeployIn, bg: BackgroundTasks,
                    user: CurrentUser = Depends(require_permission("ads.create")),
                    db: Session = Depends(get_db)):
    """部署模板到多账户（异步）：建 job + items，BackgroundTasks 逐账户建广告。立即返 job_id。"""
    t = db.query(LaunchTemplate).filter(LaunchTemplate.id == tid, LaunchTemplate.tenant_id == user.tenant_id).first()
    if not t:
        raise HTTPException(404, "模板不存在")
    if not body.items:
        raise HTTPException(400, "至少选一个账户")
    job = LaunchJob(tenant_id=user.tenant_id, template_id=t.id, template_name=t.name,
                    status="pending", total=len(body.items), created_by=user.id)
    db.add(job)
    db.flush()
    for it in body.items:
        db.add(LaunchJobItem(job_id=job.id, tenant_id=user.tenant_id, act_id=it.act_id,
                             page_id=it.page_id, pixel_id=it.pixel_id, status="pending"))
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, target_type="launch_job", target_id=str(job.id),
              action_type="deploy", source="user", result="success",
              metadata={"template_id": t.id, "accounts": len(body.items)})
    db.commit()
    bg.add_task(_run_deploy_job, job.id, user.tenant_id, t.id)
    return {"job_id": job.id, "total": len(body.items)}


class PreflightIn(BaseModel):
    act_id: str
    page_id: str = ""
    pixel_id: str = ""


@router.post("/{tid}/preflight")
def preflight_deploy(tid: int, body: PreflightIn,
                     user: CurrentUser = Depends(require_permission("ads.create")),
                     db: Session = Depends(get_db)):
    """预检：构建（不发送）即将发给 FB 的完整 payload，供核对参数对应。

    返回 campaign/adset/creative 三个 dict + 预算本币换算明细 + 解析后的 targeting。
    不调 FB、不花钱、不建广告。用于真部署前核对每个字段是否和 FB 期望对得上。
    """
    t = db.query(LaunchTemplate).filter(LaunchTemplate.id == tid, LaunchTemplate.tenant_id == user.tenant_id).first()
    if not t:
        raise HTTPException(404, "模板不存在")
    targeting = _resolve_targeting(db, t.audience_id, t.audience_json or "")
    daily_budget_fb = _resolve_budget_fb(db, body.act_id, t, user.tenant_id)
    advanced = _parse_advanced(t)
    page_id = body.page_id or t.page_id
    pixel_id = body.pixel_id or t.pixel_id
    acc = db.query(Account).filter(Account.act_id == body.act_id).first()
    currency = (acc.currency if acc else "USD") or "USD"
    cr = db.query(CurrencyRate).filter(CurrencyRate.code == currency.upper()).first()
    try:
        campaign_payload = build_campaign(
            name=t.name_prefix, objective=t.objective,
            daily_budget=daily_budget_fb if t.budget_mode.upper() == "CBO" else None,
            budget_mode=t.budget_mode, bid_strategy=t.bid_strategy,
        )
        adset_payload = build_adset(
            name=f"{t.name_prefix} 组", campaign_id="<FB 创建 campaign 后返回>",
            daily_budget=daily_budget_fb, objective=t.objective,
            conversion_goal=t.conversion_goal, page_id=page_id, pixel_id=pixel_id,
            landing_url=t.landing_url, bid_strategy=t.bid_strategy, budget_mode=t.budget_mode,
            targeting=targeting, dsa_beneficiary=t.beneficiary or "", dsa_payor=t.payer or "",
            optimization_goal=t.optimization_goal or "", billing_event=t.billing_event or "",
            destination_type_override=t.destination_type or "", extra=advanced,
        )
        creative_payload = build_creative(
            page_id=page_id, objective=t.objective, conversion_goal=t.conversion_goal,
            landing_url=t.landing_url, headline=t.headline, body=t.body,
            cta_type=t.cta_type, image_hash="<部署时按账户上传缓存>",
        )
    except ValueError as e:
        # build_adset 对缺 pixel/page 等抛 ValueError —— 预检就该把这个告诉用户
        raise HTTPException(400, f"参数校验失败：{e}")
    return {
        "act_id": body.act_id, "currency": currency,
        "budget_usd": t.budget_usd, "fx_rate": (cr.rate if cr else None),
        "daily_budget_fb": daily_budget_fb, "budget_mode": t.budget_mode,
        "objective": t.objective, "optimization_goal": adset_payload.get("optimization_goal"),
        "billing_event": adset_payload.get("billing_event"),
        "targeting_resolved": targeting,
        "campaign": campaign_payload, "adset": adset_payload, "creative": creative_payload,
        "notes": [
            "image_hash/video_id 部署时按目标账户上传并缓存",
            "campaign_id / adset_id 部署时由 FB 返回填入",
            "成功判定：FB 返回 id→success；抛错或无 id→fail（item 记 campaign_id）",
        ],
    }


def _resolve_targeting(sdb, audience_id: int, audience_json: str = ""):
    """解析受众 → targeting dict。优先 audience_json（内联编辑），其次 SavedAudience，None=FB 默认。"""
    # 1. 内联 audience_json（投放模板编辑器直接编辑的受众）
    if audience_json and audience_json.strip():
        try:
            a = json.loads(audience_json)
            countries = a.get("countries") or []
            interests = a.get("interests") or []
            if isinstance(interests, dict):
                interests = [interests]
            if not isinstance(interests, list):
                interests = []
            resolved = [i for i in interests if isinstance(i, dict) and i.get("id")]
            if not countries and not resolved:
                return None  # 内联受众空 → 走 FB 默认
            t = build_targeting(
                countries=countries, interests=resolved,
                age_min=a.get("age_min") or 18, age_max=a.get("age_max") or 65,
                gender=a.get("gender") or 0, strategy=a.get("strategy") or "broad_interest",
            )
            # 用户指定语言（FB targeting.languages：[{id,name}] 或 [id] 透传）
            langs = a.get("languages") or []
            if langs and isinstance(langs, list):
                t["languages"] = langs
            return t
        except Exception:
            pass
    # 2. SavedAudience
    if not audience_id:
        return None
    aud = sdb.query(SavedAudience).filter(
        SavedAudience.id == audience_id, SavedAudience.status == "active").first()
    if not aud:
        return None
    return build_targeting(
        countries=json.loads(aud.countries or "[]"),
        interests=json.loads(aud.interests_json or "[]"),
        age_min=aud.age_min, age_max=aud.age_max, gender=aud.gender,
        strategy=aud.strategy or "broad_interest",
    )


def _resolve_budget_fb(sdb, act_id: str, tpl: LaunchTemplate, tenant_id: int = 0) -> int:
    """模板预算 → 该账户本币最小单位（FB daily_budget）。
    优先 budget_usd（美元，按账户 currency + 汇率转）；无则回退 legacy daily_budget。"""
    if tpl.budget_usd and tpl.budget_usd > 0:
        q = sdb.query(Account).filter(Account.act_id == act_id)
        if tenant_id:
            q = q.filter(Account.tenant_id == tenant_id)
        acc = q.first()
        currency = (acc.currency if acc else "USD") or "USD"
        cr = sdb.query(CurrencyRate).filter(CurrencyRate.code == currency.upper()).first()
        if not cr and currency.upper() != "USD":
            raise ValueError(f"缺少 {currency} 汇率（fx_sync 未同步该币种），无法转换预算。请在系统设置手动配置或先 USD 部署")
        rate = cr.rate if cr else 1.0
        return usd_to_fb_amount(tpl.budget_usd, currency, rate)
    return tpl.daily_budget if tpl.daily_budget and tpl.daily_budget > 0 else 200000


def _parse_advanced(tpl: LaunchTemplate) -> dict | None:
    """解析模板的 advanced_config JSON（高级 FB 字段）。"""
    if not tpl.advanced_config or not tpl.advanced_config.strip():
        return None
    try:
        cfg = json.loads(tpl.advanced_config)
        return cfg if isinstance(cfg, dict) else None
    except Exception:
        return None


def _ai_auto_create_form(fb, sdb, asset: Asset, page_id: str, landing_url: str) -> str:
    """没选表单模板时，从素材 AI 文案自动生成 Instant Form + 建到 FB。返回 form_id。"""
    from ..core.ad_builder import build_lead_form_payload, lead_form_safe_payload
    from ..core.ai_client import AiClient, AiError
    ai = AiClient()
    if not ai.is_configured():
        return ""
    ai_copy = json.loads(asset.ai_copy_json or "{}") if asset.ai_copy_json else {}
    headlines = ai_copy.get("headlines", [])
    bodies = ai_copy.get("bodies", [])
    sys_msg = "你是 FB Instant Form 设计专家。根据广告素材信息设计潜在客户表单。严格只返回 JSON。"
    prompt = (
        f"广告标题参考：{headlines[:3]}\n广告正文参考：{bodies[:2]}\n\n"
        "生成 Instant Form 配置 JSON：\n"
        '{"form_title":"表单标题","description":"表单说明",'
        '"custom_questions":[{"key":"q1","label":"问题","placeholder":"提示"}],'
        '"extra_contact_fields":["EMAIL"],"thank_you_title":"感谢标题","thank_you_body":"感谢正文"}\n'
        "生成 2-3 个有意义的自定义问题。follow_up_url 不用填。"
    )
    data = ai.chat_json([{"role": "system", "content": sys_msg}, {"role": "user", "content": prompt}],
                        temperature=0.7, max_tokens=2048)
    payload = build_lead_form_payload(
        form_title=data.get("form_title", asset.name or "Lead Form"),
        privacy_url="https://tovaads.com/privacy",
        locale="en_US", target_countries=[], description=data.get("description", ""),
        custom_questions=data.get("custom_questions", []),
        extra_contact_fields=data.get("extra_contact_fields", ["EMAIL"]),
        thank_you_title=data.get("thank_you_title", ""),
        thank_you_body=data.get("thank_you_body", ""),
        thank_you_button_text="Visit Website" if landing_url else "",
        thank_you_website_url=landing_url,
        follow_up_url=landing_url,
        name_prefix="AI",
    )
    try:
        result = fb.post(f"{page_id}/leadgen_forms", payload)
        form_id = result.get("id")
        if not form_id:
            safe = lead_form_safe_payload(payload)
            result = fb.post(f"{page_id}/leadgen_forms", safe)
            form_id = result.get("id")
        return form_id or ""
    except Exception:
        return ""


def _run_deploy_job(job_id: int, tenant_id: int, template_id: int):
    """后台逐账户建广告。独立 SuperSessionLocal（bypass RLS，显式 tenant_id 过滤，避开 BackgroundTask 无请求上下文的 SET LOCAL 坑）。"""
    sdb = SuperSessionLocal()
    try:
        job = sdb.query(LaunchJob).filter(LaunchJob.id == job_id, LaunchJob.tenant_id == tenant_id).first()
        if not job:
            return
        tpl = sdb.query(LaunchTemplate).filter(LaunchTemplate.id == template_id).first()
        if not tpl:
            job.status = "failed"; job.finished_at = datetime.now(timezone.utc); sdb.commit(); return
        job.status = "running"; sdb.commit()
        asset = sdb.query(Asset).filter(Asset.id == tpl.asset_id).first() if tpl.asset_id else None
        targeting = _resolve_targeting(sdb, tpl.audience_id, tpl.audience_json or "")
        advanced = _parse_advanced(tpl)
        # 子码链接（一个 slug 共享多广告，{{ad.id}} 宏区分）
        link = None
        if tpl.subcode_slug:
            link = sdb.query(LandingAdLink).filter(LandingAdLink.slug == tpl.subcode_slug).first()
        items = sdb.query(LaunchJobItem).filter(LaunchJobItem.job_id == job_id).all()
        for item in items:
            try:
                item.status = "creating"; sdb.commit()
                fb = client_for_account(sdb, tenant_id, item.act_id, "write")
                if not fb:
                    raise FbApiError(f"act_{item.act_id} 未绑定写令牌", 0)
                # per-account 图片 hash（FB hash 按账户）
                image_hash = ""
                if asset and asset.type == "image":
                    filepath = os.path.join(ASSET_DIR, asset.storage_key)
                    if not os.path.exists(filepath):
                        raise FbApiError(f"素材文件丢失: {asset.storage_key}", 0)
                    image_hash = ensure_image_hash_for_account(fb, sdb, asset, item.act_id, filepath)
                    sdb.commit()  # 持久化 hash 缓存
                page_id = item.page_id or tpl.page_id
                pixel_id = item.pixel_id or tpl.pixel_id
                daily_budget_fb = _resolve_budget_fb(sdb, item.act_id, tpl, tenant_id)
                # 没选表单模板 → AI 从素材自动生成表单 + 建到 FB（LEADS 目标）
                lead_form_id = tpl.lead_form_id or ""
                if not lead_form_id and tpl.objective == "OUTCOME_LEADS" and page_id and asset:
                    try:
                        lead_form_id = _ai_auto_create_form(fb, sdb, asset, page_id, tpl.landing_url or "")
                    except Exception:
                        pass  # AI 生成/建表单失败不阻断主流程（FB 会用默认表单或报错）
                # 没选消息模板 → AI 从素材文案生成欢迎语（ENGAGEMENT+消息目标）
                message_template = tpl.message_template or ""
                if not message_template and tpl.objective == "OUTCOME_ENGAGEMENT" and asset:
                    try:
                        ai_copy = json.loads(asset.ai_copy_json or "{}") if asset.ai_copy_json else {}
                        bodies = ai_copy.get("bodies", [])
                        if bodies:
                            message_template = json.dumps({"text": bodies[0], "ice_breakers": []})
                    except Exception:
                        pass
                r = deploy_one_account(
                    fb, act_id=item.act_id, objective=tpl.objective, conversion_goal=tpl.conversion_goal,
                    page_id=page_id, pixel_id=pixel_id, landing_url=tpl.landing_url,
                    daily_budget=daily_budget_fb, budget_mode=tpl.budget_mode, bid_strategy=tpl.bid_strategy,
                    name_prefix=tpl.name_prefix, headline=tpl.headline, body=tpl.body, cta_type=tpl.cta_type,
                    image_hash=image_hash, subcode_slug=tpl.subcode_slug, subcode_link=link,
                    targeting=targeting, ad_language=tpl.ad_language,
                    dsa_beneficiary=tpl.beneficiary or "", dsa_payor=tpl.payer or "",
                    optimization_goal=tpl.optimization_goal or "", billing_event=tpl.billing_event or "",
                    destination_type_override=tpl.destination_type or "",
                    advanced_config=advanced,
                    lead_form_id=lead_form_id, message_template=message_template,
                )
                item.campaign_id = r["campaign_id"]; item.adset_id = r["adset_id"]; item.ad_id = r["ad_id"]
                item.status = "success"; item.error = None
                job.succeeded = (job.succeeded or 0) + 1
            except FbApiError as e:
                item.status = "fail"; item.error = (e.friendly or str(e))[:300]
                job.failed = (job.failed or 0) + 1
            except Exception as e:
                item.status = "fail"; item.error = str(e)[:300]
                job.failed = (job.failed or 0) + 1
            sdb.commit()
        tpl.deploy_count = (tpl.deploy_count or 0) + len(items)
        job.status = "partial_failed" if job.failed else "completed"
        job.finished_at = datetime.now(timezone.utc)
        sdb.commit()
    except Exception as e:
        try:
            job = sdb.query(LaunchJob).filter(LaunchJob.id == job_id).first()
            if job:
                job.status = "failed"; job.finished_at = datetime.now(timezone.utc); sdb.commit()
        except Exception:
            pass
    finally:
        sdb.close()


# ── Job 查询 ──
def _item_dict(it: LaunchJobItem) -> dict:
    return {
        "id": it.id, "act_id": it.act_id, "page_id": it.page_id or "", "pixel_id": it.pixel_id or "",
        "status": it.status, "campaign_id": it.campaign_id or "", "adset_id": it.adset_id or "",
        "ad_id": it.ad_id or "", "subcode_slug": it.subcode_slug or "", "error": it.error or "",
    }


@router.get("/jobs")
def list_jobs(user: CurrentUser = Depends(require_permission("ads.create")),
              db: Session = Depends(get_db), limit: int = 20):
    rows = db.query(LaunchJob).filter(LaunchJob.tenant_id == user.tenant_id) \
        .order_by(LaunchJob.id.desc()).limit(min(max(limit, 1), 100)).all()
    return [{
        "id": j.id, "template_id": j.template_id, "template_name": j.template_name or "",
        "status": j.status, "total": j.total, "succeeded": j.succeeded, "failed": j.failed,
        "created_at": str(j.created_at) if j.created_at else "",
        "finished_at": str(j.finished_at) if j.finished_at else "",
    } for j in rows]


@router.get("/jobs/{job_id}")
def get_job(job_id: int, user: CurrentUser = Depends(require_permission("ads.create")),
            db: Session = Depends(get_db)):
    j = db.query(LaunchJob).filter(LaunchJob.id == job_id, LaunchJob.tenant_id == user.tenant_id).first()
    if not j:
        raise HTTPException(404, "job 不存在")
    items = db.query(LaunchJobItem).filter(LaunchJobItem.job_id == job_id).all()
    return {
        "id": j.id, "template_id": j.template_id, "template_name": j.template_name or "",
        "status": j.status, "total": j.total, "succeeded": j.succeeded, "failed": j.failed,
        "created_at": str(j.created_at) if j.created_at else "",
        "finished_at": str(j.finished_at) if j.finished_at else "",
        "items": [_item_dict(it) for it in items],
    }


class RetryIn(BaseModel):
    page_id: str = ""
    pixel_id: str = ""


@router.post("/jobs/{job_id}/retry/{item_id}")
def retry_item(job_id: int, item_id: int, body: RetryIn, bg: BackgroundTasks,
               user: CurrentUser = Depends(require_permission("ads.create")),
               db: Session = Depends(get_db)):
    """重试一个失败 item（重置为 pending，再跑一次）。"""
    j = db.query(LaunchJob).filter(LaunchJob.id == job_id, LaunchJob.tenant_id == user.tenant_id).first()
    if not j:
        raise HTTPException(404, "job 不存在")
    it = db.query(LaunchJobItem).filter(LaunchJobItem.id == item_id, LaunchJobItem.job_id == job_id).first()
    if not it:
        raise HTTPException(404, "item 不存在")
    it.status = "pending"; it.error = None
    if body.page_id:
        it.page_id = body.page_id
    if body.pixel_id:
        it.pixel_id = body.pixel_id
    db.commit()
    bg.add_task(_retry_one, job_id, user.tenant_id, j.template_id, item_id)
    return {"job_id": job_id, "item_id": item_id, "retrying": True}


def _retry_one(job_id: int, tenant_id: int, template_id: int, item_id: int):
    """后台重跑单个 item（复用 deploy 逻辑，只跑这一个账户）。"""
    sdb = SuperSessionLocal()
    try:
        tpl = sdb.query(LaunchTemplate).filter(LaunchTemplate.id == template_id).first()
        if not tpl:
            return
        # 临时建一个只含该 item 的"job 视图"——直接调 deploy_one_account，更新该 item
        it = sdb.query(LaunchJobItem).filter(LaunchJobItem.id == item_id).first()
        if not it:
            return
        # 借用 _run_deploy_job 的单账户逻辑：把 job 的 total 固定，succeeded/failed 增量
        asset = sdb.query(Asset).filter(Asset.id == tpl.asset_id).first() if tpl.asset_id else None
        targeting = _resolve_targeting(sdb, tpl.audience_id, tpl.audience_json or "")
        advanced = _parse_advanced(tpl)
        link = sdb.query(LandingAdLink).filter(LandingAdLink.slug == tpl.subcode_slug).first() if tpl.subcode_slug else None
        job = sdb.query(LaunchJob).filter(LaunchJob.id == job_id).first()
        try:
            it.status = "creating"; sdb.commit()
            fb = client_for_account(sdb, tenant_id, it.act_id, "write")
            if not fb:
                raise FbApiError(f"act_{it.act_id} 未绑定写令牌", 0)
            image_hash = ""
            if asset and asset.type == "image":
                filepath = os.path.join(ASSET_DIR, asset.storage_key)
                image_hash = ensure_image_hash_for_account(fb, sdb, asset, it.act_id, filepath)
                sdb.commit()
            r = deploy_one_account(
                fb, act_id=it.act_id, objective=tpl.objective, conversion_goal=tpl.conversion_goal,
                page_id=it.page_id or tpl.page_id, pixel_id=it.pixel_id or tpl.pixel_id,
                landing_url=tpl.landing_url, daily_budget=_resolve_budget_fb(sdb, it.act_id, tpl, tenant_id),
                budget_mode=tpl.budget_mode, bid_strategy=tpl.bid_strategy, name_prefix=tpl.name_prefix,
                headline=tpl.headline, body=tpl.body, cta_type=tpl.cta_type, image_hash=image_hash,
                subcode_slug=tpl.subcode_slug, subcode_link=link, targeting=targeting, ad_language=tpl.ad_language,
                dsa_beneficiary=tpl.beneficiary or "", dsa_payor=tpl.payer or "",
                optimization_goal=tpl.optimization_goal or "", billing_event=tpl.billing_event or "",
                destination_type_override=tpl.destination_type or "",
                advanced_config=advanced,
                lead_form_id=tpl.lead_form_id or "", message_template=tpl.message_template or "",
            )
            it.campaign_id = r["campaign_id"]; it.adset_id = r["adset_id"]; it.ad_id = r["ad_id"]
            it.status = "success"; it.error = None
            if job:
                job.succeeded = (job.succeeded or 0) + 1
                if (job.failed or 0) > 0:
                    job.failed -= 1
                if job.succeeded + (job.failed or 0) >= (job.total or 0):
                    job.status = "partial_failed" if job.failed else "completed"
                    job.finished_at = datetime.now(timezone.utc)
        except FbApiError as e:
            it.status = "fail"; it.error = (e.friendly or str(e))[:300]
        except Exception as e:
            it.status = "fail"; it.error = str(e)[:300]
        sdb.commit()
    finally:
        sdb.close()
