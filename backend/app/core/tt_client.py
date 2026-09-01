"""统一 TikTok Business API 客户端（所有 TT 调用唯一入口）。

功能：自计数限流（无官方 RPM 数字/响应头，滑动窗 + 429 指数退避封路）、
错误翻译、token 过期请求前自动刷新（双保险，cron 为主）、分页拉取。

认证风格与 FB 不同：access_token 走 query 参数（TK 风格）；
OAuth 端点（access_token/refresh_token/advertiser/get）用 app_id + secret/refresh_token。

方法面与 FbClient 对齐（get_campaigns/get_adsets/get_ads/get_active_ads/
get_ad_insights/pause_ad/get_node/update_status），供巡检按平台分发复用；
参数结构与 FB 不同（advertiser_id 维度 + filtering JSON），sandbox 实测后再校准。
"""
import json
import os
import time
import logging
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx

logger = logging.getLogger("toveads.tt")

TT_BASE = "https://business-api.tiktok.com/open_api/v1.3/"
TT_AUTH_PORTAL = "https://business-api.tiktok.com/portal/auth"
TIMEOUT = 30
MAX_RETRIES = 3

# access_token 24h / refresh_token 365d（官方固定值，响应 expires_in 兜底用）
ACCESS_TTL_S = 86400
REFRESH_TTL_S = 31536000

# ── 自计数限流器（TK 无公开 RPM 数字、无标准 X-RateLimit 头）──
# 每 endpoint 滑动窗计数（观测 + 软顶）；429/code 42900/"rate limit" → 指数退避
# 2^strikes 秒封路（封顶 300s）。软顶是保守防御值，正常巡检远达不到。
RATE_WINDOW_S = 60.0
RATE_SOFT_CAP = 300        # 每 endpoint 每 60s 主动上限（无官方数字的保守防御）
MAX_BACKOFF_S = 300        # 封路封顶
MAX_BLOCK_SLEEP = 10.0     # 门禁时等待上限：≤10s 睡等，更长直接拒（调用方跳过）
MAX_INLINE_RETRY_S = 30.0  # 429 后同请求内最长重试等待

_rate_lock = threading.Lock()
_rate_state: dict[str, "_Throttle"] = {}


class _Throttle:
    __slots__ = ("window", "strikes", "blocked_until")

    def __init__(self):
        self.window: deque[float] = deque()
        self.strikes = 0
        self.blocked_until = 0.0


def _throttle(key: str) -> _Throttle:
    th = _rate_state.get(key)
    if th is None:
        th = _rate_state[key] = _Throttle()
    return th


def _strike_locked(key: str, th: _Throttle, now: float) -> float:
    th.strikes += 1
    wait = float(min(2 ** th.strikes, MAX_BACKOFF_S))
    th.blocked_until = now + wait
    logger.warning(f"[TT] {key} 限流，第 {th.strikes} 次退避 {wait:.0f}s")
    return wait


def throttle_wait(key: str) -> float:
    """该 endpoint 当前剩余封路秒数（0=未封）。"""
    with _rate_lock:
        th = _rate_state.get(key)
        if not th:
            return 0.0
        return max(0.0, th.blocked_until - time.time())


def throttle_strike(key: str) -> float:
    """外部观测到限流时手动记一次 strike（如异步报表轮询）。返回本次退避秒数。"""
    with _rate_lock:
        return _strike_locked(key, _throttle(key), time.time())


def throttle_snapshot() -> dict:
    """限流器快照（观测/排障）：{endpoint: {count_60s, strikes, blocked_remaining_s}}。"""
    now = time.time()
    with _rate_lock:
        out = {}
        for key, th in _rate_state.items():
            while th.window and th.window[0] <= now - RATE_WINDOW_S:
                th.window.popleft()
            out[key] = {"count_60s": len(th.window), "strikes": th.strikes,
                        "blocked_remaining_s": round(max(0.0, th.blocked_until - now), 1)}
        return out


