"""配置中心（SSOT）—— 所有配置从环境变量/.env 读，单一来源。"""
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 数据库
    database_url: str
    database_super_url: str
    # JWT
    jwt_secret: str
    jwt_alg: str = "HS256"
    jwt_expire_min: int = 10080  # 7 天（搭配滑动续期=闲置超7天才掉线；活跃用永不掉）
    jwt_refresh_expire_days: int = 7
    # 环境
    app_env: str = "development"
    # FB 凭证加密（Fernet）
    fb_cred_key: str = "placeholder"

    @model_validator(mode="after")
    def _fail_fast_on_weak_secrets(self):
        """生产环境弱密钥直接拒启（jwt_secret<32 或 fb_cred_key 是占位符=加密形同虚设）。"""
        if self.app_env == "production":
            if len(self.jwt_secret or "") < 32:
                raise ValueError("production 环境 jwt_secret 必须 ≥32 字符")
            if not self.fb_cred_key or self.fb_cred_key in ("placeholder", "") or len(self.fb_cred_key) < 32:
                raise ValueError("production 环境必须配置真实 Fernet fb_cred_key")
        return self
    # Cloudflare API
    cf_api_token: str = ""
    cf_account_id: str = ""
    # 公网 base URL（OAuth 回调、worker URL 等用）
    public_base_url: str = "https://api.tovaads.com"
    # 前端 base URL（OAuth 完成页"返回前端"链接用）
    frontend_base_url: str = "https://tovaads.com"

    # AI 全局配置（无损切换厂商：Gemini/OpenAI/DeepSeek/Grok，均 OpenAI 兼容）
    # 切换 = 改 base_url + key + model，不改代码（审计"AI 厂商无损切换"）
    # 默认 Gemini：文案/KPI/表单生成都走 Gemini，视觉另配 ai_vision_*（同为 Gemini）。
    ai_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    ai_api_key: str = ""
    ai_model: str = "gemini-2.5-flash"

    # AI 视觉模型（素材识别看图用；DeepSeek 纯文本不能看图，单独配 Gemini 等视觉模型）
    # 与文案配置独立：文案/KPI 走 ai_*（DeepSeek），素材看图走 ai_vision_*（Gemini）
    ai_vision_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    ai_vision_api_key: str = ""
    ai_vision_model: str = "gemini-2.5-flash"  # 2.0-flash 已下线(404)，用 2.5-flash

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")


settings = Settings()
