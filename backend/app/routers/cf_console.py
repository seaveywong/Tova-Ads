"""CF 管控台路由（2026-09-19 批CY 一期：只读总览 + 外部域名接入向导）。

CF zone/Pages 项目是**平台级资产**（跨租户）——全部端点 require_superadmin，
普通用户/owner 一律 403（批CV 铁律：不属自己的不可见，属自己的必可见——本组只属超管）。
数据直连 CF API（凭据来自 settings.cf_api_token/cf_account_id，配置在 设置→Cloudflare），
overview 30s 进程内缓存防连点打爆 CF。
"""
import re
import time as _time
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ..core.config import settings
from ..core.cf_client import CfClient
from ..core.deps import require_superadmin

router = APIRouter(prefix="/cf-console", tags=["cf-console"])

_CACHE: dict = {}
_TTL = 30


def _cf() -> CfClient:
    if not (settings.cf_api_token and settings.cf_account_id):
        raise HTTPException(400, "CF_API_NOT_CONFIGURED")
    return CfClient(settings.cf_api_token, settings.cf_account_id)


def _cf_client_for_user(user=Depends(require_superadmin)) -> CfClient:
    return _cf()


@router.get("/overview")
def cf_overview(_=Depends(_cf_client_for_user)):
    """域名 zone 总览（状态/NS/套餐）+ Pages 项目清单（关联落地页）。30s 缓存。"""
    hit = _CACHE.get("overview")
    if hit and _time.time() - hit[0] < _TTL:
        return hit[1]
    cf = _cf()
    zones = [{
        "id": z.get("id"), "name": z.get("name"), "status": z.get("status"),
        "plan": (z.get("plan") or {}).get("name", ""),
        "name_servers": z.get("name_servers") or [],
        "paused": bool(z.get("paused")),
    } for z in cf.list_zones()]
    # Pages 项目：落地页项目（tovaads-landing-{id}）关联库内页面标题/状态
    from ..core.database import SuperSessionLocal
    from ..models.launch import LandingPage
    db = SuperSessionLocal()
    try:
        lp_map = {p.id: p for p in db.query(LandingPage).all()}
    finally:
        db.close()
    pages = []
    for proj in cf.list_projects():
        name = proj.get("name") or ""
        page = None
        if name.startswith("tovaads-landing-"):
            try:
                page = lp_map.get(int(name.rsplit("-", 1)[-1]))
            except ValueError:
                pass
        try:
            domains = [d.get("name") for d in cf.list_project_domains(name) if d.get("name")]
        except Exception:
            domains = []
        pages.append({
            "name": name,
            "created_on": (proj.get("created_on") or "")[:19],
            "domains": domains,
            "page_id": page.id if page else None,
            "page_title": page.title if page else "",
            "page_status": page.status if page else "",
        })
    res = {"zones": zones, "pages": pages}
    _CACHE["overview"] = (_time.time(), res)
    return res


class ZoneIn(BaseModel):
    domain: str


@router.post("/zones")
def cf_onboard_zone(body: ZoneIn, _=Depends(_cf_client_for_user)):
    """外部域名接入向导：在 CF 建 zone（幂等，已存在返回现状）→ 返回注册商要改的 NS。"""
    d = (body.domain or "").strip().lower().rstrip(".")
    d = d.replace("https://", "").replace("http://", "").split("/")[0]
    if not re.match(r"^[a-z0-9][a-z0-9.-]*[a-z0-9]$", d) or "." not in d or len(d) > 253:
        raise HTTPException(400, "域名格式不正确（例：mybrand.com）")
    cf = _cf()
    z = cf.create_zone(d)
    _CACHE.pop("overview", None)
    return {"ok": True,
            "zone": {"id": z.get("id"), "name": z.get("name"), "status": z.get("status")},
            "name_servers": z.get("name_servers") or []}


@router.get("/zones/{zone_id}/dns")
def cf_zone_dns(zone_id: str, _=Depends(_cf_client_for_user)):
    """单 zone 的 DNS 记录表（总览展开行用）。"""
    cf = _cf()
    return [{"id": r.get("id"), "type": r.get("type"), "name": r.get("name"),
             "content": str(r.get("content") or "")[:120], "proxied": bool(r.get("proxied")),
             "ttl": r.get("ttl")} for r in cf.list_dns_records(zone_id)]


