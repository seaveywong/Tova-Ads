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
        raise HTTPException(400, "INVALID_DOMAIN")
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
