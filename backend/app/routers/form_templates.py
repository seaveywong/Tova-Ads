"""Instant Form 模板 + Messenger 消息模板路由。

表单模板：存完整配置 JSON → 部署时 build_lead_form_payload → 建到 FB → 存 fb_form_id 复用。
消息模板：存 welcome_text + ice_breakers → 部署时 parse_message_template → 传创意。
AI：从素材 AI 文案生成表单问题（DeepSeek 文本模型）。
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
from ..models.lead_form_template import LeadFormTemplate, MessageTemplate
from ..models.launch import Asset

router = APIRouter(prefix="/form-templates", tags=["form-templates"])


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


@router.put("/forms/{fid}")
def update_form(fid: int, body: FormTemplateIn,
                user: CurrentUser = Depends(require_permission("ads.create")),
                db: Session = Depends(get_db)):
    t = db.query(LeadFormTemplate).filter(
        LeadFormTemplate.id == fid, LeadFormTemplate.tenant_id == user.tenant_id).first()
    if not t: raise HTTPException(404, "表单模板不存在")
    t.name = body.name; t.description = body.description; t.locale = body.locale
    t.config_json = json.dumps(body.config, ensure_ascii=False) if body.config else None
    db.commit()
    return _form_dict(t)


@router.delete("/forms/{fid}")
def delete_form(fid: int, user: CurrentUser = Depends(require_permission("ads.create")),
                db: Session = Depends(get_db)):
    t = db.query(LeadFormTemplate).filter(
        LeadFormTemplate.id == fid, LeadFormTemplate.tenant_id == user.tenant_id).first()
    if not t: raise HTTPException(404, "表单模板不存在")
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
    # 已部署到同 page → 复用
    if t.fb_form_id and t.fb_page_id == page_id:
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


# ── AI 生成表单 ──
class AiGenerateFormIn(BaseModel):
    asset_id: int
    country: str = ""
    product_desc: str = ""


@router.post("/forms/ai-generate")
def ai_generate_form(body: AiGenerateFormIn,
                     user: CurrentUser = Depends(require_permission("ads.create")),
                     db: Session = Depends(get_db)):
    """AI 从素材文案生成 Instant Form 问题 + 感谢页文案（DeepSeek 文本模型）。"""
    ai = AiClient()
    if not ai.is_configured():
        raise HTTPException(400, "AI 未配置（缺 ai_api_key）")
    asset = db.query(Asset).filter(Asset.id == body.asset_id).first()
    if not asset: raise HTTPException(404, "素材不存在")
    copy = {}
    if asset.ai_copy_json:
        try: copy = json.loads(asset.ai_copy_json)
        except: copy = {}
    headlines = copy.get("headlines", [])
    bodies = copy.get("bodies", [])
    lang_note = f"目标投放国家：{body.country or '未指定'}" if body.country else ""
    sys_msg = ("你是 FB Instant Form 设计专家。根据广告素材信息设计潜在客户表单。"
               "严格只返回 JSON，不要解释。")
    prompt = (
        f"广告标题参考：{headlines[:3]}\n广告正文参考：{bodies[:2]}\n"
        f"{lang_note}\n产品描述：{body.product_desc or '（从广告素材推断）'}\n\n"
        "生成 Instant Form 配置 JSON：\n"
        '{"form_title":"表单标题(简洁,吸引提交)","description":"表单说明(1句话)",'
        '"custom_questions":[{"key":"question_1","label":"问题文本","placeholder":"输入提示"},'
        '{"key":"question_2","label":"选择题","options":[{"key":"a","value":"选项A"},{"key":"b","value":"选项B"}]}],'
        '"extra_contact_fields":["EMAIL"],"thank_you_title":"感谢页标题","thank_you_body":"感谢页正文"}\n'
        "生成 2-4 个有意义的自定义问题（结合产品/服务），不要只问姓名。"
    )
    try:
        data = ai.chat_json(
            [{"role": "system", "content": sys_msg}, {"role": "user", "content": prompt}],
            temperature=0.7, max_tokens=800,
        )
    except AiError as e:
        raise HTTPException(400, f"AI 生成失败：{e.message}")
    return {"config": data}
