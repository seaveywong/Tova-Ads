"""统一 AI 客户端（OpenAI 兼容；DeepSeek/Grok/Gemini/OpenAI 无损切换）。

全局配置 ai_base_url + ai_api_key + ai_model（审计"AI 厂商——无损切换"）。
切换厂商 = 改 .env 三个值，不改代码。所有 AI 调用（文案/KPI/表单/消息模板）走此客户端。

DeepSeek: base=https://api.deepseek.com/v1 model=deepseek-chat
OpenAI:   base=https://api.openai.com/v1      model=gpt-4o-mini
Grok:     base=https://api.x.ai/v1             model=grok-beta
Gemini:   base=https://generativelanguage.googleapis.com/v1beta/openai model=gemini-flash
"""
import json
import logging
import httpx
from .config import settings

logger = logging.getLogger("toveads.ai")


class AiError(Exception):
    """AI 调用失败。"""

    def __init__(self, message: str, status: int = 0):
        self.message = message
        self.status = status
        super().__init__(message)


class AiClient:
    """OpenAI 兼容的 chat completion 客户端。"""

    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str | None = None):
        self.base_url = (base_url or settings.ai_base_url).rstrip("/")
        self.api_key = api_key or settings.ai_api_key
        self.model = model or settings.ai_model

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def chat(self, messages: list[dict], temperature: float = 0.7,
             max_tokens: int = 1024, timeout: int = 60) -> str:
        """同步 chat completion。messages=[{"role":"system"/"user"/"assistant","content":...}]。"""
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
        return data["choices"][0]["message"]["content"]

    def chat_json(self, messages: list[dict], temperature: float = 0.3,
                  max_tokens: int = 1024, timeout: int = 60) -> dict | list:
        """chat 并解析 JSON 输出（防幻觉：要求模型只返 JSON；解析失败 raise）。"""
        raw = self.chat(messages, temperature=temperature, max_tokens=max_tokens, timeout=timeout)
        raw = raw.strip()
        # 去掉 ```json ... ``` 包裹
        if raw.startswith("```"):
            raw = raw.split("```", 2)
            raw = raw[1] if len(raw) >= 2 else raw[0]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise AiError(f"AI 输出非合法 JSON: {e}; raw={raw[:200]}")