def _throttle_enter(key: str) -> None:
    """请求前门禁：封路中 → 短封睡等后重过门禁，长封直接拒；滑动窗超软顶 → 记 strike。"""
    while True:
        with _rate_lock:
            th = _throttle(key)
            now = time.time()
            while th.window and th.window[0] <= now - RATE_WINDOW_S:
                th.window.popleft()
            if now >= th.blocked_until and len(th.window) < RATE_SOFT_CAP:
                th.window.append(now)
                return
            if now < th.blocked_until:
                wait = th.blocked_until - now
            else:  # 软顶触发
                wait = _strike_locked(key, th, now)
        if wait > MAX_BLOCK_SLEEP:
            raise TtApiError("rate_limited",
                             f"TikTok 接口限流冷却中（约 {wait:.0f}s 后恢复），本次请求已跳过",
                             {"endpoint": key}, 0)
        time.sleep(wait + 0.05)


def _throttle_success(key: str) -> None:
    with _rate_lock:
        th = _rate_state.get(key)
        if th:
            th.strikes = 0


# ── TT 错误码 → (category, 人话)。sandbox 实测后扩充 ──
TT_ERROR_MAP = {
    40000: ("invalid_param", "请求参数错误"),
    40001: ("invalid_param", "请求参数缺失"),
    40100: ("invalid_param", "请求格式错误"),
    40102: ("auth_code_invalid", "授权码无效或已过期（10 分钟内有效），请重新授权"),
    40103: ("token_missing", "缺少 Access Token"),
    40105: ("token_expired", "Access Token 无效或已过期，需刷新或重新授权"),
    40106: ("refresh_invalid", "Refresh Token 无效或已过期，需重新走 TikTok 授权"),
    40400: ("not_found", "对象不存在"),
    40113: ("permissions", "无权操作该对象（权限不足或对象不属于该广告主）"),
    40115: ("permissions", "Scope 权限不足，请在 TikTok 开发者后台申请"),
    42900: ("rate_limited", "请求过于频繁，请稍后重试"),
}


def classify_tt_error(code: int, message: str = "") -> tuple[str, str]:
    if code in TT_ERROR_MAP:
        return TT_ERROR_MAP[code]
    m = (message or "").lower()
    if "rate limit" in m:
        return TT_ERROR_MAP[42900]
    if "token" in m and ("expire" in m or "invalid" in m):
        return TT_ERROR_MAP[40105]
    return ("generic", f"TikTok 返回错误（code {code}）：{(message or '')[:120]}")


class TtApiError(Exception):
    """TT API 调用失败 —— 与 FbApiError 同形：category + friendly + raw + status。"""

    def __init__(self, category: str, friendly: str, raw: dict = None, status: int = 0):
        self.category = category
        self.friendly = friendly
        self.raw = raw or {}
        self.status = status
        super().__init__(friendly)


def _is_rate_limited(status_code: int, result: dict) -> bool:
    if status_code == 429 or result.get("code") == 42900:
        return True
    return "rate limit" in str(result.get("message", "")).lower()


def _raw_call(method: str, path: str, params: dict = None, data: dict = None,
              throttle_key: str = "") -> dict:
    """单次 HTTP（含限流门禁 + 错误分类）。不做重试/刷新——上层语义各异。"""
    key = throttle_key or f"{method} {path}"
    _throttle_enter(key)
    url = TT_BASE + path
    try:
        if method == "POST":
            resp = httpx.post(url, params=params, json=(data or {}), timeout=TIMEOUT)
        else:
            resp = httpx.get(url, params=params, timeout=TIMEOUT)
    except httpx.RequestError as e:
        raise TtApiError("network", f"网络错误：{e}", {}, 0)
    try:
        result = resp.json()
    except Exception:
        raise TtApiError("network",
                         f"响应非 JSON（HTTP {resp.status_code}）：{resp.text[:120]}", {}, resp.status_code)
    if _is_rate_limited(resp.status_code, result):
        throttle_strike(key)  # 429/42900 → 记 strike，端点进入 2^n 指数退避封路
        raise TtApiError("rate_limited", TT_ERROR_MAP[42900][1], result, resp.status_code)
    code = result.get("code", 0)
    if code != 0:
        cat, friendly = classify_tt_error(code, result.get("message", ""))
        logger.warning(f"[TT] {method} {path} → {cat}: {friendly}")
        raise TtApiError(cat, friendly, result, resp.status_code)
    _throttle_success(key)
    return result


