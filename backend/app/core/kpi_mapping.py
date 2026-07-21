"""KPI 映射配置（系统级，超管可编辑）——参照 1.0 的完整映射表。

存 system_settings['kpi_mapping']（JSON），kpi_resolver 读取时先查 DB 再 fallback 默认。
1.0 用 5 张 DB 表；2.0 用 system_settings JSON（更简洁，功能等价）。
"""
import json
from sqlalchemy.orm import Session
from ..models.system import SystemSetting

# ── 默认映射（照搬 1.0 _OBJECTIVE_RULES + _OPTGOAL_RULES，比 2.0 原来的更全）──

DEFAULT_MATRIX = {
    # objective × optimization_goal → kpi_field
    ("OUTCOME_SALES", "OFFSITE_CONVERSIONS"): "offsite_conversion.fb_pixel_purchase",
    ("OUTCOME_SALES", "VALUE"): "offsite_conversion.fb_pixel_purchase",
    ("OUTCOME_LEADS", "LEAD_GENERATION"): "onsite_conversion.lead_grouped",
    ("OUTCOME_LEADS", "OFFSITE_CONVERSIONS"): "offsite_conversion.fb_pixel_lead",
    ("OUTCOME_LEADS", "MESSAGES"): "onsite_conversion.messaging_conversation_started_7d",
    ("OUTCOME_LEADS", "APP_INSTALLS"): "app_install",
    ("OUTCOME_ENGAGEMENT", "PAGE_LIKES"): "like",
    ("OUTCOME_ENGAGEMENT", "POST_ENGAGEMENT"): "post_engagement",
    ("OUTCOME_ENGAGEMENT", "CONVERSATIONS"): "onsite_conversion.messaging_conversation_started_7d",
    ("OUTCOME_TRAFFIC", "LINK_CLICKS"): "link_click",
    ("OUTCOME_TRAFFIC", "LANDING_PAGE_VIEWS"): "landing_page_view",
    ("OUTCOME_VIDEO_VIEWS", "VIDEO_VIEWS"): "video_view",
    ("OUTCOME_VIDEO_VIEWS", "THRUPLAY"): "thruplay",
    ("OUTCOME_APP_PROMOTION", "APP_INSTALLS"): "app_install",
}

DEFAULT_BY_OBJECTIVE = {
    "OUTCOME_SALES": "offsite_conversion.fb_pixel_purchase",
    "OUTCOME_LEADS": "onsite_conversion.lead_grouped",
    "OUTCOME_ENGAGEMENT": "post_engagement",
    "OUTCOME_TRAFFIC": "link_click",
    "OUTCOME_VIDEO_VIEWS": "video_view",
    "OUTCOME_APP_PROMOTION": "app_install",
    "OUTCOME_LEAD_GENERATION": "offsite_conversion.fb_pixel_lead",
}

DEFAULT_FALLBACK_PRIORITY = [
    "offsite_conversion.fb_pixel_purchase", "purchase", "omni_purchase",
    "onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead", "lead",
    "onsite_conversion.messaging_conversation_started_7d",
    "complete_registration", "app_install",
    "like", "post_engagement", "link_click", "video_view",
]

DEFAULT_POOR_FALLBACK_TYPES = [
    "omni_view_content", "omni_landing_page_view", "onsite_web_view_content",
    "onsite_web_app_view_content", "view_content", "landing_page_view",
    "link_click", "page_engagement", "post_engagement",
    "offsite_content_view_add_meta_leads",
    "onsite_conversion.post_net_like", "onsite_conversion.post_net_comment",
    "onsite_conversion.post_net_save", "onsite_conversion.post_save",
    "post_reaction", "post_interaction_gross", "post_interaction_net",
]

