"""Dynadot RESTful API v2 客户端（2026-09-26 重写：API3 → REST v2，密钥对实证）。

官方：https://www.dynadot.com/domain/api-document（RESTful tab）
形态：https://api.dynadot.com/restful/v2/...
认证：Authorization: Bearer <API生产密钥>；敏感端点（账户信息/注册/NS 写操作）
      强制 X-Signature = Base64(HMAC-SHA256(key + "\\n" + 路径含query + "\\n" +
      request_id + "\\n" + body, Secret))，随头发 X-Request-ID。
响应：HTTP 恒 200，body {code:200|400, message, data|error.description}。
限流：Regular 账户 1 req/s——实测连发 4-5 个即回 400（2026-09-26 探针实证），
      保留全局 1.1s 节流；400 且 message 含 rate/rate limit 上抛原文。
凭据：Dynadot → 账户 → Tools → API 的「API 生产密钥」+「密钥(Secret)」两把
      （截图 2026-09-26 实证；Secret 只在敏感端点用到，查价/搜索免）。
注意：REST search 不返回实时价（API3 曾带价）——价格统一走 tld_price 价目表
      （上层 _pricing 10min 缓存），premium 域以下单核验为准。
"""
import re
import time
import base64
import hmac
import hashlib
import threading
import uuid
import httpx
import logging
import json

logger = logging.getLogger("toveads.dynadot")

_BASE = "https://api.dynadot.com"

# 全局节流：1 req/s 是账户级配额——实例级时间戳在"每请求新建客户端"的调用形态下
# 无效，并发查价必撞限流。模块级跨实例共享（平台单 Dynadot 账户）。
_GLOBAL_LAST = [0.0]
_GLOBAL_PACE_LOCK = threading.Lock()   # 读-睡-写须原子——并发双读旧值会同秒双发

_RATE_HINTS = ("rate limit", "rate_limit", "too many", "exceed")


class DynadotError(Exception):
    def __init__(self, message: str, rate_limited: bool = False):
        super().__init__(message)
        self.rate_limited = rate_limited


class DynadotNotConfigured(DynadotError):
    def __init__(self):
        super().__init__("DYNADOT_NOT_CONFIGURED")


class DynadotSecretMissing(DynadotError):
    """敏感端点（注册/NS/账户）需要 Secret 签名而未配置 Secret。"""

    def __init__(self):
        super().__init__("DYNADOT_SECRET_REQUIRED")


