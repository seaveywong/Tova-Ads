"""统一 FB Graph API 客户端（总则4：所有 FB 调用唯一入口）。

功能：重试、节流退避、错误翻译（classify_fb_error，照搬 1.0 execution_safety + 扩展）。
所有 FB 读写都经此层，业务模块不直接调 httpx→FB。
"""
import time
import json
import logging
import httpx
from typing import Any

logger = logging.getLogger("toveads.fb")

GRAPH_VERSION = "v25.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"
TIMEOUT = 30
MAX_RETRIES = 3

# ── FB 错误码 → (category, 人话)  SSOT：照搬 1.0 classify + 2.0 实测扩展 ──
# 见 Mira_2.0_docs/02_附录_错误码字典.md（单一来源；新增码请同步更新该文档）
FB_ERROR_MAP = {
    # 账户/权限
    33:       ("account_write",  "广告账户无写权限，请到 BM 授权操作号"),
    1487202:  ("page_ads",       "主页缺少广告权限，请到 BM 给主页授权"),
    1487067:  ("budget_limit",   "预算超限"),
    200:      ("permissions",    "权限不足"),
    10:       ("permission_denied", "权限被拒绝"),
    190:      ("token_expired",  "Token 已过期或失效，请重新绑定"),
    # 竞价（1.0 三硬规矩对应）
    1815858:  ("bid_conflict",   "竞价策略与出价冲突（LOWEST_COST 不带 bid）"),
    2490487:  ("bid_required",   "此广告目标需明确竞价策略"),
    # 合规/认证
    2859002:  ("cert_required",  "账户需完成 Meta 非歧视政策认证"),
    1815089:  ("leadgen_tos",    "主页尚未接受 FB 潜在客户服务条款（Lead Generation Terms），请到主页设置接受"),
    # 受监管地区（2.0 实测 2026-07-06）
    2490408:  ("regulated_opt",  "受监管地区不支持该优化目标（如 TW 不支持 PAGE_LIKES/POST_ENGAGEMENT/VIDEO_VIEWS/LEAD_GENERATION）"),
    3858498:  ("regulated_missing", "需要区域性受监管类别值（TW/SG 受监管广告需 verified_identity_id，请在认证主页库录入）"),
    3858495:  ("regulated_id",   "受监管身份 ID 无效（regional_regulation_identities 必须是数字 verified_identity_id）"),
    # 受众
    1870227:  ("audience",       "受众定向字段不被接受（建议 targeting_automation.advantage_audience=0）"),
    2446395:  ("audience_size",  "受众太窄或字段无效"),
    # 滥用/风控（Lead Form 重试安全版）
    368:      ("abuse",          "内容被举报滥用或触发风控（已尝试安全版重试）"),
    1346003:  ("abuse",          "内容被举报滥用或触发风控（已尝试安全版重试）"),
    # 开发者模式
    1885183:  ("dev_mode",       "Meta App 处于开发者模式，所有写操作失败——请切到 Live"),
    # 通用
    100:      ("invalid_param",  "请求参数错误"),
    4:        ("rate_limited",   "请求过于频繁，请稍后重试"),
    17:       ("rate_limited",   "请求过于频繁，请稍后重试"),
    32:       ("rate_limited",   "达到 API 调用上限，请稍后重试"),
}


def classify_fb_error(error_data: dict) -> tuple[str, str]:
    """FB 错误 JSON → (category, 中文人话)。"""
    code = error_data.get("code", 0)
    sub = error_data.get("error_subcode", 0)
    msg = error_data.get("message", "")

    if sub in FB_ERROR_MAP:
        return FB_ERROR_MAP[sub]
    if code in FB_ERROR_MAP:
        # code 100 特例：Missing Permission = 令牌缺权限（如 /me/businesses 需
        # business_management），不是参数问题——给可操作的重新授权指引
        if code == 100 and "missing permission" in msg.lower():
            return ("permissions", "令牌缺少所需权限（如 business_management），请删除令牌后重新授权勾选")
        return FB_ERROR_MAP[code]
    if "non-discrimination" in msg.lower():
        return FB_ERROR_MAP[2859002]
    return ("generic", f"Facebook 返回错误（code {code}）：{msg[:120]}")


