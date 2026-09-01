"""Instant Form 模板 + Messenger 消息模板路由。

表单模板：存完整配置 JSON → 部署时 build_lead_form_payload → 建到 FB → 存 fb_form_id 复用。
消息模板：存 welcome_text + ice_breakers → 部署时 parse_message_template → 传创意。
AI：从素材 AI 文案（headlines/bodies/受众）生成表单问题与 Messenger 消息（文本模型）。
"""
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from ..core.database import get_db
from ..core.deps import CurrentUser, require_permission
from ..core.log_utils import write_log, new_trace_id
from ..core.fb_tokens import first_client
from ..core.fb_client import FbApiError
from ..core.ad_builder import build_lead_form_payload, lead_form_safe_payload, _CONTACT_FIELD_TYPES, default_contact_field
from ..core.ai_client import AiClient, AiError
from ..core.ai_purposes import AI_LANGUAGE_NAMES
from ..models.lead_form_template import LeadFormTemplate, MessageTemplate
from ..models.launch import Asset

router = APIRouter(prefix="/form-templates", tags=["form-templates"])

# AI 生成租户级配额（进程内存滑窗，多 worker 各自计数=更严可接受）——防刷爆共享 key
_AI_QUOTA: dict = {}


def _ai_quota_ok(db, tenant_id: int, kind: str, limit: int = 20, window_sec: int = 3600) -> bool:
    import time as _t
    now = _t.time()
    key = f"{tenant_id}:{kind}"
    hits = [ts for ts in _AI_QUOTA.get(key, []) if now - ts < window_sec]
    if len(hits) >= limit:
        return False
    hits.append(now)
    _AI_QUOTA[key] = hits[-limit:]
    if len(_AI_QUOTA) > 5000:
        _AI_QUOTA.clear()
    return True



def _form_dict(t: LeadFormTemplate) -> dict:
    cfg = {}
    if t.config_json:
        try: cfg = json.loads(t.config_json)
        except: cfg = {}
    return {
        "id": t.id, "name": t.name, "description": t.description or "",
        "config": cfg, "fb_form_id": t.fb_form_id or "", "fb_page_id": t.fb_page_id or "",
        "locale": t.locale or "en_US", "status": t.status,
        "created_at": str(t.created_at) if t.created_at else "",
    }


def _msg_dict(t: MessageTemplate) -> dict:
    ib = []
    if t.ice_breakers_json:
        try: ib = json.loads(t.ice_breakers_json)
        except: ib = []
    return {
        "id": t.id, "name": t.name,
        "welcome_text": t.welcome_text or "", "ice_breakers": ib,
        "status": t.status, "created_at": str(t.created_at) if t.created_at else "",
    }


# ── Instant Form CRUD ──
class FormTemplateIn(BaseModel):
    name: str
    description: str = ""
    config: dict = {}       # 完整表单配置（form_title/privacy_url/locale/custom_questions/...）
    locale: str = "en_US"


@router.get("/forms")
def list_forms(user: CurrentUser = Depends(require_permission("ads.create")),
               db: Session = Depends(get_db)):
    rows = db.query(LeadFormTemplate).filter(
        LeadFormTemplate.tenant_id == user.tenant_id, LeadFormTemplate.status != "archived"
    ).order_by(LeadFormTemplate.id.desc()).all()
    return [_form_dict(t) for t in rows]


@router.post("/forms")
def save_form(body: FormTemplateIn,
              user: CurrentUser = Depends(require_permission("ads.create")),
              db: Session = Depends(get_db)):
    t = LeadFormTemplate(
        tenant_id=user.tenant_id, created_by=user.id,
        name=body.name, description=body.description,
        config_json=json.dumps(body.config, ensure_ascii=False) if body.config else None,
        locale=body.locale or "en_US", status="active",
    )
    db.add(t); db.flush()
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, target_type="form_template", target_id=str(t.id),
              action_type="create", source="user", result="success")
    db.commit()
    return _form_dict(t)


