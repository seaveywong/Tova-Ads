"""AI 路由：配置探测 + 连通测试 + 文案生成（doc 02 §2 AI 兜底，审计项目15/36）。

全局配置走 settings（ai_base_url/ai_api_key/ai_model）——无损切换厂商。
v1 先做 general 文案（标题+正文）；13 种 purpose 完整集 v2。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ..core.config import settings
from ..core.deps import CurrentUser, require_permission
from ..core.ai_client import AiClient, AiError

router = APIRouter(prefix="/ai", tags=["ai"])

# 地区 → 语言（ISO 639-1）。上传指定 country 时自动推导文案语言（命中目标投放地区）。
# 与 1.0 一致：支持切换语言；country 优先推导，language 可显式覆盖。
REGION_LANG: dict[str, str] = {
    "TW": "zh-TW", "HK": "zh-TW", "MO": "zh-TW",
    "CN": "zh-CN", "SG": "zh-CN",
    "US": "en", "GB": "en", "AU": "en", "CA": "en", "PH": "en", "MY": "en", "IN": "en",
    "VN": "vi", "TH": "th", "ID": "id", "JP": "ja", "KR": "ko",
    "ES": "es", "MX": "es", "BR": "pt", "DE": "de", "FR": "fr", "RU": "ru", "AE": "ar", "SA": "ar",
}
# 语言→locale（FB Lead Form locale 用，见 02_附录_表单字段）
LANG_TO_LOCALE: dict[str, str] = {
    "zh-TW": "zh_TW", "zh-CN": "zh_CN", "zh": "zh_CN",
    "en": "en_US", "vi": "vi_VN", "th": "th_TH", "id": "id_ID",
    "ja": "ja_JP", "ko": "ko_KR", "ms": "ms_MY",
    "es": "es_ES", "pt": "pt_BR", "de": "de_DE", "fr": "fr_FR", "ru": "ru_RU", "ar": "ar_AR",
}


def resolve_language(language: str, country: str) -> tuple[str, str]:
    """返回 (language, locale)。language 空时按 country 推导。显式 language 优先。
    兼容用户传 "zh"/"en"/"zh-TW"/"zh_CN" 等变体。"""
    lang = (language or "").strip()
    if not lang and country:
        lang = REGION_LANG.get(country.upper(), "en")
    if not lang:
        lang = "en"
    # 归一 locale
    locale = LANG_TO_LOCALE.get(lang) or LANG_TO_LOCALE.get(lang.lower()) or "en_US"
    # 中文变体归一
    if lang.lower().startswith("zh"):
        locale = "zh_TW" if ("tw" in lang.lower() or "hk" in lang.lower()) else "zh_CN"
        lang = "zh-TW" if locale == "zh_TW" else "zh-CN"
    return lang, locale


@router.get("/config")
def ai_config(user: CurrentUser = Depends(require_permission("ads.read"))):
    """当前 AI 全局配置（key 打码）。"""
    key = settings.ai_api_key
    masked = (key[:6] + "***" + key[-4:]) if key and len(key) > 12 else ("***" if key else "")
    return {
        "base_url": settings.ai_base_url,
        "model": settings.ai_model,
        "api_key_masked": masked,
        "configured": bool(key),
    }


@router.post("/test")
def ai_test(user: CurrentUser = Depends(require_permission("ads.create"))):
    """连通测试：真调一次 AI，返回模型回复。证明全局配置可用。"""
    ai = AiClient()
    if not ai.is_configured():
        raise HTTPException(400, "AI 未配置（.env 缺 ai_api_key）")
    try:
        reply = ai.chat(
            [{"role": "system", "content": "你是测试助手，只回复 'OK' 两字。"},
             {"role": "user", "content": "ping"}],
            max_tokens=16, temperature=0,
        )
        return {"ok": True, "model": ai.model, "base_url": ai.base_url, "reply": reply.strip()}
    except AiError as e:
        raise HTTPException(400, f"AI 调用失败：{e.message}")


class GenCopyIn(BaseModel):
    product: str = ""            # 产品/服务描述
    audience: str = ""           # 目标人群
    language: str = ""           # 可空：空则按 country 推导；显式优先（与 1.0 一致可切换）
    country: str = ""            # 目标投放国家（TW/US/VN...）——上传时指定，后续可改
    count: int = 3               # 生成几组


@router.post("/copy")
def gen_copy(body: GenCopyIn, user: CurrentUser = Depends(require_permission("ads.create"))):
    """生成广告文案（标题+正文）。自定义优先，AI 兜底——此为兜底入口（审计项目36）。

    语言命中目标投放地区：language 空 → 按 country 推导（REGION_LANG）；显式 language 覆盖。
    与 1.0 一致：支持切换语言；上传指定国家、后续可改（country 是入参，随时重调）。
    返回 {language, locale, headlines, bodies}。
    """
    ai = AiClient()
    if not ai.is_configured():
        raise HTTPException(400, "AI 未配置")
    lang, locale = resolve_language(body.language, body.country)
    lang_note = {"zh-CN": "输出语言：简体中文", "zh-TW": "输出语言：繁體中文"}.get(lang, f"输出语言：{lang}")
    # FB 合规：禁绝对化/医疗承诺
    sys_msg = (f"你是 FB 广告文案专家。{lang_note}。第一人称，吸引点击，符合当地文化习惯。"
               "严禁 guaranteed/100%/cure/disease 等绝对化或医疗承诺词。"
               f"严格只返回 JSON，格式 {{\"headlines\":[...],\"bodies\":[...]}}，各 {body.count} 条。"
               "headline≤40字，body≤120字。不要任何解释或 markdown。")
    country_hint = f"\n目标投放国家：{body.country}" if body.country else ""
    user_msg = f"产品：{body.product}\n目标人群：{body.audience}{country_hint}"
    try:
        data = ai.chat_json(
            [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}],
            max_tokens=800, temperature=0.8,
        )
    except AiError as e:
        raise HTTPException(400, f"AI 生成失败：{e.message}")
    return {"model": ai.model, "language": lang, "locale": locale,
            "headlines": data.get("headlines", []), "bodies": data.get("bodies", [])}