class FbApiError(Exception):
    """FB API 调用失败 —— 带 category + friendly + raw，供错误翻译层用（doc 05）。"""

    def __init__(self, category: str, friendly: str, raw: dict = None, status: int = 0):
        self.category = category
        self.friendly = friendly
        self.raw = raw or {}
        self.status = status
        super().__init__(friendly)


def _safe_ascii_name(filename: str, default_ext: str) -> str:
    """multipart 文件名 ASCII 化：非 ASCII 名（如中文）会让 httpx 编码 header 失败，
    保留扩展名换成通用名（FB 对文件名本身无要求，只认内容）。"""
    name = filename or ""
    try:
        name.encode("ascii")
        return name or ("file" + default_ext)
    except UnicodeEncodeError:
        ext = name[name.rfind("."):] if "." in name else default_ext
        return "file" + (ext if ext.startswith(".") else default_ext)


class FbClient:
    """统一 FB Graph API 客户端。所有 FB 操作经此。"""

    def __init__(self, access_token: str):
        self.token = access_token

    # ── 底层请求（含重试 + 错误翻译）──
    def _request(self, method: str, path: str, params: dict = None, data: dict = None) -> dict:
        url = f"{GRAPH_BASE}/{path}"
        params = dict(params or {})
        params["access_token"] = self.token

        for attempt in range(MAX_RETRIES):
            try:
                if method == "POST" and data:
                    import json as _json
                    form = {k: _json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                            for k, v in data.items()}
                    resp = httpx.post(url, params=params, data=form, timeout=TIMEOUT)
                elif method == "DELETE":
                    resp = httpx.delete(url, params=params, timeout=TIMEOUT)
                else:
                    resp = httpx.get(url, params=params, timeout=TIMEOUT)
                result = resp.json()
                if "error" in result:
                    err = result["error"]
                    cat, friendly = classify_fb_error(err)
                    logger.warning(f"[FB] {method} {path} → {cat}: {friendly}")
                    raise FbApiError(cat, friendly, err, resp.status_code)
                return result
            except FbApiError:
                raise
            except httpx.RequestError as e:
                # 幂等保护：POST/DELETE 只对"确认未到达"的连接错误重试；
                # ReadTimeout/WriteTimeout 时服务端可能已执行（重放=重复建广告/帖/花钱）
                _retryable = isinstance(e, (httpx.ConnectError, httpx.ConnectTimeout))
                if method in ("POST", "DELETE") and not _retryable:
                    raise FbApiError("network", f"网络超时（结果未知，不重试防重复创建）：{e}", {}, 0)
                if attempt < MAX_RETRIES - 1:
                    wait = 2 ** attempt
                    logger.info(f"[FB] 网络错误，{wait}s 后重试: {e}")
                    time.sleep(wait)
                    continue
                raise FbApiError("network", f"网络错误：{e}", {}, 0)
            except Exception as e:
                raise FbApiError("unknown", f"未知错误：{e}", {}, 0)

    def get(self, path: str, params: dict = None) -> dict:
        return self._request("GET", path, params)

    def get_paged(self, path: str, params: dict = None, limit: int = 200,
                  max_total: int = 5000) -> list[dict]:
        """FB 分页拉取：自动跟随 paging.cursors.after 直到无更多数据或达 max_total。

        照搬 1.0 _fb_get_all_pages（kpi_resolver.py L411）——单 token 下 >200 账户/广告
        不翻页会漏。limit 是每页大小（FB 默认上限 200/100 取决于端点）。
        """
        from urllib.parse import urlparse, parse_qs
        base = dict(params or {})
        if "limit" not in base:
            base["limit"] = limit  # 调用方未指定才用默认；部分端点(published_posts/posts/feed)FB 上限 100，默认 200 会 #100 报错
        all_items: list[dict] = []
        after = None
        while len(all_items) < max_total:
            p = dict(base)
            if after:
                p["after"] = after
            data = self._request("GET", path, p)
            items = data.get("data", []) or []
            all_items.extend(items)
            paging = data.get("paging", {}) or {}
            cursors = paging.get("cursors", {}) or {}
            after = cursors.get("after") or paging.get("next")
            if isinstance(after, str) and after.startswith("http"):
                after = parse_qs(urlparse(after).query).get("after", [None])[0]
            if not after or len(items) < limit:
                break
        return all_items

    def post(self, path: str, data: dict = None) -> dict:
        return self._request("POST", path, data=data)

    # ── 常用封装 ──
    def debug_token(self) -> dict:
        """校验 token + 拿类型/有效期/scopes。"""
        return self.get("debug_token", {"input_token": self.token})

    def me(self) -> dict:
        """当前 token 对应的用户身份。"""
        return self.get("me", {"fields": "id,name"})

    def get_ad_accounts(self, light: bool = False) -> list[dict]:
        """拉取可管理的广告账户列表（全量分页，单 token >200 账户不漏）。

        light=True 用轻字段（无 balance/spend_cap/amount_spent）——这些是服务端
        计算字段，大代理 token（3k+ 账户）带上它们单次全量拉取从 ~30s 涨到超时；
        载入列表/导入判定只需要存在性+名称，余额等由导入后的刷新补。
        """
        fields = ("account_id,account_status,name,currency,timezone_name" if light else
                  "account_id,account_status,name,currency,timezone_name,balance,spend_cap,amount_spent")
        return self.get_paged("me/adaccounts", {"fields": fields})

    def batch_get(self, relative_urls: list[str]) -> list[dict | None]:
        """FB batch API：一次 POST 打包 ≤50 个 GET，返回逐项解析的 body（失败项为 None）。

        用于「每 BM 查一次」类聚合（如 business_users 角色）——串行 N 次会拖垮端点。
        """
        import json as _json
        out: list[dict | None] = []
        for i in range(0, len(relative_urls), 50):
            chunk = relative_urls[i:i + 50]
            batch = [{"method": "GET", "relative_url": u} for u in chunk]
            resp = httpx.post(GRAPH_BASE, params={
                "access_token": self.token, "batch": _json.dumps(batch),
                "include_headers": "false"}, timeout=60)
            for item in resp.json():
                try:
                    out.append(_json.loads(item.get("body") or "{}"))
                except Exception:
                    out.append(None)
        return out

    def get_pages(self) -> list[dict]:
        """拉取可管理的主页列表（全量分页）。"""
        return self.get_paged("me/accounts", {
            "fields": "id,name,category,can_post,fan_count,tasks",
        })

    def get_page_access_token(self, page_id: str) -> str:
        """取指定主页的 page access token（用当前 user token 派生：me/accounts?fields=id,access_token）。
        建主页帖(/{page}/photos|feed) 需 page token（user token 不行，code200）。无→空串。"""
        for p in self.get_paged("me/accounts", {"fields": "id,access_token"}):
            if str(p.get("id")) == str(page_id):
                return p.get("access_token") or ""
        return ""

    def get_pixels(self, act_id: str) -> list[dict]:
        """拉取广告账户下的像素（全量分页）。"""
        return self.get_paged(f"act_{act_id}/adspixels", {
            "fields": "id,name,can_archive",
        })

    def get_businesses(self) -> list[dict]:
        """拉取可管理的 BM（business）列表 + permitted_tasks（推导 基本/完全 权限）。"""
        return self.get_paged("me/businesses", {
            "fields": "id,name,permitted_tasks",
        })

    def get_insights(self, act_id: str, date_preset: str = "today",
                     date_from: str = "", date_to: str = "") -> dict:
        """拉取账户级 insights（消耗/展示/点击/转化）。doc 02 看板用。

        支持两种时间模式：
        - date_preset: today/yesterday/last_7d/last_30d（FB 预设）
        - date_from + date_to: 自定义日期范围（YYYY-MM-DD，time_range 模式）
        """
        params = {
            "fields": "spend,impressions,clicks,ctr,cpc,reach,frequency,cpm,"
                      "actions,action_values,conversion_values,purchase_roas,"
                      "date_start,date_stop",
            "level": "account",
        }
        if date_from and date_to:
            params["time_range"] = json.dumps({"since": date_from, "until": date_to})
        else:
            params["date_preset"] = date_preset
        data = self.get(f"act_{act_id}/insights", params)
        if data.get("data"):
            return data["data"][0]
        return {"spend": "0", "impressions": "0", "clicks": "0"}

    def get_adset_insights(self, act_id: str, date_preset: str = "today") -> list[dict]:
        """拉取广告组级 insights（预算进度告警用）。返 [{adset_id, spend}, ...]。"""
        params = {
            "fields": "adset_id,spend,impressions,clicks",
            "level": "adset",
            "date_preset": date_preset,
            "limit": 200,
        }
        return self.get_paged(f"act_{act_id}/insights", params, limit=200)

    def get_ad_insights(self, act_id: str, date_preset: str = "today", limit: int = 200,
                       only_active: bool = True, since: str = "", until: str = "") -> list[dict]:
        """拉取广告级 insights（按广告拆解，全量分页）。

        优先用 time_range(since/until 账户本地日，精确) 避免 FB date_preset(today) 跨时区累积失真；
        不传 since/until 则 fallback date_preset。
        ⚠️ Graph v25 起 insights 不支持 effective_status 字段（code100 整体报错）——
        ACTIVE 过滤改从 /ads 结构接口拿 id 集合再过滤 insights 行。
        """
        params = {
            "fields": "ad_id,ad_name,campaign_id,campaign_name,adset_id,adset_name,"
                      "spend,impressions,clicks,ctr,cpc,reach,frequency,"
                      "actions,purchase_roas",
            "level": "ad",
        }
        if since and until:
            params["time_range"] = '{"since":"%s","until":"%s"}' % (since, until)
        else:
            params["date_preset"] = date_preset
        all_ads = self.get_paged(f"act_{act_id}/insights", params, limit=limit)
        if only_active:
            # 只保留 ACTIVE（含学习中的——学习中但 ACTIVE = 在花钱，用户明确要纳入）。
            # v25 insights 无 effective_status——从 /ads 结构拿状态映射：既做过滤，也
            # 回填到行上（下游 _ad_is_active/快照/管理器兼容旧字段读取）
            status_map = {str(a.get("id", "")).split(".")[-1]: a.get("effective_status", "")
                          for a in self.get_ads(act_id)}
            out = []
            for a in all_ads:
                _sid = str(a.get("ad_id", "")).split(".")[-1]
                if _sid in status_map:
                    a["effective_status"] = status_map[_sid]
                    if status_map[_sid] == "ACTIVE":
                        out.append(a)
            return out
        return all_ads

    def get_adsets(self, act_id: str, effective_status: str | None = '["ACTIVE"]',
                   fields: str | None = None) -> list[dict]:
        """拉广告组（全量分页）。effective_status=None 拉全状态(管理器用)，默认仅 ACTIVE(巡检用)。"""
        params = {"fields": fields or (
            "id,name,daily_budget,lifetime_budget,effective_status,configured_status,"
            "campaign_id,objective,optimization_goal,bid_strategy,promoted_object,destination_type")}
        if effective_status:
            params["effective_status"] = effective_status
        return self.get_paged(f"act_{act_id}/adsets", params)

    def get_campaigns(self, act_id: str, effective_status: str | None = None,
                      fields: str | None = None) -> list[dict]:
        """拉广告系列（全量分页，管理器用；默认全状态）。"""
        params = {"fields": fields or (
            "id,name,objective,status,effective_status,configured_status,daily_budget,"
            "lifetime_budget,bid_strategy,buying_type,budget_remaining")}
        if effective_status:
            params["effective_status"] = effective_status
        return self.get_paged(f"act_{act_id}/campaigns", params)

    def get_node(self, node_id: str, fields: str) -> dict:
        """按 ID 拉单条节点详情（ad/adset/campaign 通用）。"""
        return self.get(node_id, {"fields": fields})

    def update_status(self, node_id: str, status: str) -> dict:
        """改节点状态（ACTIVE/PAUSED/ARCHIVED，通用 ad/adset/campaign）。"""
        return self.post(node_id, {"status": status})

    def update_budget(self, node_id: str, daily_budget: str = None, lifetime_budget: str = None) -> dict:
        """改日预算/总预算（minor units 字符串，如 '5000' = $50）。"""
        data = {}
        if daily_budget:
            data["daily_budget"] = daily_budget
        if lifetime_budget:
            data["lifetime_budget"] = lifetime_budget
        return self.post(node_id, data)

    def rename_node(self, node_id: str, name: str) -> dict:
        """改名。"""
        return self.post(node_id, {"name": name})

    def get_leads(self, form_id: str, limit: int = 100) -> list[dict]:
        """FB leadgen：取 Instant Form 潜客数据。GET /{form_id}/leads（leads_retrieval scope）。"""
        return self.get_paged(
            f"{form_id}/leads",
            params={"fields": "id,created_time,field_data,ad_id,form_id"},
            limit=limit,
        )

    def subscribe_page_webhook(self, page_id: str, page_token: str, fields: list[str] = None) -> dict:
        """订阅主页 webhook（pages_manage_metadata scope）。POST /{page_id}/subscribed_apps + subscribed_fields。

        需 page access token（user token 会 code200）。FB 单次 POST 即订阅 + 指定 fields（覆盖式）。
        """
        desired = fields or ["leadgen", "feed", "messages"]
        page_fb = FbClient(page_token)
        page_fb.post(f"{page_id}/subscribed_apps", {"subscribed_fields": ",".join(desired)})
        return {"page_id": page_id, "subscribed_fields": desired}

    def delete_node(self, node_id: str) -> dict:
        """硬删节点（DELETE /{id}）。通常用 update_status(ARCHIVED) 软删更安全。"""
        return self._request("DELETE", node_id)

    def duplicate_node(self, node_id: str, count: int = 1, new_name: str = "",
                       deep_copy: bool = True) -> dict:
        """复制节点（POST /{id}/copies）。"""
        data = {"number_of_copies": str(count)}
        if new_name:
            data["rename_options"] = {"rename_strategy": "DEEP_RENAME", "new_name": new_name}
        if deep_copy:
            data["status_option"] = "PAUSED"
        return self.post(f"{node_id}/copies", data)

    def pause_ad(self, ad_id: str) -> dict:
        """暂停单条广告（doc 03 升级暂停用）。"""
        return self.post(ad_id, {"status": "PAUSED"})

    def upload_ad_image(self, act_id: str, image_bytes: bytes, filename: str = "image.jpg") -> dict:
        """上传图片到 FB 广告账户 → 返 {hash, url}（FB image_hash 供创意用）。"""
        url = f"{GRAPH_BASE}/act_{act_id}/adimages"
        safe = _safe_ascii_name(filename, ".jpg")
        resp = httpx.post(
            url,
            params={"access_token": self.token},
            files={safe: (safe, image_bytes, "image/jpeg")},
            timeout=120,
        )
        result = resp.json()
        if "error" in result:
            err = result["error"]
            cat, friendly = classify_fb_error(err)
            raise FbApiError(cat, friendly, err, resp.status_code)
        images = result.get("images", {})
        # FB 返回 {filename: {hash, account_id, url}}
        for k, v in images.items():
            return {"hash": v.get("hash", ""), "url": v.get("url", ""), "filename": k}
        return {"hash": "", "url": ""}

    def upload_video(self, act_id: str, video_bytes: bytes, filename: str = "video.mp4") -> dict:
        """上传视频到 FB 广告账户（POST /act_{id}/advideos，multipart source）→ 返 {id: video_id}。

        video_id 可直接用于创意 video_data.video_id（FB 转码异步排队，不阻塞建广告）。
        视频文件大（几十 MB）→ 超时 600s（图片是 120s）；不走 _request 的网络重试——
        上传非幂等，重试可能产生重复视频。
        """
        url = f"{GRAPH_BASE}/act_{act_id}/advideos"
        safe = _safe_ascii_name(filename, ".mp4")
        mime = "video/quicktime" if safe.lower().endswith((".mov", ".qt")) else "video/mp4"
        try:
            resp = httpx.post(
                url,
                params={"access_token": self.token},
                files={"source": (safe, video_bytes, mime)},
                timeout=600,
            )
        except httpx.RequestError as e:
            logger.warning(f"[FB] upload_video act_{act_id} network error: {e}")
            # 静态中文串：可被全局译表精确匹配；细节进日志不进用户可见错误
            raise FbApiError("network", "视频上传网络错误（视频文件大易超时，结果未知不自动重试，请稍后重试）", {}, 0)
        result = resp.json()
        if "error" in result:
            err = result["error"]
            cat, friendly = classify_fb_error(err)
            raise FbApiError(cat, friendly, err, resp.status_code)
        return {"id": result.get("id", "")}

    def get_ads(self, act_id: str, effective_status: str | None = '["ACTIVE"]',
                fields: str | None = None) -> list[dict]:
        """拉广告（全量分页）。effective_status=None 拉全状态(管理器)，默认仅 ACTIVE(巡检/哨兵)。"""
        params = {"fields": fields or (
            "id,name,status,effective_status,configured_status,adset_id,campaign_id,created_time,"
            "creative{id,effective_object_story_id,object_story_spec,thumbnail_url},review_feedback")}
        if effective_status:
            params["filtering"] = f'[{{"field":"effective_status","operator":"IN","value":{effective_status}}}]'
        return self.get_paged(f"act_{act_id}/ads", params)

    def get_active_ads(self, act_id: str) -> list[dict]:
        """拉 ACTIVE 广告（巡检/哨兵用，兼容旧调用）。"""
        return self.get_ads(act_id)

    def get_ad_creative_links(self, act_id: str) -> dict:
        """拉账户下广告的创意链接（子码自动绑定用）。返 {ad_id: link_url}（全量分页）。

        从 object_story_spec 提取 link_data.link 或 video_data.call_to_action.value.link。
        """
        data_list = self.get_paged(f"act_{act_id}/ads", {
            "fields": "id,creative{object_story_spec{link_data{link},video_data{call_to_action{value{link}}}}}",
        }, limit=200)
        out: dict[str, str] = {}
        for ad in data_list:
            ad_id = ad.get("id")
            spec = ((ad.get("creative") or {}).get("object_story_spec") or {})
            link = ((spec.get("link_data") or {}).get("link")
                    or (((spec.get("video_data") or {}).get("call_to_action") or {}).get("value") or {}).get("link"))
            if link:
                out[ad_id] = link
        return out

    def search_interests(self, query: str, limit: int = 20) -> list[dict]:
        """FB 兴趣词搜索（Targeting Search API）。审计项目16：受众定向 v1 仅兴趣。

        返回 [{id, name, audience_size, path, ...}, ...]，供前端选兴趣 → 存 saved_audiences。
        """
        data = self.get("search", {
            "type": "adinterest",
            "q": query,
            "limit": limit,
        })
        return data.get("data", [])