def _config_hash(config_json: str | None) -> str:
    """config 规范化哈希（key 排序，语义等价 config 同 hash）。"""
    import hashlib
    if not config_json:
        return ""
    try:
        return hashlib.sha256(json.dumps(json.loads(config_json), sort_keys=True,
                                         ensure_ascii=False).encode()).hexdigest()[:16]
    except Exception:
        return hashlib.sha256(config_json.encode()).hexdigest()[:16]


@router.put("/forms/{fid}")
def update_form(fid: int, body: FormTemplateIn,
                user: CurrentUser = Depends(require_permission("ads.create")),
                db: Session = Depends(get_db)):
    t = db.query(LeadFormTemplate).filter(
        LeadFormTemplate.id == fid, LeadFormTemplate.tenant_id == user.tenant_id).first()
    if not t: raise HTTPException(404, "表单模板不存在")
    t.name = body.name; t.description = body.description; t.locale = body.locale
    new_cfg = json.dumps(body.config, ensure_ascii=False) if body.config else None
    if _config_hash(new_cfg) != (t.config_hash or ""):
        t.fb_form_id = None  # config 变了 → 旧 FB 表单失效，下次部署强制重建
    t.config_json = new_cfg
    db.commit()
    return _form_dict(t)


@router.delete("/forms/{fid}")
def delete_form(fid: int, user: CurrentUser = Depends(require_permission("ads.create")),
                db: Session = Depends(get_db)):
    t = db.query(LeadFormTemplate).filter(
        LeadFormTemplate.id == fid, LeadFormTemplate.tenant_id == user.tenant_id).first()
    if not t: raise HTTPException(404, "表单模板不存在")
    # 归档后部署 runner 仍会按 id 继续用它建 FB 表单——被引用时明确告知而不是静默归档
    from ..models.launch_template import LaunchTemplate
    _ref = db.query(LaunchTemplate.id).filter(
        LaunchTemplate.tenant_id == user.tenant_id,
        LaunchTemplate.lead_form_template_id == fid,
        LaunchTemplate.status != "archived",
    ).count()
    if _ref:
        raise HTTPException(400, f"该表单仍被 {_ref} 个投放模板引用，请先在模板中移除引用再归档")
    t.status = "archived"; db.commit()
    return {"id": fid, "archived": True}