class TtClient:
    """统一 TikTok Business API 客户端。

    refresher: () -> new_access_token | None。业务请求遇 token_expired 时自动调用一次、
    换 token 原地重试（cron 刷新为主，这里兜请求间隙过期）；refresher 内部负责 DB 轮换写回。
    """

    def __init__(self, access_token: str, app_id: str = "",
                 refresher: Callable[[], str | None] = None):
        self.token = access_token
        self.app_id = app_id
        self.refresher = refresher
        self._refreshed_once = False

    # ── 底层请求（重试 + 限流退避 + token 过期自动刷新一次）──
    def _request(self, method: str, path: str, params: dict = None, data: dict = None) -> dict:
        key = f"{method} {path}"
        base = dict(params or {})
        for attempt in range(MAX_RETRIES):
            p = dict(base)
            p["access_token"] = self.token
            try:
                return _raw_call(method, path, p, data, throttle_key=key)
            except TtApiError as e:
                if e.category == "rate_limited":
                    wait = throttle_wait(key) or 2.0
                    if attempt < MAX_RETRIES - 1 and wait <= MAX_INLINE_RETRY_S:
                        time.sleep(wait)
                        continue
                    raise
                if e.category == "network" and method == "GET" and attempt < MAX_RETRIES - 1:
                    # 读幂等：网络错误退避重试；POST 非幂等（结果未知）直接抛，防重复创建
                    wait = 2 ** attempt
                    logger.info(f"[TT] 网络错误，{wait}s 后重试: {e.friendly}")
                    time.sleep(wait)
                    continue
                # token 过期双保险：refresher 轮换后原地重试一次
                if (e.category == "token_expired" and self.refresher
                        and not self._refreshed_once):
                    self._refreshed_once = True
                    try:
                        new_tok = self.refresher()
                    except Exception as re:
                        logger.warning(f"[TT] 自动刷新失败（{path}）: {re}")
                        new_tok = None
                    if new_tok:
                        self.token = new_tok
                        continue
                raise

        raise TtApiError("unknown", f"重试耗尽：{method} {path}", {}, 0)

    def get(self, path: str, params: dict = None) -> dict:
        return self._request("GET", path, params)

    def post(self, path: str, data: dict = None) -> dict:
        return self._request("POST", path, data=data)

    def get_paged(self, path: str, params: dict = None, page_size: int = 100,
                  max_total: int = 5000) -> list[dict]:
        """TT 分页拉取：data.list + data.page_info(page/total_page) 自动翻页。
        TT 默认 page_size=10，必须显式传。"""
        base = dict(params or {})
        out: list[dict] = []
        page = 1
        while len(out) < max_total:
            p = dict(base, page=page, page_size=page_size)
            data = self.get(path, p).get("data") or {}
            items = data.get("list") or []
            out.extend(items)
            info = data.get("page_info") or {}
            try:
                total_page = int(info.get("total_page") or 1)
            except (TypeError, ValueError):
                total_page = 1
            if not items or page >= total_page:
                break
            page += 1
        return out

    # ── OAuth 端点（模块级，无需实例；app_id+secret 维度）──

    @staticmethod
    def exchange_auth_code(app_id: str, secret: str, auth_code: str) -> dict:
        """auth_code → {access_token(24h), refresh_token(365d), advertiser_ids, scope, expires_in...}。
        auth_code 10 分钟有效；连接类网络错误重试 1 次。"""
        params = {"app_id": app_id, "secret": secret, "auth_code": auth_code}
        for attempt in range(2):
            try:
                return (_raw_call("GET", "oauth2/access_token/", params).get("data") or {})
            except TtApiError as e:
                if e.category == "network" and attempt == 0:
                    time.sleep(1)
                    continue
                raise
        return {}

    @staticmethod
    def refresh_access_token(app_id: str, secret: str, refresh_token: str) -> dict:
        """刷新（轮换）：返回全新 access_token + refresh_token，旧 refresh_token 立即失效。
        调用方必须把两个新 token 原子写回 DB（见 services/tt_token_refresh.py）。"""
        params = {"app_id": app_id, "secret": secret, "refresh_token": refresh_token}
        for attempt in range(2):
            try:
                return (_raw_call("GET", "oauth2/refresh_token/", params).get("data") or {})
            except TtApiError as e:
                if e.category == "network" and attempt == 0:
                    time.sleep(1)
                    continue
                raise
        return {}

    @staticmethod
    def get_authorized_advertisers(access_token: str, app_id: str) -> list[dict]:
        """授权主体列表：[{advertiser_id, name, ...}]（一个 token 带多 advertiser）。"""
        params = {"access_token": access_token, "app_id": app_id}
        data = _raw_call("GET", "oauth2/advertiser/get/", params).get("data") or {}
        return data.get("list") or []

    # ── 广告对象读取（对齐 FbClient 方法面，供 P4 巡检分发）──

    _STATUS_MAP = {"ACTIVE": "STATUS_ENABLE", "PAUSED": "STATUS_DISABLE",
                   "ARCHIVED": "STATUS_DELETE", "DELETED": "STATUS_DELETE"}

    @classmethod
    def _norm_statuses(cls, v) -> list[str] | None:
        """'["ACTIVE"]'（FB 风格）或 TT 原生 ['STATUS_ENABLE', ...] → TT statuses 列表。"""
        if v is None:
            return None
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except ValueError:
                return None
        if not isinstance(v, (list, tuple)) or not v:
            return None
        return [cls._STATUS_MAP.get(str(s).upper(), str(s).upper()) for s in v]

    def get_campaigns(self, advertiser_id: str, effective_status=None, fields=None) -> list[dict]:
        """拉广告系列（全量分页）。effective_status=None 拉全状态（管理器），默认全量。"""
        params: dict[str, Any] = {"advertiser_id": advertiser_id}
        st = self._norm_statuses(effective_status)
        if st:
            params["filtering"] = json.dumps({"statuses": st})
        if fields:
            params["fields"] = json.dumps(fields)
        return self.get_paged("campaign/get/", params)

    def get_adsets(self, advertiser_id: str, effective_status=None, fields=None) -> list[dict]:
        """拉广告组（全量分页）。"""
        params: dict[str, Any] = {"advertiser_id": advertiser_id}
        st = self._norm_statuses(effective_status)
        if st:
            params["filtering"] = json.dumps({"statuses": st})
        if fields:
            params["fields"] = json.dumps(fields)
        return self.get_paged("adgroup/get/", params)

    def get_ads(self, advertiser_id: str, effective_status=None, fields=None) -> list[dict]:
        """拉广告（全量分页）。effective_status=None 拉全状态（管理器）。"""
        params: dict[str, Any] = {"advertiser_id": advertiser_id}
        st = self._norm_statuses(effective_status)
        if st:
            params["filtering"] = json.dumps({"statuses": st})
        if fields:
            params["fields"] = json.dumps(fields)
        return self.get_paged("ad/get/", params)

    def get_active_ads(self, advertiser_id: str) -> list[dict]:
        """拉投放中广告（巡检/哨兵用）。"""
        return self.get_ads(advertiser_id, '["ACTIVE"]')

    def get_ad_insights(self, advertiser_id: str, date_preset: str = "today",
                        since: str = "", until: str = "",
                        only_active: bool = False, limit: int = 100) -> list[dict]:
        """广告级报表（report/integrated/get，BASIC / AUCTION_AD / dimensions=ad_id）。

        since/until 为 YYYY-MM-DD（账户本地日，调用方算好，同 FB 语义）；
        不传则按 date_preset 兜底 UTC 日。行已摊平：dimensions.ad_id 与 metrics.*
        提到顶层。TT 报表不含投放状态，only_active 无法在此过滤（由调用方 join ad/get）。
        """
        if not (since and until):
            now = datetime.now(timezone.utc)
            if date_preset == "yesterday":
                d = now - timedelta(days=1)
                since = until = d.strftime("%Y-%m-%d")
            elif date_preset == "last_7d":
                until = now.strftime("%Y-%m-%d")
                since = (now - timedelta(days=6)).strftime("%Y-%m-%d")
            elif date_preset == "last_30d":
                until = now.strftime("%Y-%m-%d")
                since = (now - timedelta(days=29)).strftime("%Y-%m-%d")
            else:
                since = until = now.strftime("%Y-%m-%d")
        params = {
            "advertiser_id": advertiser_id,
            "report_type": "BASIC",
            "data_level": "AUCTION_AD",
            "dimensions": json.dumps(["ad_id"]),
            "metrics": json.dumps(["spend", "impressions", "clicks", "ctr", "cpc",
                                   "cpm", "conversions"]),
            "start_date": since,
            "end_date": until,
        }
        rows = self.get_paged("report/integrated/get/", params, page_size=min(limit, 200))
        for r in rows:
            dim = r.pop("dimensions", None) or {}
            if isinstance(dim, dict):
                for k, v in dim.items():
                    r.setdefault(k, v)
            metrics = r.pop("metrics", None)
            if isinstance(metrics, dict):
                for k, v in metrics.items():
                    r.setdefault(k, v)
        return rows

    def get_advertiser_info(self, advertiser_id: str) -> dict:
        """单广告主详情（name/currency/timezone，账户导入用）。"""
        data = self.get("advertiser/info/", {"advertiser_ids": json.dumps([str(advertiser_id)])})
        return ((data.get("data") or {}).get("list") or [{}])[0]

    def get_ad_accounts(self) -> list[dict]:
        """授权主体下的广告主列表（duck-type FbClient.get_ad_accounts，fb_tokens 分发器
        reassociate 补候选池链接用；行含 advertiser_id/name）。
        oauth2/advertiser/get 需要 app_id：实例未带则 TT_APP_ID 环境变量兜底
        （凭证行自身有 app_id，构造方传 TtClient(token, app_id=cred.app_id) 更稳）。"""
        app_id = self.app_id or (os.environ.get("TT_APP_ID") or "").strip()
        if not app_id:
            raise TtApiError(
                "invalid_param",
                "get_ad_accounts 需要 app_id（构造 TtClient 时传入，或设 TT_APP_ID 环境变量）", {}, 0)
        return TtClient.get_authorized_advertisers(self.token, app_id)

    # ── 写操作 ──

    _OPT_STATUS = {"ACTIVE": "ENABLE", "PAUSED": "DISABLE", "ARCHIVED": "DELETE"}

    def update_status(self, node_id: str, status: str, node_type: str = "ad",
                      advertiser_id: str = "") -> dict:
        """改节点状态（ENABLE/DISABLE/DELETE；FB 风格 ACTIVE/PAUSED 自动映射）。"""
        opt = self._OPT_STATUS.get((status or "").upper(), (status or "").upper())
        ids_key = {"campaign": "campaign_ids", "adgroup": "adgroup_ids",
                   "ad": "ad_ids"}.get(node_type, "ad_ids")
        try:
            adv = int(advertiser_id)
        except (TypeError, ValueError):
            adv = advertiser_id
        return self.post(f"{node_type}/status/update/", {
            "advertiser_id": [adv],
            ids_key: [str(node_id)],
            "opt_status": opt,
        })

    def pause_ad(self, advertiser_id: str, ad_id: str) -> dict:
        """暂停单条广告（止损用，TT=opt_status DISABLE）。"""
        return self.update_status(ad_id, "PAUSED", "ad", advertiser_id)

    def get_node(self, node_id: str, node_type: str = "ad",
                 advertiser_id: str = "", fields=None) -> dict:
        """按 ID 拉单条节点详情（campaign/adgroup/ad 通用；TT 需带 advertiser_id 维度）。"""
        if not advertiser_id:
            raise TtApiError("invalid_param", "TT get_node 需要 advertiser_id", {}, 0)
        path = {"campaign": "campaign/get/", "adgroup": "adgroup/get/",
                "ad": "ad/get/"}.get(node_type, "ad/get/")
        params: dict[str, Any] = {
            "advertiser_id": advertiser_id,
            "filtering": json.dumps({"ids": [str(node_id)]}),
        }
        if fields:
            params["fields"] = json.dumps(fields)
        items = self.get_paged(path, params)
        return items[0] if items else {}
