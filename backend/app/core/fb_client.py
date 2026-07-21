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

GRAPH_VERSION = "v22.0"
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
        return FB_ERROR_MAP[code]
    if "non-discrimination" in msg.lower():
        return FB_ERROR_MAP[2859002]
    return ("generic", f"Facebook 返回错误（code {code}）：{msg[:120]}")


class FbApiError(Exception):
    """FB API 调用失败 —— 带 category + friendly + raw，供错误翻译层用（doc 05）。"""

    def __init__(self, category: str, friendly: str, raw: dict, status: int = 0):
        self.category = category
        self.friendly = friendly
        self.raw = raw
        self.status = status
        super().__init__(friendly)


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
        base["limit"] = limit
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

    def get_ad_accounts(self) -> list[dict]:
        """拉取可管理的广告账户列表（全量分页，单 token >200 账户不漏）。"""
        return self.get_paged("me/adaccounts", {
            "fields": "account_id,account_status,name,currency,timezone_name,balance,spend_cap,amount_spent",
        })

    def get_pages(self) -> list[dict]:
        """拉取可管理的主页列表（全量分页）。"""
        return self.get_paged("me/accounts", {
            "fields": "id,name,category,can_post,fan_count,tasks",
        })

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

    def get_ad_insights(self, act_id: str, date_preset: str = "today", limit: int = 200,
                       only_active: bool = True, since: str = "", until: str = "") -> list[dict]:
        """拉取广告级 insights（按广告拆解，全量分页）。

        优先用 time_range(since/until 账户本地日，精确) 避免 FB date_preset(today) 跨时区累积失真；
        不传 since/until 则 fallback date_preset。
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
            # 只保留 ACTIVE（含学习中的——学习中但 ACTIVE = 在花钱，用户明确要纳入）
            all_ads = [a for a in all_ads if a.get("effective_status") == "ACTIVE"]
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
        resp = httpx.post(
            url,
            params={"access_token": self.token},
            files={filename: (filename, image_bytes, "image/jpeg")},
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

    def get_ads(self, act_id: str, effective_status: str | None = '["ACTIVE"]',
                fields: str | None = None) -> list[dict]:
        """拉广告（全量分页）。effective_status=None 拉全状态(管理器)，默认仅 ACTIVE(巡检/哨兵)。"""
        params = {"fields": fields or (
            "id,name,status,effective_status,configured_status,adset_id,campaign_id,"
            "creative{id,effective_object_story_id,object_story_spec},review_feedback")}
        if effective_status:
            params["filtering"] = f'[{{"field":"effective_status","operator":"IN","value":{effective_status}}}]'
        return self.get_paged(f"act_{act_id}/ads", params)

    def get_active_ads(self, act_id: str) -> list[dict]:
        """拉 ACTIVE 广告（巡检/哨兵用，兼容旧调用）。"""
        return self.get_ads(act_id)

    def get_ad_creative_links(self, act_id: str) -> dict:
        """拉账户下广告的创意链接（子码自动绑定用）。返 {ad_id: link_url}。

        从 object_story_spec 提取 link_data.link 或 video_data.call_to_action.value.link。
        """
        data = self.get(f"act_{act_id}/ads", {
            "fields": "id,creative{object_story_spec{link_data{link},video_data{call_to_action{value{link}}}}}",
            "limit": 200,
        })
        out: dict[str, str] = {}
        for ad in data.get("data", []):
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