@router.post("/forms/{fid}/deploy")
def deploy_form(fid: int, body: dict,
                user: CurrentUser = Depends(require_permission("ads.create")),
                db: Session = Depends(get_db)):
    """建表单到 FB（page_id 必传）→ 存 fb_form_id。已建的直接返回。"""
    t = db.query(LeadFormTemplate).filter(
        LeadFormTemplate.id == fid, LeadFormTemplate.tenant_id == user.tenant_id).first()
    if not t: raise HTTPException(404, "表单模板不存在")
    page_id = body.get("page_id", "")
    if not page_id: raise HTTPException(400, "page_id 必填")
    # 已部署到同 page 且 config 未变 → 复用（config 变了必须重建，否则用户改了问题拿到的还是旧表单）
    if t.fb_form_id and t.fb_page_id == page_id and t.config_hash == _config_hash(t.config_json):
        return {"form_id": t.fb_form_id, "reused": True}
    cfg = {}
    if t.config_json:
        try: cfg = json.loads(t.config_json)
        except: cfg = {}
    fb = first_client(db, user.tenant_id)
    if not fb: raise HTTPException(400, "未绑定 FB 凭证")
    payload = build_lead_form_payload(
        form_title=cfg.get("form_title", t.name),
        privacy_url=cfg.get("privacy_url", ""),
        locale=cfg.get("locale", t.locale or "en_US"),
        target_countries=cfg.get("target_countries", []),
        description=cfg.get("description", ""),
        custom_questions=cfg.get("custom_questions", []),
        extra_contact_fields=cfg.get("extra_contact_fields", []),
        privacy_link_text=cfg.get("privacy_link_text", "Privacy Policy"),
        thank_you_title=cfg.get("thank_you_title", ""),
        thank_you_body=cfg.get("thank_you_body", ""),
        thank_you_button_text=cfg.get("thank_you_button_text", ""),
        thank_you_website_url=cfg.get("thank_you_website_url", ""),
        follow_up_url=cfg.get("follow_up_url", ""),
        context_card_title=cfg.get("context_card_title", ""),
        name_prefix="Tova",
        is_optimized_for_quality=bool(cfg.get("is_optimized_for_quality", False)),
        welcome_message=cfg.get("welcome_message", ""),
        only_visible_to_target_countries=bool(cfg.get("only_visible_to_target_countries", False)),
    )
    try:
        result = fb.post(f"{page_id}/leadgen_forms", payload)
        form_id = result.get("id")
        if not form_id:
            raise HTTPException(400, f"FB 未返回 form_id：{str(result)[:200]}")
    except FbApiError as e:
        # 368/1346003 风控 → 重试安全版
        code = (e.raw or {}).get("code", 0)
        if code in (368, 1346003):
            try:
                safe = lead_form_safe_payload(payload)
                result = fb.post(f"{page_id}/leadgen_forms", safe)
                form_id = result.get("id")
                if not form_id: raise HTTPException(400, f"安全版仍失败：{str(result)[:200]}")
            except HTTPException: raise
            except Exception as e2:
                raise HTTPException(400, f"表单创建失败（安全版重试也失败）：{e.friendly}")
        else:
            raise HTTPException(400, f"表单创建失败：{e.friendly}")
    t.fb_form_id = form_id; t.fb_page_id = page_id
    t.config_hash = _config_hash(t.config_json)  # 记部署时的 config 基线，后续变更触发重建
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, target_type="leadgen_form", target_id=form_id,
              action_type="create", source="fb_api", result="success",
              metadata={"page_id": page_id, "template_id": fid})
    db.commit()
    return {"form_id": form_id, "reused": False}


# ── Messenger 消息 CRUD ──
class MsgTemplateIn(BaseModel):
    name: str
    welcome_text: str = ""
    ice_breakers: list = []  # [{title, response}, ...]


@router.get("/messages")
def list_messages(user: CurrentUser = Depends(require_permission("ads.create")),
                  db: Session = Depends(get_db)):
    rows = db.query(MessageTemplate).filter(
        MessageTemplate.tenant_id == user.tenant_id, MessageTemplate.status != "archived"
    ).order_by(MessageTemplate.id.desc()).all()
    return [_msg_dict(t) for t in rows]


@router.post("/messages")
def save_message(body: MsgTemplateIn,
                 user: CurrentUser = Depends(require_permission("ads.create")),
                 db: Session = Depends(get_db)):
    t = MessageTemplate(
        tenant_id=user.tenant_id, created_by=user.id,
        name=body.name, welcome_text=body.welcome_text,
        ice_breakers_json=json.dumps(body.ice_breakers, ensure_ascii=False) if body.ice_breakers else None,
        status="active",
    )
    db.add(t); db.flush()
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, target_type="message_template", target_id=str(t.id),
              action_type="create", source="user", result="success")
    db.commit()
    return _msg_dict(t)


@router.put("/messages/{mid}")
def update_message(mid: int, body: MsgTemplateIn,
                   user: CurrentUser = Depends(require_permission("ads.create")),
                   db: Session = Depends(get_db)):
    t = db.query(MessageTemplate).filter(
        MessageTemplate.id == mid, MessageTemplate.tenant_id == user.tenant_id).first()
    if not t: raise HTTPException(404, "消息模板不存在")
    t.name = body.name; t.welcome_text = body.welcome_text
    t.ice_breakers_json = json.dumps(body.ice_breakers, ensure_ascii=False) if body.ice_breakers else None
    db.commit()
    return _msg_dict(t)