@router.delete("/zones/{zone_id}")
def cf_delete_zone(zone_id: str, name: str = "", _=Depends(_cf_client_for_user)):
    """删 zone（连带全部 DNS——不可逆）。必须带 ?name= 且与 CF 侧 zone 名一致才执行（防误删）。"""
    if not name:
        raise HTTPException(400, "NAME_REQUIRED")
    cf = _cf()
    match = [z for z in cf.list_zones() if z.get("id") == zone_id]
    if not match:
        raise HTTPException(404, "ZONE_NOT_FOUND")
    if (match[0].get("name") or "").lower() != name.strip().lower():
        raise HTTPException(400, "NAME_MISMATCH")
    cf.delete_zone(zone_id)
    _CACHE.pop("overview", None)
    return {"ok": True}


@router.get("/usage")
def cf_usage(fresh: int = 0, _=Depends(_cf_client_for_user)):
    """各 zone 访问量（今日/近7天/近30天：请求/带宽/独立访客）+ 套餐与限额参考。
    GraphQL Analytics 需 Token 有 Zone Analytics Read——缺权限返回 needs_permission
    + perm（CF 原话的权限名转可读）+ token_tail（定位"改错 token"——用户曾改另一把
    仍看不到数据）。fresh=1 绕 60s 缓存（改完权限立即重试点 ⟳）。"""
    if not fresh:
        hit = _CACHE.get("usage")
        if hit and _time.time() - hit[0] < 60:
            return hit[1]
    cf = _cf()
    zones = cf.list_zones()
    from datetime import date as _date, timedelta as _td
    today = _date.today()
    zids = [z["id"] for z in zones]
    # 批量查询（zoneTag_in 一次拉全部 zone——逐 zone×2 查询 14 次串行曾拖慢面板 10s+）
    q30 = """
    query($zs: [String!]!, $s: Date!, $e: Date!) {
      viewer { zones(filter: {zoneTag_in: $zs}) { zoneTag
        httpRequests1dGroups(limit: 31, filter: {date_geq: $s, date_leq: $e}, orderBy: [date_DESC]) {
          dimensions { date }
          sum { requests bytes pageViews }
          uniq { uniques }
        }
      }}
    }"""
    # 今日近实时：1h groups（小时粒度，~1h 滞后；1d 数据集今日要等数小时）。结构已探针验证
    # （date_geq 过滤 + 纯聚合无 dimensions；adaptive 数据集字段集不同故弃用）。
    q_today = """
    query($zs: [String!]!, $s: Date!, $e: Date!) {
      viewer { zones(filter: {zoneTag_in: $zs}) { zoneTag
        httpRequests1hGroups(limit: 10, filter: {date_geq: $s, date_leq: $e}) {
          sum { requests pageViews }
          uniq { uniques }
        }
      }}
    }"""
    g30, gtoday, all_errs = {}, {}, []
    try:
        r30 = cf.graphql(q30, {"zs": zids, "s": str(today - _td(days=30)), "e": str(today)})
        all_errs += r30.get("errors") or []
        for zn in (((r30.get("data") or {}).get("viewer") or {}).get("zones") or []):
            g30[zn.get("zoneTag")] = zn.get("httpRequests1dGroups") or []
    except Exception as e:
        all_errs.append({"message": str(e)})
    try:
        rt = cf.graphql(q_today, {"zs": zids, "s": str(today), "e": str(today)})
        all_errs += rt.get("errors") or []
        for zn in (((rt.get("data") or {}).get("viewer") or {}).get("zones") or []):
            gtoday[zn.get("zoneTag")] = zn.get("httpRequests1hGroups") or []
    except Exception as e:
        all_errs.append({"message": str(e)})
    # 权限探测（两查询合并错误流）。关键词须覆盖两种报错文案：单 zone=“does not have
    # permission '...'”；zoneTag_in 批量=“zones [...] are not authorized”（不含 permission
    # 一词——曾漏判误报权限已通）。extensions.code=authz 再兜一层
    msg = " ".join(str(e.get("message", "")) for e in all_errs)
    low = msg.lower()
    code_authz = any((e.get("extensions") or {}).get("code") == "authz" for e in all_errs)
    needs_perm = code_authz or any(
        k in low for k in ("permission", "authz", "not entitled",
                           "does not have", "not authorized"))
    perm_pretty = ""
    if needs_perm:
        # CF 原话 'com.cloudflare.api.account.zone.analytics.read' → 'Zone › Analytics › Read'
        m = re.search(r"permission '([a-z.]+)'", low)
        if m:
            parts = m.group(1).split(".")[-3:]
            perm_pretty = " › ".join(p.capitalize() for p in parts)
    out = []
    for z in zones:
        row = {"zone": z.get("name"), "plan": (z.get("plan") or {}).get("name", ""),
               "today": None, "today_rt": False, "d7": 0, "d30": 0,
               "bytes30": 0, "uniques30": 0, "daily": []}
        daily = []
        for g in g30.get(z["id"]) or []:
            d = (g.get("dimensions") or {}).get("date")
            s = g.get("sum") or {}
            req = int(s.get("requests") or 0)
            row["d30"] += req
            row["bytes30"] += int(s.get("bytes") or 0)
            row["uniques30"] += int((g.get("uniq") or {}).get("uniques") or 0)
            delta = (today - _date.fromisoformat(d)).days
            if 0 < delta <= 30:
                daily.append({"d": d, "r": req})   # 迷你趋势不含今日（今日走 1h 近实时）
            if delta < 7:
                row["d7"] += req
            if delta == 0:
                row["today"] = {"requests": req,
                                "pageViews": int(s.get("pageViews") or 0),
                                "uniques": int((g.get("uniq") or {}).get("uniques") or 0)}
        row["daily"] = sorted(daily, key=lambda x: x["d"])
        th = gtoday.get(z["id"]) or []
        if th:
            s = th[0].get("sum") or {}
            row["today"] = {"requests": int(s.get("requests") or 0),
                            "pageViews": int(s.get("pageViews") or 0),
                            "uniques": int((th[0].get("uniq") or {}).get("uniques") or 0)}
            row["today_rt"] = True
        if not (g30.get(z["id"]) or gtoday.get(z["id"])):
            row["no_data"] = True
        out.append(row)
    res = {"zones": out, "needs_permission": needs_perm, "perm": perm_pretty,
           "token_tail": (settings.cf_api_token or "")[-6:],
           # 官方常量（Free 套餐参考；Pro/Business 上调）——API 不返回限额，按套餐静态展示
           "limits": {"pages_static": "不限", "pages_bandwidth": "不限",
                      "functions_per_day": "10万", "builds_per_month": "500"}}
    _CACHE["usage"] = (_time.time(), res)
    return res


