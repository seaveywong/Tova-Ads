"""统一 TikTok Business API 客户端（所有 TT 调用唯一入口）。

功能：自计数限流（无官方 RPM 数字/响应头，滑动窗 + 429 指数退避封路）、
错误翻译、token 过期请求前自动刷新（双保险，cron 为主）、分页拉取。

认证风格与 FB 不同：access_token 走 query 参数（TK 风格）；
OAuth 端点（access_token/refresh_token/advertiser/get）用 app_id + secret/refresh_token。

方法面与 FbClient 对齐（get_campaigns/get_adsets/get_ads/get_active_ads/
get_ad_insights/pause_ad/get_node/update_status/update_budget/rename_node/delete_node），
供巡检按平台分发复用；参数结构与 FB 不同（advertiser_id 维度 + filtering JSON），sandbox 实测后再校准。

TT→FB 形状归一映射（tt_to_fb_campaign/adset/ad）：TT 实体 → FB 字段形状（键名/状态/
预算单位），ads_cache 同构存储，广告管理器展示层零平台分支。

P3 增补（部署链路）：create_campaign/create_adgroup/create_ad（建广告三件套，
payload 由 core/tt_ad_builder.py 构造）+ upload_ad_image/upload_ad_video
（素材传广告主文件库拿 file_id，视频小文件单发/大文件分块）。
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

# 视频上传（P3）：≤单发阈值整文件 multipart 直传；超过走分块 Init/Upload/Finish
VIDEO_SINGLE_SHOT_MAX = 20 * 1024 * 1024   # 20MB 以下单发（广告素材 MP4 绝大多数在此内）
VIDEO_SLICE_SIZE = 10 * 1024 * 1024        # 分块大小 10MB


def _pick_file_id(data: dict) -> str:
    """从上传/分块响应宽容取 file_id（video_id/file_id/列表首元素键名随版本漂移）。"""
    if not isinstance(data, dict):
        return ""
    for k in ("video_id", "file_id", "image_id"):
        v = data.get(k)
        if v:
            return str(v)
    for k in ("videos", "list", "materials"):
        v = data.get(k)
        if isinstance(v, (list, tuple)) and v and isinstance(v[0], dict):
            vid = v[0].get("video_id") or v[0].get("id") or v[0].get("file_id")
            if vid:
                return str(vid)
    return ""

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


# ── TT→FB 形状归一（ads_cache 同构存储：TT 实体 → FB 字段形状，管理器展示层零平台分支）──
# sandbox 校准点：各 get 端点默认字段集与枚举值以 v1.3 实测为准（objective_type /
# optimization_goal 枚举随版本扩充），映射按官方文档 v1.3 编写，实测差异只需改这一段。

# opt_status（用户配置态）→ FB status/configured_status。TT DELETE=FB ARCHIVED（软删语义）
TT_OPT_TO_FB = {"ENABLE": "ACTIVE", "DISABLE": "PAUSED", "DELETE": "ARCHIVED"}
# status（投放状态，TT 的 effective 语义：含预算耗尽/完成等阻塞态）→ FB effective_status。
# 未收录枚举（STATUS_BUDGET_EXCEED/STATUS_COMPLETE…）原样透传——前端 TT registry 兜底翻译
TT_STATUS_TO_FB = {"STATUS_ENABLE": "ACTIVE", "STATUS_DISABLE": "PAUSED", "STATUS_DELETE": "DELETED"}
# TT objective_type → FB objective（对齐前端 OBJ_MAP 展示；语义近似映射）
TT_OBJECTIVE_TO_FB = {
    "TRAFFIC": "LINK_CLICKS", "CONVERSIONS": "CONVERSIONS", "AWARENESS": "BRAND_AWARENESS",
    "REACH": "REACH", "ENGAGEMENT": "OUTCOME_ENGAGEMENT", "LEAD_GENERATION": "OUTCOME_LEAD_GENERATION",
    "VIDEO_VIEWS": "VIDEO_VIEWS", "APP_PROMOTION": "APP_PROMOTION",
    "CATALOG_SALES": "CATALOG_SALES", "LIVE_PROMOTION": "LIVE_PROMOTION",
}
# TT optimization_goal → FB optimization_goal（对齐前端 OPT_MAP 展示）
TT_OPTGOAL_TO_FB = {
    "CLICK": "LINK_CLICKS", "CONVERSION": "OFFSITE_CONVERSIONS", "IMPRESSION": "IMPRESSIONS",
    "REACH": "REACH", "VIDEO_VIEW": "VIDEO_VIEWS", "LEAD": "LEAD_GENERATION",
}

def tt_budget_to_fb_minor(budget, currency: str) -> str:
    """TT 预算（整本币，20=20 美元/20 日元）→ FB minor units 字符串（'2000'=$20）。
    存进 ads_cache 后展示层走 FB 同一 from_minor_units 逆换算路径；非法值返 ''。"""
    from .ad_ops import ZERO_DECIMAL as _TT_ZERO_DECIMAL   # 延迟导入：core/ad_ops 反向 import 本模块（TtApiError），模块级会成环
    try:
        v = int(budget)
    except (TypeError, ValueError):
        return ""
    factor = 1 if (currency or "USD").upper() in _TT_ZERO_DECIMAL else 100
    return str(v * factor)


def _tt_status_fields(o: dict) -> dict:
    """opt_status/status/show_status → FB status/configured_status/effective_status。

    effective 取 TT status（投放状态，含阻塞态）优先、opt 兜底；show_status=SHOW_STATUS_NO
    （审核拒）为最高可见级——盖成 DISAPPROVED，对齐 FB 拒审红标 + ⚠ 拒审原因入口。
    原生字段全部保留在行上（guard 兜底读 ad_id/status 原生键不受影响）。
    """
    opt = str(o.get("opt_status") or "").upper()
    raw = str(o.get("status") or "").upper()
    configured = TT_OPT_TO_FB.get(opt, opt)
    eff = TT_STATUS_TO_FB.get(raw, raw) or configured  # 未知投放态透传；status 缺失回落 opt
    if str(o.get("show_status") or "").upper() == "SHOW_STATUS_NO":
        eff = "DISAPPROVED"
    return {"status": configured, "configured_status": configured, "effective_status": eff}


def _tt_budget_fields(o: dict, currency: str) -> dict:
    """budget_mode/budget（整本币）→ FB daily_budget/lifetime_budget（minor units）。
    BUDGET_MODE_INFINITE（不限）不产出预算字段——同 FB 无预算对象，前端显示层级占位且不可编辑。"""
    out: dict = {}
    mode = str(o.get("budget_mode") or "").upper()
    if mode == "BUDGET_MODE_DAY":
        out["daily_budget"] = tt_budget_to_fb_minor(o.get("budget"), currency)
    elif mode == "BUDGET_MODE_TOTAL":
        out["lifetime_budget"] = tt_budget_to_fb_minor(o.get("budget"), currency)
    return out


def tt_to_fb_campaign(c: dict, currency: str = "USD") -> dict:
    """TT campaign/get 行 → FB campaign 形状（键名/状态/预算单位三归一）。"""
    out = dict(c)
    out["id"] = str(c.get("campaign_id") or "")
    out["name"] = c.get("campaign_name") or ""
    out["objective"] = TT_OBJECTIVE_TO_FB.get(str(c.get("objective_type") or "").upper(),
                                              c.get("objective_type") or "")
    out.update(_tt_status_fields(c))
    out.update(_tt_budget_fields(c, currency))
    return out


def tt_to_fb_adset(a: dict, currency: str = "USD") -> dict:
    """TT adgroup/get 行 → FB adset 形状。"""
    out = dict(a)
    out["id"] = str(a.get("adgroup_id") or "")
    out["name"] = a.get("adgroup_name") or ""
    out["campaign_id"] = str(a.get("campaign_id") or "")
    out["optimization_goal"] = TT_OPTGOAL_TO_FB.get(str(a.get("optimization_goal") or "").upper(),
                                                    a.get("optimization_goal") or "")
    out.update(_tt_status_fields(a))
    out.update(_tt_budget_fields(a, currency))
    return out


def tt_to_fb_ad(a: dict, currency: str = "USD") -> dict:
    """TT ad/get 行 → FB ad 形状（create_time 空格分隔 → ISO T；无缩略图/主页帖，creative 不映射）。"""
    out = dict(a)
    out["id"] = str(a.get("ad_id") or "")
    out["name"] = a.get("ad_name") or ""
    out["adset_id"] = str(a.get("adgroup_id") or "")
    out["campaign_id"] = str(a.get("campaign_id") or "")
    ct = str(a.get("create_time") or "")
    if ct:
        out["created_time"] = ct.replace(" ", "T")
    out.update(_tt_status_fields(a))
    return out


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

    def update_budget(self, node_id: str, budget: int, advertiser_id: str = "",
                      budget_mode: str = "BUDGET_MODE_DAY") -> dict:
        """改广告组预算（adgroup/update/）。budget=整本币（无 ×100，与 FB minor units 不同）；
        budget_mode 需与目标类型一致（DAY/TOTAL，不限→改设任一类型时一并传）。
        sandbox 校准点：campaign 层预算能否走 campaign/update/ 未证实——现仅 adgroup 层。"""
        try:
            adv = int(advertiser_id)
        except (TypeError, ValueError):
            adv = advertiser_id
        return self.post("adgroup/update/", {
            "advertiser_id": adv,
            "adgroup_ids": [str(node_id)],
            "budget": int(budget),
            "budget_mode": budget_mode,
        })

    def rename_node(self, node_id: str, name: str, node_type: str = "ad",
                    advertiser_id: str = "") -> dict:
        """改名（campaign/adgroup/ad 通用；TT 各层端点与 name 字段名不同：campaign_name 等）。"""
        path, ids_key, name_key = {
            "campaign": ("campaign/update/", "campaign_ids", "campaign_name"),
            "adgroup": ("adgroup/update/", "adgroup_ids", "adgroup_name"),
            "ad": ("ad/update/", "ad_ids", "ad_name"),
        }.get(node_type, ("ad/update/", "ad_ids", "ad_name"))
        try:
            adv = int(advertiser_id)
        except (TypeError, ValueError):
            adv = advertiser_id
        return self.post(path, {"advertiser_id": adv, ids_key: [str(node_id)], name_key: name})

    def delete_node(self, node_id: str, node_type: str = "ad", advertiser_id: str = "") -> dict:
        """删节点。TT 无 FB 式 DELETE /{id} 硬删端点——opt_status=DELETE 即 TT 的删除语义
        （sandbox 校准点：若 /ad/delete/ 等硬删端点实测可用，在此切换即可，签名不变）。"""
        return self.update_status(node_id, "ARCHIVED", node_type, advertiser_id)

    # ── 广告创建三件套（P3 部署链路；payload 由 core/tt_ad_builder.py 构造）──

    def create_campaign(self, advertiser_id: str, payload: dict) -> dict:
        """campaign/create/ → {"campaign_id": ...}。payload 不含 advertiser_id（此处合并）。"""
        data = self._post_create("campaign/create/", advertiser_id, payload, "campaign_ids")
        return {"campaign_id": data[0]}

    def create_adgroup(self, advertiser_id: str, payload: dict) -> dict:
        """adgroup/create/ → {"adgroup_id": ...}。"""
        data = self._post_create("adgroup/create/", advertiser_id, payload, "adgroup_ids")
        return {"adgroup_id": data[0]}

    def create_ad(self, advertiser_id: str, payload: dict) -> dict:
        """ad/create/ → {"ad_id": ...}。广告出生暂停由 payload.operation_status=DISABLE 保证。"""
        data = self._post_create("ad/create/", advertiser_id, payload, "ad_ids")
        return {"ad_id": data[0]}

    def _post_create(self, path: str, advertiser_id: str, payload: dict, ids_key: str) -> list[str]:
        """创建端点公共：合并 advertiser_id（int）→ POST → 取 data.{ids_key}[0]。"""
        try:
            adv = int(advertiser_id)
        except (TypeError, ValueError):
            adv = advertiser_id
        body = dict(payload or {})
        body["advertiser_id"] = adv
        result = self.post(path, body)
        data = result.get("data") or {}
        # 创建类端点返回 id 列表（campaign_ids/adgroup_ids/ad_ids）；个别版本返回单值
        ids = data.get(ids_key)
        if isinstance(ids, (list, tuple)):
            ids = [str(i) for i in ids if i]
        elif ids:
            ids = [str(ids)]
        if not ids:
            raise TtApiError("no_id", f"TT {path} 未返回 {ids_key}（响应：{str(result)[:200]}）")
        return ids

    # ── 素材上传（file_id 按 advertiser 隔离，不能跨账户复用；部署侧 ensure_tt_file_id_for_account 缓存）──
    # sandbox 校准点：multipart 字段名/响应键以官方 v1.3 文档实测为准（image_id/file_id、
    # 分块协议 upload_id/chunk_number）。解析端已对常见键名容错，实测不符只需改这里。

    UPLOAD_TIMEOUT = 300  # 视频上传远大于普通请求

    def _upload_multipart(self, path: str, data: dict, files: dict) -> dict:
        """multipart POST（_raw_call 只支持 JSON body，上传走这里；限流/错误分类同款）。"""
        key = f"POST {path}"
        _throttle_enter(key)
        params = {"access_token": self.token}
        try:
            resp = httpx.post(TT_BASE + path, params=params, data=data, files=files,
                              timeout=self.UPLOAD_TIMEOUT)
        except httpx.RequestError as e:
            raise TtApiError("network", f"网络错误：{e}", {}, 0)
        try:
            result = resp.json()
        except Exception:
            raise TtApiError("network",
                             f"响应非 JSON（HTTP {resp.status_code}）：{resp.text[:120]}", {}, resp.status_code)
        if _is_rate_limited(resp.status_code, result):
            throttle_strike(key)
            raise TtApiError("rate_limited", TT_ERROR_MAP[42900][1], result, resp.status_code)
        if result.get("code", 0) != 0:
            cat, friendly = classify_tt_error(result.get("code", 0), result.get("message", ""))
            logger.warning(f"[TT] POST {path} → {cat}: {friendly}")
            raise TtApiError(cat, friendly, result, resp.status_code)
        _throttle_success(key)
        return result.get("data") or {}

    def upload_ad_image(self, advertiser_id: str, image_bytes: bytes,
                        filename: str = "image.jpg") -> dict:
        """上传图片到广告主文件库 → {"file_id": image_id}。

        file/image/ad/（广告素材库）；返回 image_id 即创意用的 file_id（另有 post_id 可选）。
        """
        data = self._upload_multipart("file/image/ad/", {
            "advertiser_id": str(advertiser_id),
        }, {"image_file": (filename or "image.jpg", image_bytes, "image/jpeg")})
        file_id = _pick_file_id(data)
        if not file_id:
            raise TtApiError("no_id", f"TT 上传图片未返回 image_id（响应：{str(data)[:200]}）")
        return {"file_id": file_id}

    def upload_ad_video(self, advertiser_id: str, video_bytes: bytes,
                        filename: str = "video.mp4") -> dict:
        """上传视频到广告主文件库 → {"file_id": video_id, "mode": single|chunk}。

        小文件单发（file/ad/video/upload/ multipart 直传）；大文件分块 Init → Upload(逐块) →
        Finish（末块即完成，分块协议字段以官方文档/sandbox 实测为准——Init 失败自动回落单发）。
        视频转码异步：拿到 video_id 即可用于建广告（TT 允许 PROCESSING 状态引用，审核时校验）。
        """
        adv = str(advertiser_id)
        if len(video_bytes) <= VIDEO_SINGLE_SHOT_MAX:
            return self._upload_video_single(adv, video_bytes, filename)
        try:
            return self._upload_video_chunked(adv, video_bytes, filename)
        except TtApiError as e:
            if e.category in ("invalid_param", "not_found"):
                logger.warning(f"[TT] 分块上传不可用（{e.friendly}），回落整文件单发")
                return self._upload_video_single(adv, video_bytes, filename)
            raise

    def _upload_video_single(self, adv: str, video_bytes: bytes, filename: str) -> dict:
        data = self._upload_multipart("file/ad/video/upload/", {
            "advertiser_id": adv,
        }, {"video_file": (filename or "video.mp4", video_bytes, "video/mp4")})
        vid = _pick_file_id(data)
        if not vid:
            raise TtApiError("no_id", f"TT 上传视频未返回 video_id（响应：{str(data)[:200]}）")
        return {"file_id": vid, "mode": "single"}

    def _upload_video_chunked(self, adv: str, video_bytes: bytes, filename: str) -> dict:
        """分块：Init（JSON，拿 upload_id）→ 逐块 multipart → 末块完成拿 video_id。"""
        total = len(video_bytes)
        chunk_num = (total + VIDEO_SLICE_SIZE - 1) // VIDEO_SLICE_SIZE
        init = self.post("file/ad/video/upload/", {
            "advertiser_id": adv,
            "upload_type": "UPLOAD_TYPE_CHUNK",
            "file_name": filename or "video.mp4",
            "file_size": total,
            "slice_size": VIDEO_SLICE_SIZE,
            "chunk_num": chunk_num,
        }).get("data") or {}
        upload_id = init.get("upload_id") or init.get("uploadid") or ""
        if not upload_id:
            raise TtApiError("invalid_param",
                             f"TT 分块上传 Init 未返回 upload_id（响应：{str(init)[:200]}）")
        for i in range(chunk_num):
            chunk = video_bytes[i * VIDEO_SLICE_SIZE:(i + 1) * VIDEO_SLICE_SIZE]
            data = self._upload_multipart("file/ad/video/upload/", {
                "advertiser_id": adv,
                "upload_type": "UPLOAD_TYPE_CHUNK",
                "upload_id": upload_id,
                "chunk_number": str(i + 1),   # 1 基序号
            }, {"video_file": (filename or "video.mp4", chunk, "video/mp4")})
            vid = _pick_file_id(data)
            if vid and i + 1 == chunk_num:
                return {"file_id": vid, "mode": "chunk"}
        raise TtApiError("no_id", "TT 分块上传完成但未返回 video_id（视频转码中，稍后重试或查看文件库）")