@router.delete("/messages/{mid}")
def delete_message(mid: int, user: CurrentUser = Depends(require_permission("ads.create")),
                   db: Session = Depends(get_db)):
    t = db.query(MessageTemplate).filter(
        MessageTemplate.id == mid, MessageTemplate.tenant_id == user.tenant_id).first()
    if not t: raise HTTPException(404, "消息模板不存在")
    t.status = "archived"; db.commit()
    return {"id": mid, "archived": True}


# locale → 展示语言名（表单/消息 AI 生成的输出语言）
_LOCALE_LANG = {
    "en_US": "English", "en_GB": "English (UK)", "zh_TW": "繁體中文", "zh_CN": "简体中文",
    "vi_VN": "Tiếng Việt", "th_TH": "ภาษาไทย", "id_ID": "Bahasa Indonesia",
    "ja_JP": "日本語", "ko_KR": "한국어", "es_ES": "Español", "pt_BR": "Português",
}


# ── AI 生成表单 ──
class AiGenerateFormIn(BaseModel):
    asset_id: int
    country: str = ""
    product_desc: str = ""
    locale: str = "en_US"  # 表单语言（en_US=英文, zh_TW=繁中, vi_VN=越南...）
    purpose: str = ""      # 自由文本「投放目的」（可选，定向生成）


@router.post("/forms/ai-generate")
def ai_generate_form(body: AiGenerateFormIn,
                     user: CurrentUser = Depends(require_permission("ads.create")),
                     db: Session = Depends(get_db)):
    """AI 从素材文案生成 Instant Form 问题 + 感谢页文案（文本模型）。租户级 20 次/小时配额。"""
    if not _ai_quota_ok(db, user.tenant_id, "form"):
        raise HTTPException(429, "AI 生成太频繁（租户每小时限 20 次），请稍后再试")
    ai = AiClient()
    if not ai.is_configured():
        raise HTTPException(400, "AI 未配置（缺 ai_api_key）")
    asset = db.query(Asset).filter(
        Asset.id == body.asset_id, Asset.tenant_id == user.tenant_id).first()
    if not asset: raise HTTPException(404, "素材不存在")
    copy = {}
    if asset.ai_copy_json:
        try: copy = json.loads(asset.ai_copy_json)
        except: copy = {}
    audience = {}
    if asset.ai_audience_json:
        try: audience = json.loads(asset.ai_audience_json)
        except: audience = {}
    headlines = copy.get("headlines", [])
    bodies = copy.get("bodies", [])
    audience_note = audience.get("audience_note", "")
    interests = audience.get("interests", [])
    lang_note = f"目标投放国家：{body.country or '未指定'}" if body.country else ""
    purpose_note = f"\n投放目的：{body.purpose.strip()}" if body.purpose and body.purpose.strip() else ""
    out_lang = _LOCALE_LANG.get(body.locale, "English")
    sys_msg = ("你是 FB Instant Form 设计专家。根据广告素材信息设计潜在客户表单。"
               "严格只返回 JSON，不要解释。")
    prompt = (
        f"广告标题参考：{headlines[:3]}\n广告正文参考：{bodies[:2]}\n"
        f"目标受众：{audience_note or '（从素材推断）'}\n兴趣词：{interests[:8]}\n"
        f"{lang_note}\n产品描述：{body.product_desc or '（从广告素材推断）'}{purpose_note}\n\n"
        f"**表单所有内容（标题/描述/问题/选项/感谢页）必须用 {out_lang} 输出。**\n\n"
        "生成 Instant Form 配置 JSON：\n"
        '{"form_title":"","description":"","custom_questions":[],'
        '"extra_contact_fields":["EMAIL","PHONE"],"thank_you_title":"","thank_you_body":""}\n'
        "生成 2-4 个通用商业问题（联系方式偏好/预算/紧迫度/需求描述），"
        "问题要贴合该素材的目标受众，不要和具体产品细节绑定。所有文本用指定语言输出。"
    )
    try:
        data = ai.chat_json(
            [{"role": "system", "content": sys_msg}, {"role": "user", "content": prompt}],
            temperature=0.7, max_tokens=4096,
        )
    except AiError as e:
        raise HTTPException(400, f"AI 生成失败：{e.message}")
    return {"config": data}


