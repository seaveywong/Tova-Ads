"""Dynadot API v3 客户端（域名代购主力注册商，2026-09-19 批DE）。

官方：https://www.dynadot.com/domain/api3.html
形态：GET https://api.dynadot.com/api3.json?key=[Key]&command=xxx&参数
返回：{"XxxResponse": {"ResponseCode": "0", ...}}，0=成功 -1=失败（Error 字段）
限流：Regular 账户 1 req/s——查价走缓存（上层 10min），注册/NS 为单次调用不受影响。
单 Key 认证（Tools → API 生成）。支持支付宝充值账户余额，API 消费从余额扣。
"""
import re
import time
import threading
import httpx
import logging

logger = logging.getLogger("toveads.dynadot")

_API = "https://api.dynadot.com/api3.json"

# 全局节流（扫描修 #6）：1 req/s 是账户级配额——实例级 self._last 在"每请求新建客户端"
# 的调用形态下无效，并发查价必撞限流。模块级时间戳跨实例共享（平台单 Dynadot 账户）。
_GLOBAL_LAST = [0.0]
_GLOBAL_PACE_LOCK = threading.Lock()   # 复审 #8：读-睡-写须原子——并发双读旧值会同秒双发


class DynadotError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


class DynadotNotConfigured(DynadotError):
    def __init__(self):
        super().__init__("DYNADOT_NOT_CONFIGURED")


class DynadotClient:
    def __init__(self, api_key: str):
        self.key = api_key

    def _call(self, command: str, **params) -> dict:
        # Regular 账户 1 req/s（账户级）——跨实例全局节流，命令间至少隔 1.1s。
        # 锁内完成 读-睡-写（两个调用起始间隔≥1.1s，即 FB 的请求速率口径）；HTTP 在锁外。
        with _GLOBAL_PACE_LOCK:
            wait = 1.1 - (time.time() - _GLOBAL_LAST[0])
            if wait > 0 and _GLOBAL_LAST[0]:
                time.sleep(wait)
            _GLOBAL_LAST[0] = time.time()
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

    def search_many(self, domains: list) -> list:
        """批量可注册性 + 实时价（域名候选推送用，2026-09-24 域名商店重做）。
        官方 search 支持 domain0..domainN 一次查多个；50/块（全局 1req/s 节流自动间隔，
        超过 50 才会付第二次调用延迟）。返 [{domain, available, price_usd}]，去重不保序。
        API 未返回的域名不出现（视为未查到）。"""
        out, seen = [], set()
        for i in range(0, len(domains), 50):
            chunk = domains[i:i + 50]
            params = {f"domain{j}": d for j, d in enumerate(chunk)}
            body = self._call("search", show_price="1", currency="USD", **params)
            for x in (body.get("SearchResults") or []):
                d = str(x.get("DomainName") or "").lower()
                if not d or d in seen:
                    continue
                seen.add(d)
                m = re.match(r"([\d.]+)", str(x.get("Price") or ""))
                out.append({"domain": d,
                            "available": str(x.get("Available")).lower() == "yes",
                            "price_usd": round(float(m.group(1)), 2) if m else None})
        return out

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
