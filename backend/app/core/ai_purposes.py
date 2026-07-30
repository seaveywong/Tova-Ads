"""素材 AI 分析：通用第一人称生成 prompt + 自由文本「投放目的」+ 深度/风格轴。

用途由用户以一段自由文本「投放目的」描述（替换旧的 13 个预设用途）。
深度轴 fast/standard/deep 控制生成条数 + 视频抽帧数 + max_tokens。
风格轴 conservative/standard/aggressive 控制合规松紧（aggressive 放宽，允许具体数字/钩子）。

数据为 SSOT，供 assets.py analyze 端点 + 前端 GET /assets/ai-options 共用。
"""
from __future__ import annotations

# 语言代码 → 展示名
AI_LANGUAGE_NAMES: dict[str, str] = {
    "en": "English", "es": "Spanish (Español)", "pt": "Portuguese (Português)",
    "fr": "French (Français)", "ar": "Arabic (العربية)", "zh": "Simplified Chinese (简体中文)",
    "zh-tw": "Traditional Chinese (繁體中文)", "ja": "Japanese (日本語)", "ko": "Korean (한국어)",
    "de": "German (Deutsch)", "it": "Italian (Italiano)", "ru": "Russian (Русский)",
    "hi": "Hindi (हिन्दी)", "id": "Indonesian (Bahasa Indonesia)", "th": "Thai (ภาษาไทย)",
    "vi": "Vietnamese (Tiếng Việt)", "tr": "Turkish (Türkçe)", "ms": "Malay (Bahasa Melayu)",
    "nl": "Dutch (Nederlands)", "pl": "Polish (Polski)",
}

# 国家 → 默认语言代码
COUNTRY_LANGUAGE_MAP: dict[str, str] = {
    "US": "en", "GB": "en", "CA": "en", "AU": "en", "NZ": "en", "IE": "en", "IN": "en", "PH": "en", "MY": "en",
    "ES": "es", "MX": "es", "AR": "es", "CO": "es", "PE": "es", "CL": "es", "VE": "es",
    "BR": "pt", "PT": "pt",
    "FR": "fr", "BE": "fr",
    "DE": "de", "AT": "de",
    "AE": "ar", "SA": "ar", "EG": "ar", "KW": "ar", "QA": "ar",
    "JP": "ja", "KR": "ko",
    "ID": "id",
    "TH": "th", "VN": "vi", "TR": "tr",
    "CN": "zh", "SG": "zh", "TW": "zh-tw", "HK": "zh-tw",
}

# ── 精度档位（max_tokens 已上调：gemini-2.5-flash 是 thinking 模型，aggressive 风格 + 推理会消耗更多，否则截断 JSON）──
ANALYSIS_DEPTH_CONFIG: dict[str, dict] = {
    "fast":     {"label": "快速", "temperature": 0.7, "video_frames": 1, "max_tokens": 3072, "copy_count": 3},
    "standard": {"label": "标准", "temperature": 0.85, "video_frames": 4, "max_tokens": 4096, "copy_count": 3},
    "deep":     {"label": "深度", "temperature": 0.9, "video_frames": 6, "max_tokens": 5120, "copy_count": 5},
}

# ── 风格轴 ──
STYLE_GUIDES: dict[str, str] = {
    "conservative": (
        "【文案风格：保守】"
        "语气温和、安全、不夸大。多用「了解更多」「分享」「体验」等柔和表述，"
        "避免任何可能引起审核的词语，适合对合规要求极高的广告主。"
    ),
    "standard": (
        "【文案风格：标准】"
        "语气自然、有感染力，在合规范围内尽量吸引眼球。"
        "可用适度的情感化表达和行动召唤，平衡吸引力与合规性。"
    ),
    "aggressive": (
        "【文案风格：激进——请写出真正有冲击力的广告文案】\n"
        "目标：让用户看到第一句就停下来、产生强烈好奇心和行动冲动。\n\n"
        "具体写法要求：\n"
        "1. 标题必须具有冲击力，可用以下技巧：\n"
        "   - 具体数字/事实：如 'This $0.38 Stock Could Be the Next $1,000,000 Opportunity'\n"
        "   - 惊叹/不敢相信：如 'I Can't Believe This Is Still Under $1...'\n"
        "   - 悬念引导：如 'What I Found in This Chart Shocked Me'\n"
        "   - 紧迫感：如 'This Window Is Closing Fast — Are You In?'\n"
        "   - 内幕感：如 'My Secret Strategy That Wall Street Doesn't Want You to Know'\n\n"
        "2. 文案必须具体、有画面感，不要模糊语言：\n"
        "   - 具体化：写出真实场景和数字，不要用「显著收益」这种模糊词\n"
        "   - 情感化：用第一人称分享真实心理状态，如 'I've been watching this for weeks and I can't sleep'\n"
        "   - 强烈 CTA：结尾用行动指令，如 'Join my free group now — link in bio'\n\n"
        "禁止事项（仅限以下几条，不要过度限制）：\n"
        "- 不要写 'guaranteed returns' 或 'risk-free'（但可以写具体数字和场景）\n"
        "- 不要直接说 'cure/treat disease'（但可以写体验和感受）\n"
        "- 不要用 'you are fat/sick/poor' 直接攻击用户（但可以用第一人称分享）"
    ),
}