DEFAULT_FIELD_LABELS = {
    "offsite_conversion.fb_pixel_purchase": "购买", "purchase": "购买", "omni_purchase": "购买",
    "offsite_conversion.fb_pixel_lead": "线索", "onsite_conversion.lead_grouped": "线索", "lead": "线索",
    "onsite_conversion.messaging_conversation_started_7d": "私信会话",
    "app_install": "应用安装", "complete_registration": "注册完成",
    "like": "主页赞", "post_engagement": "帖子互动", "link_click": "链接点击",
    "landing_page_view": "落地页浏览", "video_view": "视频观看", "thruplay": "ThruPlay",
    "offsite_conversion.fb_pixel_add_to_cart": "加入购物车",
    "offsite_conversion.fb_pixel_initiate_checkout": "发起结账",
}

# KPI 字段分类（看板筛选 + 诊断展示用）
KPI_CATEGORIES = {
    "转化": ["offsite_conversion.fb_pixel_purchase", "purchase", "omni_purchase",
             "offsite_conversion.fb_pixel_add_to_cart", "offsite_conversion.fb_pixel_initiate_checkout",
             "offsite_conversion.fb_pixel_complete_registration", "offsite_conversion.fb_pixel_subscribe",
             "offsite_conversion.fb_pixel_contact", "contact"],
    "线索": ["onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead", "lead"],
    "私信": ["onsite_conversion.messaging_conversation_started_7d", "onsite_conversion.messaging_first_reply"],
    "App": ["app_install"],
    "流量": ["link_click", "landing_page_view"],
    "互动": ["like", "post_engagement", "page_engagement", "video_view", "thruplay"],
}


def get_kpi_mapping(db: Session) -> dict:
    """读 KPI 映射配置（DB 优先 → 默认）。"""
    row = db.query(SystemSetting).filter(SystemSetting.key == "kpi_mapping").first()
    if row and row.value:
        try:
            cfg = json.loads(row.value)
            return _merge_defaults(cfg)
        except Exception:
            pass
    return _default_mapping()


def save_kpi_mapping(db: Session, cfg: dict):
    """保存 KPI 映射配置到 system_settings。"""
    val = json.dumps(cfg)
    row = db.query(SystemSetting).filter(SystemSetting.key == "kpi_mapping").first()
    if row:
        row.value = val
    else:
        db.add(SystemSetting(key="kpi_mapping", value=val))
    db.commit()


def _default_mapping() -> dict:
    return {
        "matrix": {f"{k[0]}|{k[1]}": v for k, v in DEFAULT_MATRIX.items()},
        "by_objective": dict(DEFAULT_BY_OBJECTIVE),
        "fallback_priority": list(DEFAULT_FALLBACK_PRIORITY),
        "poor_fallback_types": list(DEFAULT_POOR_FALLBACK_TYPES),
        "field_labels": dict(DEFAULT_FIELD_LABELS),
    }


def _merge_defaults(cfg: dict) -> dict:
    """DB 配置 merge 默认（DB 优先，缺的补默认）。"""
    d = _default_mapping()
    return {
        "matrix": {**d["matrix"], **(cfg.get("matrix") or {})},
        "by_objective": {**d["by_objective"], **(cfg.get("by_objective") or {})},
        "fallback_priority": cfg.get("fallback_priority") or d["fallback_priority"],
        "poor_fallback_types": cfg.get("poor_fallback_types") or d["poor_fallback_types"],
        "field_labels": {**d["field_labels"], **(cfg.get("field_labels") or {})},
    }


def field_label(field: str, mapping: dict = None) -> str:
    """字段 → 中文标签（mapping 未传时用默认）。"""
    labels = (mapping or _default_mapping()).get("field_labels", DEFAULT_FIELD_LABELS)
    return labels.get(field, field or "-")


def is_poor_fallback(field: str, mapping: dict = None) -> bool:
    """字段是否在劣质兜底黑名单中。"""
    poor = set((mapping or _default_mapping()).get("poor_fallback_types", DEFAULT_POOR_FALLBACK_TYPES))
    return field in poor
