"""素材 AI 分析：用途驱动 prompt + 深度/风格轴（从 1.0 server_src/api/assets.py 移植）。

13 种广告用途，每种一段专属 prompt（第一人称"我"视角 + 该用途的合规禁词）。
深度轴 fast/standard/deep 控制生成条数 + 视频抽帧数 + max_tokens。
风格轴 conservative/standard/aggressive 控制合规松紧（aggressive 放宽，允许具体数字/钩子）。

数据为 SSOT，供 assets.py analyze 端点 + 前端 GET /assets/ai-purposes 共用。
"""
from __future__ import annotations

# ── 13 用途专属 prompt（逐字移植自 1.0 server_src/api/assets.py:37-120）──
AI_PURPOSE_PROMPTS: dict[str, str] = {
    "general": (
        "你是一位资深 Facebook 广告投放专家。请分析这张广告素材图片，根据画面内容自动判断最佳广告策略。"
        "以图片中人物的第一视角（用「我」「我的」等第一人称）生成广告标题和文案，让受众感受到是图片中的人在直接与他们说话。"
        "【合规要求】文案必须符合 Facebook 广告政策：不使用绝对化承诺（如 guaranteed / 100% / promise），"
        "不直接指向用户个人特征（如「你的财务问题」），语气自然、真实，避免夸大宣传。"
    ),
    "attract_male": (
        "请以图片中人物的第一视角（用「我」「我的」等第一人称）生成广告文案，就像图片中的人在直接向男性受众说话。"
        "目标是吸引男性用户主动发起互动和私信。风格神秘、有趣、带有好奇心驱动，重点引导用户发送私信联系「我」。"
        "例如：「想了解更多关于我的事吗？」「我在等你来找我聊聊…」"
        "【合规要求】避免性暗示或露骨内容，不使用「sexy」「hot」等词，保持暗示性但不违规。"
    ),
    "attract_female": (
        "请以图片中人物的第一视角（用「我」「我的」等第一人称）生成广告文案，就像图片中的人在直接向女性受众说话。"
        "目标是吸引女性用户主动发起互动和私信。风格温暖、真实、有亲和力，重点引导用户发送私信联系「我」。"
        "例如：「我想和你分享我的故事…」「来找我聊聊吧，我们可以成为朋友」"
        "【合规要求】避免性暗示，不直接指向用户外貌或身材，保持真实感和情感连接。"
    ),
    "attract_investors": (
        "请以图片中人物的第一视角（用「我」「我的」等第一人称）生成广告文案，就像图片中的人在直接向投资者分享经验。"
        "目标是吸引股民、投资者和金融用户了解投资机会。风格专业、有说服力，重点引导用户了解更多。"
        "例如：「我一直在关注这个市场机会…」「我找到了一个值得深入研究的标的，想了解吗？」"
        "【合规要求】严禁承诺收益或回报（不用 guaranteed returns / make money / get rich），"
        "不使用具体收益数字作为承诺，改用「有潜力」「值得关注」「我在研究」等表述，"
        "避免「立即暴富」「稳赚不赔」等夸大宣传，保持信息分享而非投资建议的语气。"
    ),
    "promote_clothing": (
        "请以图片中人物的第一视角（用「我」「我的」等第一人称）生成广告文案，就像图片中的人在展示并推荐服饰。"
        "目标是突出时尚感、品质感和穿搭魅力，引导用户了解和购买。"
        "例如：「这是我最近爱穿的一件…」「穿上它让我整个人都不一样了」"
        "【合规要求】不使用「最便宜」「全网最低价」等绝对化表述，避免虚假折扣信息。"
    ),
    "promote_beauty": (
        "请以图片中人物的第一视角（用「我」「我的」等第一人称）生成广告文案，就像图片中的人在分享美妆/护肤心得。"
        "目标是突出使用体验和效果，引导用户了解和购买。"
        "例如：「我用了这个之后感觉皮肤状态好了很多…」「这是我最近的日常护肤步骤」"
        "【合规要求】不使用医疗声称（如 cure / treat / clinically proven），"
        "不承诺具体效果数字（如「7天美白」），改用「感觉」「体验」「我的变化」等主观表述。"
    ),
    "promote_health": (
        "请以图片中人物的第一视角（用「我」「我的」等第一人称）生成广告文案，就像图片中的人在分享健康生活方式。"
        "目标是突出健康生活理念和产品使用体验，引导用户了解和购买。"
        "【合规要求】严禁医疗声称（cure / treat / prevent / diagnose），"
        "不使用「减重 X 公斤」等具体承诺，改用「帮助我保持活力」「我的日常健康习惯」等表述，"
        "不直接指向用户的健康问题（不用「你的疾病」「你的体重问题」）。"
    ),
    "promote_app": (
        "请以图片中人物的第一视角（用「我」「我的」等第一人称）生成广告文案，就像图片中的人在推荐 App。"
        "目标是突出 App 功能价值和使用体验，引导用户下载/注册。"
        "【合规要求】不夸大功能效果，不使用「100% 免费」等绝对化表述，如有内购需如实说明。"
    ),
    "promote_course": (
        "请以图片中人物的第一视角（用「我」「我的」等第一人称）生成广告文案，就像图片中的人在分享学习经历。"
        "目标是突出学习价值和技能提升，引导用户了解和报名。"
        "【合规要求】不承诺具体收入或就业结果（不用「学完月薪过万」），"
        "改用「帮助我提升了…」「我学到了很多实用技能」等真实体验表述。"
    ),
    "promote_finance": (
        "请以图片中人物的第一视角（用「我」「我的」等第一人称）生成广告文案，就像图片中的人在分享理财心得。"
        "目标是突出理财理念和产品价值，引导用户了解产品。"
        "【合规要求】严禁承诺收益（不用 guaranteed / fixed return / risk-free），"
        "不使用具体收益率作为承诺，改用「我在了解这个理财方式」「值得关注的机会」等表述，"
        "所有投资都有风险，文案语气要体现这一点。"
    ),
    "ecommerce": (
        "请以图片中人物的第一视角（用「我」「我的」等第一人称）生成广告文案，就像图片中的人在推荐商品。"
        "目标是突出产品价值和使用体验，引导用户了解和购买。"
        "【合规要求】不使用虚假折扣（如「原价 999，现价 99」但实际从未按原价销售），"
        "不使用「全网最低」等无法核实的绝对化表述，紧迫感要真实。"
    ),
    "lead_gen": (
        "请以图片中人物的第一视角（用「我」「我的」等第一人称）生成广告文案，就像图片中的人在邀请用户了解更多。"
        "目标是突出免费价值和专属福利，引导用户填写表单/注册。"
        "【合规要求】如果是免费内容需真实免费，不隐藏后续收费，"
        "不使用「你已被选中」「限你专属」等虚假个性化表述。"
    ),
    "brand_awareness": (
        "请以图片中人物的第一视角（用「我」「我的」等第一人称）生成广告文案，就像图片中的人在代表品牌说话。"
        "目标是突出品牌价值观和情感共鸣，提升品牌好感度。"
        "【合规要求】不使用「最好的品牌」「行业第一」等无法核实的绝对化表述，"
        "保持真实、有温度的品牌声音。"
    ),
}

