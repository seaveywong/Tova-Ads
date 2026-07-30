"""统一 AI 客户端（OpenAI 兼容；DeepSeek/Grok/Gemini/OpenAI 无损切换）。

全局配置 ai_base_url + ai_api_key + ai_model（审计"AI 厂商——无损切换"）。
切换厂商 = 改 .env 三个值，不改代码。所有 AI 调用（文案/KPI/表单/消息模板）走此客户端。

DeepSeek: base=https://api.deepseek.com/v1 model=deepseek-chat
OpenAI:   base=https://api.openai.com/v1      model=gpt-4o-mini
Grok:     base=https://api.x.ai/v1             model=grok-beta
Gemini:   base=https://generativelanguage.googleapis.com/v1beta/openai model=gemini-flash

视觉（看图）走独立配置 ai_vision_* —— DeepSeek 纯文本不能看图，素材识别用 Gemini 等。
"""
import json
import re
import logging
import httpx
from .config import settings

logger = logging.getLogger("toveads.ai")

# 去掉模型可能裹的 ```json ... ``` 代码块（锚定首尾三反引号，内部单反引号不影响）
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)
_FENCE_OPEN_RE = re.compile(r"^```[a-zA-Z0-9]*\s*\n?")


def _strip_json_fence(raw: str) -> str:
    """去 markdown 代码块包裹。容忍缺尾围栏（被 max_tokens 截断时只去开头 ```json 行）。"""
    raw = (raw or "").strip()
    m = _JSON_FENCE_RE.match(raw)
    if m:
        return m.group(1).strip()
    if raw.startswith("```"):                      # 缺尾围栏：去开头 ```json 行
        return _FENCE_OPEN_RE.sub("", raw, count=1).strip()
    return raw


def _extract_json(raw: str):
    """解析模型 JSON 输出：先去围栏，json.loads 失败则兜底截取首个 {...}/[...]（容忍前后散文/尾部截断）。"""
    raw = _strip_json_fence((raw or "").strip())
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        for oc, cc in (("{", "}"), ("[", "]")):
            i, j = raw.find(oc), raw.rfind(cc)
            if i != -1 and j > i:
                try:
                    return json.loads(raw[i:j + 1])
                except json.JSONDecodeError:
                    continue
        raise


class AiError(Exception):
    """AI 调用失败。"""

    def __init__(self, message: str, status: int = 0):
        self.message = message
        self.status = status
        super().__init__(message)


class AiClient:
    """OpenAI 兼容的 chat completion 客户端。"""

    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str | None = None):
        # 注意：用 `is None` 判定"未传"，不能用 `or`——否则显式传空串(视觉 key 未配)会回退到 ai_api_key，
        # 导致视觉客户端静默用 DeepSeek key 请求 Gemini（被拒 400）。None=用默认，显式值(含"")=用它。
        self.base_url = (settings.ai_base_url if base_url is None else base_url).rstrip("/")
        self.api_key = settings.ai_api_key if api_key is None else api_key
        self.model = settings.ai_model if model is None else model

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def chat(self, messages: list[dict], temperature: float = 0.7,
             max_tokens: int = 1024, timeout: int = 60) -> str:
        """同步 chat completion。messages=[{"role":"system"/"user"/"assistant","content":...}]。
        content 既可以是 str（纯文本），也可以是 list（视觉格式 [{"type":"text"...},{"type":"image_url"...}]）。"""
        if not self.api_key:
            raise AiError("AI 未配置（ai_api_key 为空）")
        resp = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
            json={"model": self.model, "messages": messages,
                  "temperature": temperature, "max_tokens": max_tokens},
            timeout=timeout,
        )
        if resp.status_code != 200:
            raise AiError(f"AI 调用失败 ({resp.status_code}): {resp.text[:300]}", resp.status_code)
        data = resp.json()
        # 健壮解析：空 choices（被安全过滤）/ content 是 list（部分代理返输入形状）都兜住
        choices = data.get("choices") or []
        if not choices:
            raise AiError(f"AI 返回空 choices（可能被安全过滤）: {json.dumps(data, ensure_ascii=False)[:300]}", resp.status_code)
        content = choices[0].get("message", {}).get("content")
        if content is None:
            raise AiError(f"AI 返回空 content: {json.dumps(data, ensure_ascii=False)[:300]}", resp.status_code)
        if isinstance(content, list):
            # 某些 OpenAI 兼容代理把 content 返成 [{"type":"text","text":...}] —— 拼成字符串
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        return content

    def chat_json(self, messages: list[dict], temperature: float = 0.3,
                  max_tokens: int = 1024, timeout: int = 60) -> dict | list:
        """chat 并解析 JSON 输出（防幻觉：要求模型只返 JSON；解析失败 raise）。"""
        raw = self.chat(messages, temperature=temperature, max_tokens=max_tokens, timeout=timeout)
        try:
            return _extract_json(raw)
        except json.JSONDecodeError as e:
            raise AiError(f"AI 输出非合法 JSON: {e}; raw={raw[:200]}")


def vision_client() -> AiClient:
    """视觉模型客户端（素材识别看图用，独立 ai_vision_* 配置）。"""
    return AiClient(
        base_url=settings.ai_vision_base_url,
        api_key=settings.ai_vision_api_key,
        model=settings.ai_vision_model,
    )


def chat_with_images(text_prompt: str, image_b64_list: list[str],
                     mime: str = "image/jpeg", system_prompt: str = "",
                     temperature: float = 0.4, max_tokens: int = 2048,
                     timeout: int = 90) -> str:
    """视觉模型看图：把多张图（base64）+ 文本 prompt 送给视觉模型，返回文本。

    image_b64_list: 不含 data:前缀的纯 base64 字符串列表（图片字节的 base64）。
    用 base64 内联（不依赖模型服务器回拉公网 URL，最稳）。
    """
    vc = vision_client()
    if not vc.is_configured():
        raise AiError("视觉 AI 未配置（ai_vision_api_key 为空）")
    content: list[dict] = [{"type": "text", "text": text_prompt}]
    for b64 in image_b64_list:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}"},
        })
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": content})
    return vc.chat(messages, temperature=temperature, max_tokens=max_tokens, timeout=timeout)


def chat_with_images_json(text_prompt: str, image_b64_list: list[str],
                          mime: str = "image/jpeg", system_prompt: str = "",
                          temperature: float = 0.3, max_tokens: int = 2048,
                          timeout: int = 90) -> dict | list:
    """视觉看图 + 解析 JSON 输出（同 chat_json 的去 markdown 包裹逻辑）。"""
    raw = chat_with_images(text_prompt, image_b64_list, mime=mime, system_prompt=system_prompt,
                           temperature=temperature, max_tokens=max_tokens, timeout=timeout)
    try:
        return _extract_json(raw)
    except json.JSONDecodeError as e:
        raise AiError(f"视觉 AI 输出非合法 JSON: {e}; raw={raw[:200]}")
