"""Dynadot API v3 客户端（域名代购主力注册商，2026-09-19 批DE）。

官方：https://www.dynadot.com/domain/api3.html
形态：GET https://api.dynadot.com/api3.json?key=[Key]&command=xxx&参数
返回：{"XxxResponse": {"ResponseCode": "0", ...}}，0=成功 -1=失败（Error 字段）
限流：Regular 账户 1 req/s——查价走缓存（上层 10min），注册/NS 为单次调用不受影响。
单 Key 认证（Tools → API 生成）。支持支付宝充值账户余额，API 消费从余额扣。
"""
import re
import time
import httpx
import logging

logger = logging.getLogger("toveads.dynadot")

_API = "https://api.dynadot.com/api3.json"


class DynadotError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


class DynadotNotConfigured(DynadotError):
    def __init__(self):
        super().__init__("DYNADOT_NOT_CONFIGURED")


class DynadotClient:
    def __init__(self, api_key: str):
        self.key = api_key
        self._last = 0.0

    def _call(self, command: str, **params) -> dict:
        # Regular 账户 1 req/s——命令间至少隔 1.1s（上层查价已缓存，此处多为单发）
        wait = 1.1 - (time.time() - self._last)
        if wait > 0 and self._last:
            time.sleep(wait)
        self._last = time.time()
        q = {"key": self.key, "command": command}
        q.update({k: v for k, v in params.items() if v is not None})
        r = httpx.get(_API, params=q, timeout=30)
        try:
            data = r.json()
        except Exception:
            raise DynadotError(f"Dynadot 返回非 JSON（HTTP {r.status_code}）")
        # 响应包名 = command snake_case → PascalCase + "Response"（官方映射：
        # account_info→AccountInfoResponse / tld_price→TldPriceResponse / set_ns→SetNsResponse；
        # str.capitalize() 会得 Account_info——多词命令全解析失败，2026-09-21 全面扫描修复）
        wrap = "".join(w.capitalize() for w in command.split("_")) + "Response"
        body = data.get(wrap) or data
        code = str(body.get("ResponseCode", body.get("SuccessCode", "-1")))
        if code != "0":
            raise DynadotError(f"[{command}] {str(body.get('Error') or body)[:200]}")
        return body

    def account_info(self) -> dict:
        """账户信息（测试连接用；含 AccountBalance/PriceLevel）。"""
        return self._call("account_info").get("AccountInfo") or {}

    def balance(self) -> dict:
        """余额 {currency: amount}。"""
        out = {}
        for b in (self._call("get_account_balance").get("BalanceList") or []):
            out[b.get("Currency")] = b.get("Amount")
        return out

    def search(self, domain: str) -> dict:
        """可注册性 + 实时价（show_price=1）→ {available, price_usd}。
        Price 形如 "77.00 in USD"（premium 域会带说明）——正则取首数。"""
        body = self._call("search", domain0=domain, show_price="1", currency="USD")
        rows = body.get("SearchResults") or []
        row = next((x for x in rows if x.get("DomainName", "").lower() == domain.lower()), None)
        if not row:
            raise DynadotError("search 未返回该域名结果")
        m = re.match(r"([\d.]+)", str(row.get("Price") or ""))
        return {"available": str(row.get("Available")).lower() == "yes",
                "price_usd": round(float(m.group(1)), 2) if m else None}

    def pricing(self) -> dict:
        """全 TLD 价格表 → {tld: {registration, renewal}}（上层缓存）。"""
        body = self._call("tld_price", currency="USD")
        out = {}
        for t in (body.get("TldPrice") or []):
            p = t.get("Price") or {}
            out[str(t.get("Tld")).lstrip(".")] = {
                "registration": _f(p.get("Register")), "renewal": _f(p.get("Renew"))}
        return out

    def register(self, domain: str, years: int = 1) -> dict:
        """注册（从账户余额扣费）。Dynadot register 不带 NS——注册后用 set_ns 切 CF。"""
        return self._call("register", domain=domain, duration=years, currency="USD")

    def set_ns(self, domain: str, ns: list) -> dict:
        """域名 NS 切到 CF（ns0/ns1...参数）。"""
        params = {"domain": domain}
        for i, h in enumerate(ns[:13]):
            params[f"ns{i}"] = h
        return self._call("set_ns", **params)

    def renew(self, domain: str, years: int = 1) -> dict:
        return self._call("renew", domain=domain, duration=years, currency="USD")


def _f(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None