# 前端下拉用（value + 中文 label）
AI_PURPOSES: list[dict] = [
    {"value": "general", "label": "通用（根据图片自动判断）"},
    {"value": "attract_male", "label": "吸引男性用户互动/私信"},
    {"value": "attract_female", "label": "吸引女性用户互动/私信"},
    {"value": "attract_investors", "label": "吸引投资者/股民/金融用户"},
    {"value": "promote_clothing", "label": "推广服饰/时尚/穿搭"},
    {"value": "promote_beauty", "label": "推广美妆/护肤/美容"},
    {"value": "promote_health", "label": "推广健康/保健/营养"},
    {"value": "promote_app", "label": "推广 App 下载/注册"},
    {"value": "promote_course", "label": "推广课程/教育/培训"},
    {"value": "promote_finance", "label": "推广金融/理财/投资"},
    {"value": "ecommerce", "label": "电商带货（引导购买）"},
    {"value": "lead_gen", "label": "获取线索（引导留资/注册）"},
    {"value": "brand_awareness", "label": "品牌曝光/认知提升"},
]

# 语言代码 → 展示名（移植自 1.0 AI_LANGUAGE_NAMES）
AI_LANGUAGE_NAMES: dict[str, str] = {
    "en": "English", "es": "Spanish (Español)", "pt": "Portuguese (Português)",
    "fr": "French (Français)", "ar": "Arabic (العربية)", "zh": "Simplified Chinese (简体中文)",
    "zh-tw": "Traditional Chinese (繁體中文)", "ja": "Japanese (日本語)", "ko": "Korean (한국어)",
    "de": "German (Deutsch)", "it": "Italian (Italiano)", "ru": "Russian (Русский)",
    "hi": "Hindi (हिन्दी)", "id": "Indonesian (Bahasa Indonesia)", "th": "Thai (ภาษาไทย)",
    "vi": "Vietnamese (Tiếng Việt)", "tr": "Turkish (Türkçe)", "ms": "Malay (Bahasa Melayu)",
    "nl": "Dutch (Nederlands)", "pl": "Polish (Polski)",
}