@router.get("/reconcile")
def cf_reconcile(fresh: int = 0, _=Depends(_cf_client_for_user)):
    """CF zone ↔ 平台域名库对账（超管体检）：cf_only=CF 有 zone 但库未登记（白买了/漏登记）；
    lib_only=库登记了但 CF 无对应 zone（NS 没切/已删 zone）。60s 缓存，fresh=1 绕过。"""
    if not fresh:
        hit = _CACHE.get("reconcile")
        if hit and _time.time() - hit[0] < 60:
            return hit[1]
    cf = _cf()
    zones = {(z.get("name") or "").lower().strip().rstrip(".") for z in cf.list_zones()}
    from ..core.database import SuperSessionLocal
    from ..models.landing_lib import LandingDomain
    from ..models.auth import Tenant
    db = SuperSessionLocal()
    try:
        rows = db.query(LandingDomain).filter(LandingDomain.status == "active").all()
        tmap = {t.id: t.name for t in db.query(Tenant).all()}
    finally:
        db.close()
    lib: dict = {}
    for r in rows:
        d = (r.domain or "").lower().strip().rstrip(".")
        if not d:
            continue
        lib.setdefault(d, []).append(
            {"tenant": tmap.get(r.tenant_id, str(r.tenant_id)), "cf_zone_status": r.cf_zone_status or ""})
    res = {
        "matched": sorted(zones & set(lib)),
        "cf_only": sorted(zones - set(lib)),
        "lib_only": [{"domain": d, "owners": v} for d, v in sorted(lib.items()) if d not in zones],
        "cf_zone_count": len(zones), "lib_count": len(lib),
    }
    _CACHE["reconcile"] = (_time.time(), res)
    return res