class DynadotClient:
    def __init__(self, api_key: str, api_secret: str = ""):
        self.key = (api_key or "").strip()
        self.secret = (api_secret or "").strip()

    # ── 签名：Base64(HMAC-SHA256(key\n路径\nrequest_id\nbody, secret)) ──
    def _signature(self, path_and_query: str, request_id: str, body_str: str) -> str:
        msg = "\n".join([self.key, path_and_query, request_id, body_str])
        return base64.b64encode(
            hmac.new(self.secret.encode(), msg.encode(), hashlib.sha256).digest()
        ).decode()

    def _call(self, method: str, path: str, params: dict = None,
              body: dict = None, signed: bool = False) -> dict:
        """统一请求。path 形如 /restful/v2/...；返回 data 部分。"""
        # 1 req/s（账户级，实测连发即 400）——锁内读-睡-写，HTTP 在锁外
        with _GLOBAL_PACE_LOCK:
            wait = 1.1 - (time.time() - _GLOBAL_LAST[0])
            if wait > 0 and _GLOBAL_LAST[0]:
                time.sleep(wait)
            _GLOBAL_LAST[0] = time.time()
        q = str(httpx.QueryParams({k: str(v) for k, v in (params or {}).items()
                                   if v is not None}))
        full = path + ("?" + q if q else "")
        body_str = json.dumps(body, ensure_ascii=False) if body is not None else ""
        headers = {"Authorization": f"Bearer {self.key}", "Accept": "application/json"}
        if signed:
            if not self.secret:
                raise DynadotSecretMissing()
            rid = uuid.uuid4().hex
            headers["X-Request-ID"] = rid
            headers["X-Signature"] = self._signature(full, rid, body_str)
        if body is not None:
            headers["Content-Type"] = "application/json"
        r = httpx.request(method, _BASE + full, headers=headers,
                          content=body_str.encode() if body_str else None, timeout=30)
        try:
            data = r.json()
        except Exception:
            raise DynadotError(f"Dynadot 返回非 JSON（HTTP {r.status_code}）")
        if data.get("code") != 200:
            err = str(((data.get("error") or {}).get("description"))
                      or data.get("message") or data)[:250]
            low = err.lower()
            raise DynadotError(f"[{path.split('?')[0]}] {err}",
                               rate_limited=any(h in low for h in _RATE_HINTS))
        return data.get("data") or {}

    # ── 账户（敏感：需 Secret）──
    def account_info(self) -> dict:
        """账户信息（测试连接用）。REST 返回 username/account_contact/total_spending 等。"""
        return self._call("GET", "/restful/v2/accounts/info", signed=True).get("account_info") or {}

    # ── 可注册性（免签名）──
    def search(self, domain: str) -> dict:
        """单域名可注册性 → {available, price_usd}。
        REST search 不返回价格（price_usd 恒 None，上层价目表兜底）。"""
        d = domain.lower().strip()
        data = self._call("GET", f"/restful/v2/domains/{d}/search")
        return {"available": str(data.get("available", "")).lower() == "yes",
                "price_usd": None}

    def search_many(self, domains: list) -> list:
        """批量可注册性（bulk_search，逗号拼接 domain_name_list，50/块）。
        返 [{domain, available, price_usd:None}]，API 未返回的域名不出现。"""
        out, seen = [], set()
        dl = [str(d).lower().strip() for d in domains if d]
        for i in range(0, len(dl), 50):
            chunk = dl[i:i + 50]
            data = self._call("GET", "/restful/v2/domains/bulk_search",
                              params={"domain_name_list": ",".join(chunk)})
            for x in (data.get("domain_result_list") or []):
                d = str(x.get("domain_name") or "").lower()
                if not d or d in seen:
                    continue
                seen.add(d)
                out.append({"domain": d, "available": str(x.get("available", "")).lower() == "yes",
                            "price_usd": None})
        return out

    # ── 价目表（免签名）──
    def pricing(self) -> dict:
        """全 TLD 价格表 → {tld: {registration, renewal}}（上层 10min 缓存）。
        currency 必填；一年价 = all_years_register_price[0]（show_multi_year_price=No 时列表仅 1 项）。"""
        data = self._call("GET", "/restful/v2/domains/get_tld_price",
                          params={"currency": "USD"})
        out = {}
        for t in (data.get("tld_price_list") or []):
            reg = (t.get("all_years_register_price") or [None])[0]
            ren = (t.get("all_years_renew_price") or [None])[0]
            out[str(t.get("tld")).lstrip(".")] = {"registration": _f(reg), "renewal": _f(ren)}
        return out

    # ── 写操作（敏感：需 Secret）──
    def register(self, domain: str, years: int = 1) -> dict:
        """注册（从账户余额扣费）。路径带域名；duration/currency/privacy 入 body。
        注册后用 set_ns 切 CF（REST register 的 name_server_list 可一并传，但两步走
        与 CF 先建 zone 的顺序绑定——zone NS 分配后才可知，维持注册→set_ns 两步）。"""
        d = domain.lower().strip()
        return self._call("POST", f"/restful/v2/domains/{d}/register", signed=True,
                          body={"duration": years, "currency": "USD", "privacy": "full"})

    def set_ns(self, domain: str, ns: list) -> dict:
        """域名 NS 切到 CF（PUT nameservers，body nameserver_list）。"""
        d = domain.lower().strip()
        return self._call("PUT", f"/restful/v2/domains/{d}/nameservers", signed=True,
                          body={"nameserver_list": [str(h).strip() for h in ns if str(h).strip()]})

    def renew(self, domain: str, years: int = 1) -> dict:
        d = domain.lower().strip()
        return self._call("POST", f"/restful/v2/domains/{d}/renew", signed=True,
                          body={"duration": years, "currency": "USD"})


def _f(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None