# ── AI 生成 Messenger 消息 ──
class AiGenerateMsgIn(BaseModel):
    asset_id: int
    product_desc: str = ""
    purpose: str = ""      # 自由文本「投放目的」（可选，定向生成）


@router.post("/messages/ai-generate")
def ai_generate_message(body: AiGenerateMsgIn,
                        user: CurrentUser = Depends(require_permission("ads.create")),
                        db: Session = Depends(get_db)):
    """AI 从素材文案生成 Messenger welcome_text + ice_breakers（文本模型）。

    输出语言跟随素材分析语言（asset.ai_language），让消息贴合该素材的文案语言。
    租户级 20/h 配额（与 form 端点同款，防刷爆共享 key）。
    """
    if not _ai_quota_ok(db, user.tenant_id, "msg"):
        raise HTTPException(429, "AI 生成太频繁（租户每小时限 20 次），请稍后再试")
    ai = AiClient()
    if not ai.is_configured():
        raise HTTPException(400, "AI 未配置（缺 ai_api_key）")
    asset = db.query(Asset).filter(Asset.id == body.asset_id).first()
    if not asset: raise HTTPException(404, "素材不存在")
    copy = {}
    if asset.ai_copy_json:
        try: copy = json.loads(asset.ai_copy_json)
        except: copy = {}
    audience = {}
    if asset.ai_audience_json:
        try: audience = json.loads(asset.ai_audience_json)
        except: audience = {}
    headlines = copy.get("headlines", [])
    bodies = copy.get("bodies", [])
    audience_note = audience.get("audience_note", "")
    purpose_note = f"\n投放目的：{body.purpose.strip()}" if body.purpose and body.purpose.strip() else ""
    lang_code = (asset.ai_language or "").strip().lower().replace("_", "-")
    out_lang = AI_LANGUAGE_NAMES.get(lang_code, "English")
    sys_msg = ("你是 FB Messenger 营销话术专家。根据广告素材文案设计 Messenger 欢迎语与快捷提问。"
               "严格只返回 JSON，不要解释。")
    prompt = (
        f"广告标题参考：{headlines[:3]}\n广告正文参考：{bodies[:2]}\n"
        f"目标受众：{audience_note or '（从素材推断）'}\n产品描述：{body.product_desc or '（从素材推断）'}{purpose_note}\n\n"
        f"**所有文案必须用 {out_lang} 输出，语气与广告素材保持一致。**\n\n"
        "生成 Messenger 配置 JSON：\n"
        '{"welcome_text":"（1 段第一人称开场白，亲切简短，承接广告承诺并引导用户继续对话）",'
        '"ice_breakers":[{"title":"（≤20 字的快捷按钮）","response":"（点该按钮后机器人的回复，≤80 字）"}, ...共 3-4 条]}\n'
        "ice_breakers 的 title 覆盖用户最可能的几个意图（如：了解更多 / 怎么参加 / 价格 / 联系方式），"
        "response 要具体、贴合素材主题，不要空泛。"
    )
    try:
        data = ai.chat_json(
            [{"role": "system", "content": sys_msg}, {"role": "user", "content": prompt}],
            temperature=0.8, max_tokens=3072,
        )
    except AiError as e:
        raise HTTPException(400, f"AI 生成失败：{e.message}")
    welcome_text = str(data.get("welcome_text", "")).strip()
    ice_breakers = []
    raw_ibs = data.get("ice_breakers", [])
    if isinstance(raw_ibs, list):
        for ib in raw_ibs:
            if isinstance(ib, dict):
                title = str(ib.get("title", "")).strip()
                response = str(ib.get("response", "")).strip()
                if title and response:
                    ice_breakers.append({"title": title[:40], "response": response[:300]})
    return {"welcome_text": welcome_text, "ice_breakers": ice_breakers}