# 全局合规指引（aggressive 时不附加）
COMPLIANCE_GUIDE = """【Facebook 广告合规指引】
请用真实、自然的语气写文案，避免以下表述：
- 绝对化承诺（guaranteed / 100% / 一定能）→ 改用「有机会」「帮助」「可能」
- 夸大收益（get rich / 月入过万）→ 改用「值得关注」「我在研究」
- 医疗声称（cure / treat）→ 改用「感觉」「体验」「我的变化」
- 直接指向用户问题（你的财务/体重/疾病）→ 改用第一人称分享视角"""

# 通用生成指令（替换旧的 13 用途专属 prompt）：第一人称视角 + 画面自判 + 合规底线。
_GENERAL_GEN_INSTRUCTION = (
    "你是一位资深 Facebook 广告投放专家。请分析这张广告素材，根据画面内容自动判断最佳广告策略。"
    "以图片/视频中人物的第一视角（用「我」「我的」等第一人称）生成广告标题和文案，"
    "让受众感受到是画面中的人在直接与他们说话；若画面无人物（纯产品/图表/风景），则以推荐者视角直接向受众说话。"
)


def resolve_language_code(language: str, country: str) -> str:
    """language 非空 → 归一（zh-cn/cn→zh, zh-tw 保留）；空 → country 推导；都空 → en。"""
    lang = (language or "").strip().lower().replace("_", "-")
    if lang in ("zh-cn", "cn", "zh-hans"):
        return "zh"
    if lang in ("zh-tw", "tw", "hk", "zh-hant"):
        return "zh-tw"
    if lang:
        return lang
    if country:
        return COUNTRY_LANGUAGE_MAP.get(country.upper(), "en")
    return "en"


def build_analysis_prompt(*, depth: str, style: str,
                          language: str, country: str, video_frame_count: int,
                          purpose: str = "") -> tuple[str, str]:
    """组装完整分析 prompt（不含图片，图片由调用方以 image_url 形式附上）。

    purpose：用户自由文本「投放目的」（可选）。空 → 模型按画面自判。
    返回 (prompt, lang_code)。
    """
    depth_cfg = ANALYSIS_DEPTH_CONFIG.get(depth, ANALYSIS_DEPTH_CONFIG["standard"])
    copy_count = depth_cfg["copy_count"]
    purpose_hint = (
        f"\n【投放目的】请重点围绕以下目的生成文案与受众：{purpose.strip()}"
        if purpose and purpose.strip() else ""
    )
    style_guide = STYLE_GUIDES.get(style, STYLE_GUIDES["standard"])
    compliance_guide = "" if style == "aggressive" else COMPLIANCE_GUIDE
    lang_code = resolve_language_code(language, country)
    lang_name = AI_LANGUAGE_NAMES.get(lang_code, "English")
    lang_instruction = (f"输出语言：所有内容（analysis / headlines / bodies / audience_note）"
                        f"必须统一用 {lang_name} 输出，不得混用其他语言。")
    video_hint = (
        f"\n【注意】以下 {video_frame_count} 张图片是同一段视频按时间顺序均匀截取的帧，"
        "请综合理解视频的完整内容、故事线和广告意图后生成文案，不要只描述单帧画面。"
        if video_frame_count > 1 else ""
    )
    analysis_len = "50字以内" if depth == "fast" else "100字以内"
    return f"""{_GENERAL_GEN_INSTRUCTION}{purpose_hint}{video_hint}

{style_guide}

{lang_instruction}

请用 JSON 格式返回：
{{
  "analysis": "描述画面/视频内容和广告意图（使用主语言，{analysis_len}）",
  "headlines": ["标题1", ...（共{copy_count}条）],
  "bodies": ["文案1（含 CTA）", ...（共{copy_count}条）],
  "interests": ["英文兴趣词1", "英文兴趣词2", "英文兴趣词3", "英文兴趣词4", "英文兴趣词5"],
  "audience_note": "目标受众特征简述（使用主语言）"
}}

要求：
1. 如果图片中有清晰的人物，请以该人物的第一视角（「我」「我的」等第一人称）书写标题和文案；如果图片中没有人物（如纯数字、图表、产品图、风景图），请以旁白/推荐者视角书写，直接向受众说话（如「你」「你的」），或用吸引眼球的陈述句开头。
2. 标题不超过 40 字，文案不超过 125 字，语气自然有感染力。
3. 兴趣词必须是 Facebook Ads Manager 受众定向中真实存在的英文词，不要造词。
4. 兴趣词要与投放目的高度匹配。
{compliance_guide}
6. 只返回 JSON，不要其他内容""", lang_code
