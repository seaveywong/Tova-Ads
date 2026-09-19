"""Porkbun API 客户端（域名代购：查价/注册/续费/NS——2026-09-19 批DD 预埋）。

凭据从 settings 读（Settings → Porkbun 配置卡，超管）；未配置时各调用抛 PorkbunNotConfigured
——上层返回明确报错引导配置，不炸。Porkbun API 形态：POST json 到
https://api.porkbun.com/api/json/v3/{endpoint}，apikey+secret 随体。

用的端点（Porkbun 官方 API 文档 porkbun.com/products/api）：
- ping：验证凭据 + 返回账号信息（含余额状态 Anonymous Billing）
- domain/getPricing：全部 TLD 价格表（注册/续费/转入，美元）
- domain/check：可注册性
- domain/register：注册（可带 ns 直接指定 CF 名称服务器——一步到位）
- domain/renew：续费
- domain/getNs / domain/updateNs：名称服务器读写（兜底：注册时未带 ns 的补设）
"""
import httpx
import logging

logger = logging.getLogger("toveads.porkbun")

_API = "https://api.porkbun.com/api/json/v3"


class PorkbunError(Exception):
    def __init__(self, message: str, status: str = "ERROR"):
        super().__init__(message)
        self.status = status


class PorkbunNotConfigured(PorkbunError):
    def __init__(self):
        super().__init__("PORKBUN_NOT_CONFIGURED")


def porkbun_configured(settings) -> bool:
    return bool(getattr(settings, "porkbun_api_key", None)
                and getattr(settings, "porkbun_secret_key", None))


class PorkbunClient:
    def __init__(self, api_key: str, secret_key: str):
        self.api_key = api_key
        self.secret = secret_key

    def _call(self, endpoint: str, payload: dict | None = None, timeout: int = 30) -> dict:
        body = {"apikey": self.api_key, "secretapikey": self.secret}
        body.update(payload or {})
        r = httpx.post(f"{_API}/{endpoint}", json=body, timeout=timeout)
        try:
            data = r.json()
        except Exception:
            raise PorkbunError(f"Porkbun 返回非 JSON（HTTP {r.status_code}）")
        if data.get("status") != "SUCCESS":
            raise PorkbunError(str(data.get("message") or data)[:200], data.get("status", ""))
        return data

    # ── 凭据验证（配置卡「测试连接」）──
    def ping(self) -> dict:
        return self._call("ping")

    # ── 价格（下单成本快照；缓存由上层管）──
    def pricing(self) -> dict:
        """全 TLD 价格表 → {tld: {register/renew/transfer/transferrenew}}}（美元浮点）"""
        d = self._call("domain/getPricing")["pricing"] or {}
        out = {}
        for tld, p in d.items():
            out[tld] = {"registration": _f(p.get("registration")),
                        "renewal": _f(p.get("renewal"))}
        return out

    def check(self, domain: str) -> dict:
        """可注册性：{'porkbunAvailable': 'yes'/'no', price?}"""
        return self._call("domain/check", {"domain": domain})

    # ── 注册（ns 直指 CF——注册完即接入，无需二次设置）──
    def register(self, domain: str, years: int = 1, ns: list[str] | None = None) -> dict:
        payload = {"domain": domain, "period": years}
        if ns:
            payload["ns"] = ns
        return self._call("domain/register", payload)

    def renew(self, domain: str, years: int = 1) -> dict:
        return self._call("domain/renew", {"domain": domain, "period": years})

    def update_ns(self, domain: str, ns: list[str]) -> dict:
        return self._call("domain/updateNs", {"domain": domain, "ns": ns})


def _f(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None