# 国家 → 默认语言代码（移植自 1.0 COUNTRY_LANGUAGE_MAP）
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

# ── 精度档位（移植自 1.0 ANALYSIS_DEPTH_CONFIG :1056-1081；max_tokens 已上调——gemini-2.5-flash 是 thinking 模型，原 1.0 的 2048 不够 aggressive 风格 + 推理消耗，会截断 JSON）──
ANALYSIS_DEPTH_CONFIG: dict[str, dict] = {
    "fast":     {"label": "快速", "temperature": 0.7, "video_frames": 1, "max_tokens": 3072, "copy_count": 3},
    "standard": {"label": "标准", "temperature": 0.85, "video_frames": 4, "max_tokens": 4096, "copy_count": 3},
    "deep":     {"label": "深度", "temperature": 0.9, "video_frames": 6, "max_tokens": 5120, "copy_count": 5},
}

# ── 风格轴（移植自 1.0 style_guide :1199-1229）──
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


def resolve_purpose_prompt(purpose: str) -> str:
    """用途 → 专属 prompt 段。custom:xxx 前缀 → 拼自定义目的 prompt；否则查表（默认 general）。"""
    purpose = (purpose or "").strip()
    if purpose.lower().startswith("custom:"):
        custom_desc = purpose[7:].strip()
        return (
            "请以图片中人物的第一视角（用「我」「我的」等第一人称）生成广告文案，"
            "就像图片中的人在直接与受众说话。"
            f"投放目的：{custom_desc}。"
            "禁止使用第三人称描述图片内容。"
            "【合规要求】不使用绝对化承诺（guaranteed / 100% / promise），不直接指向用户个人特征，语气自然真实。"
        )
    return AI_PURPOSE_PROMPTS.get(purpose or "general", AI_PURPOSE_PROMPTS["general"])


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


def build_analysis_prompt(*, purpose: str, depth: str, style: str,
                          language: str, country: str, video_frame_count: int) -> str:
    """组装完整分析 prompt（不含图片，图片由调用方以 image_url 形式附上）。"""
    depth_cfg = ANALYSIS_DEPTH_CONFIG.get(depth, ANALYSIS_DEPTH_CONFIG["standard"])
    copy_count = depth_cfg["copy_count"]
    purpose_prompt = resolve_purpose_prompt(purpose)
    style_guide = STYLE_GUIDES.get(style, STYLE_GUIDES["standard"])
    compliance_guide = "" if style == "aggressive" else COMPLIANCE_GUIDE
    lang_code = resolve_language_code(language, country)
    lang_name = AI_LANGUAGE_NAMES.get(lang_code, "English")
    lang_instruction = f"输出语言：{lang_name}。"
    video_hint = (
        f"\n【注意】以下 {video_frame_count} 张图片是同一段视频按时间顺序均匀截取的帧，"
        "请综合理解视频的完整内容、故事线和广告意图后生成文案，不要只描述单帧画面。"
        if video_frame_count > 1 else ""
    )
    analysis_len = "50字以内" if depth == "fast" else "100字以内"
    return f"""{purpose_prompt}{video_hint}

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
