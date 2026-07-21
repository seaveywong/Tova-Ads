"""落地页事件 ingest + 子码 router/next（doc 04 转化归因 / doc 02 §C 子码路由）。

公开端点（无 JWT）——靠 landing_pages.ingest_secret 校验（Worker 携带 X-Edge-Secret）。
用 SuperSessionLocal（BYPASSRLS）因为无租户上下文（secret→page→tenant 解析）。
"""
import hashlib
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from ..core.database import SuperSessionLocal
from ..models.launch import LandingPage, LandingAdLink
from ..models.landing_event import LandingEvent
from ..models.landing_lib import LandingPixel

router = APIRouter(prefix="/landing-pages", tags=["landing-events"])


def _find_page_by_secret(db: Session, secret: str) -> LandingPage | None:
    if not secret:
        return None
    return db.query(LandingPage).filter(LandingPage.ingest_secret == secret).first()


def _ip_hash(request: Request, salt: str) -> str:
    ip = (request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    return hashlib.sha256(f"{ip}:{salt}".encode()).hexdigest()[:64] if ip else ""


def _hash_ip(ip: str, salt: str) -> str:
    """对显式传入的 IP 字符串做 hash（worker 传访客 IP 时用，比 request cf-connecting-ip 准——后者是 worker→后端来源）。"""
    return hashlib.sha256(f"{ip}:{salt}".encode()).hexdigest()[:64] if ip else ""


def _parse_ua(ua: str) -> dict:
    """从 user-agent 解析设备类型/平台/浏览器/系统（worker 不发这些，ingest 兜底解析）。
    型号不解析（iOS UA 不含型号、Android 杂乱，不可靠）。"""
    ua = ua or ""
    u = ua.lower()
    # 设备类型
    if "ipad" in u or "tablet" in u or ("android" in u and "mobile" not in u):
        dev = "tablet"
    elif "mobile" in u or "iphone" in u or "android" in u:
        dev = "mobile"
    else:
        dev = "desktop"
    # 系统
    if "windows" in u:
        osv = "Windows"
    elif "iphone" in u or "ipad" in u or "ios" in u:
        osv = "iOS"
    elif "android" in u:
        osv = "Android"
    elif "mac os" in u or "macintosh" in u:
        osv = "macOS"
    elif "linux" in u:
        osv = "Linux"
    else:
        osv = ""
    # 平台（粗）
    platform = "iOS" if osv == "iOS" else ("Android" if osv == "Android" else osv.lower() if osv else "")
    # 浏览器（顺序敏感：edg/opr/opxi 等先于 chrome/safari）
    if "edg/" in u or "edge/" in u:
        br = "Edge"
    elif "oprx" in u or "opt/" in u or "opr/" in u or "opera" in u:
        br = "Opera"
    elif "samsungbrowser" in u:
        br = "Samsung"
    elif "firefox/" in u and "seamonkey" not in u:
        br = "Firefox"
    elif "crios/" in u or "chrome/" in u or "chromium" in u:
        br = "Chrome"
    elif "safari/" in u:
        br = "Safari"
    else:
        br = ""
    return {"device_type": dev, "platform": platform, "browser": br, "os": osv}


class EventIngestIn(BaseModel):
    secret: str = ""
    event_type: str = "visit"
    slug: str = ""
    ad_id: str = ""
    act_id: str = ""
    fbclid: str = ""
    pixel_ids: str = ""  # 本次访问真实 fire 的像素（worker display 模式透传 route_next 返回值，逗号分隔；地面真相）
    path: str = ""
    target_url: str = ""
    decision: str = ""
    reason: str = ""
    country: str = ""
    region: str = ""
    city: str = ""
    colo: str = ""
    asn: str = ""
    platform: str = ""
    device_type: str = ""
    browser: str = ""
    os: str = ""
    user_agent: str = ""
    visitor_id: str = ""
    referrer: str = ""
    metadata: str = ""
    ip: str = ""


# 爬虫拦截不记录（噪音：FB爬虫AS32934 + bot UA 占 block 绝大多数，无诊断价值；真人误拦的 block 仍记录）
_CRAWLER_BLOCK_UA = ("facebookexternalhit", "facebot", "meta-externalagent", "googlebot",
                     "bingbot", "baiduspider", "bytespider", "yandexbot", "duckduckbot", "crawler", "spider")


def _is_crawler_block(asn, ua):
    if asn and str(asn) == "32934":
        return True
    u = (ua or "").lower()
    return any(t in u for t in _CRAWLER_BLOCK_UA)


@router.post("/events/ingest")
def ingest_event(body: EventIngestIn, request: Request):
    """落地页事件回传（visit/click/submit/block/redirect）。存表 + 子码自动绑。

    公开端点：secret（X-Edge-Secret header 或 body.secret）校验 landing_pages.ingest_secret。
    """
    secret = request.headers.get("x-edge-secret") or body.secret
    db = SuperSessionLocal()
    try:
        page = _find_page_by_secret(db, secret)
        if not page:
            raise HTTPException(401, "无效的 ingest secret")
        # 爬虫/bot 的拦截事件不记录（噪音，占 block 大头；真人误拦的 block 仍留作诊断）
        if body.event_type == "block" and _is_crawler_block(body.asn, body.user_agent):
            return {"ok": True, "skipped": "crawler_block"}
        # 子码自动绑：slug + ad_id 都在 → 绑 LandingAdLink.ad_id（首次点击绑；在 secret 校验后）
        # reserved/active 可绑；archived 且没绑过广告的"闲置归档"子码，有真实访问进来 → 复活绑定
        # （覆盖：生成子码→超14天没用被自动归档→之后才铺广告投流 的延迟投放场景）。
        # deleted 不复活（硬删状态，配置已清，走页级）；手动归档但绑过广告的也不动。
        if body.slug and body.ad_id and "{{" not in str(body.ad_id):
            # 不绑占位符（FB 没填 {{ad.id}} 时来的字面量，绑了就永远卡住拿不到真实广告）
            link = db.query(LandingAdLink).filter(LandingAdLink.slug == body.slug).first()
            if link and not link.ad_id and link.status in ("reserved", "active", "archived"):
                link.ad_id = body.ad_id
                if body.act_id and "{{" not in str(body.act_id):
                    link.act_id = body.act_id  # 同步记真实账户（route_next 在 ?act= 缺失时回退用它）
                link.status = "active"
                link.archived_at = None
            elif link and link.ad_id and "{{" in str(link.ad_id):
                # 已绑占位符的子码，真实访问来了→覆盖绑到真实广告（修复历史误绑）
                link.ad_id = body.ad_id
                if body.act_id and "{{" not in str(body.act_id):
                    link.act_id = body.act_id
                link.status = "active"
                link.archived_at = None
        tenant_id = page.tenant_id
        page_id = page.id
        # FB 不填 {{account.id}}(进来是字面量)→ 从 ad_id 反查 ads_cache 得真实账户
        _act = body.act_id
        if (not _act or "{{" in str(_act)) and body.ad_id:
            from ..models.ads_cache import AdsCache
            for _row in db.query(AdsCache).filter(AdsCache.tenant_id == tenant_id).all():
                try:
                    import json as _j
                    for _ad in _j.loads(_row.ads_json or "[]"):
                        if str(_ad.get("id")) == str(body.ad_id):
                            _act = _row.act_id
                            break
                except Exception:
                    continue
                if _act and "{{" not in str(_act):
                    break
        _ua = _parse_ua(body.user_agent)  # worker 只发 UA，这里解析设备/平台/浏览器/系统
        ev = LandingEvent(
            tenant_id=tenant_id, page_id=page_id,
            event_type=body.event_type, slug=body.slug, ad_id=body.ad_id,
            act_id=_act, fbclid=body.fbclid, fired_pixel_ids=body.pixel_ids,
            path=body.path, target_url=body.target_url,
            decision=body.decision, reason=body.reason,
            country=body.country, region=body.region, city=body.city,
            colo=body.colo, asn=body.asn,
            platform=body.platform or _ua["platform"],
            device_type=body.device_type or _ua["device_type"],
            browser=body.browser or _ua["browser"],
            os=body.os or _ua["os"],
            user_agent=body.user_agent, visitor_id=body.visitor_id,
            referrer=body.referrer, metadata=body.metadata,
            ip_hash=_hash_ip(body.ip, secret or "nosalt") or _ip_hash(request, secret or "nosalt"),
        )
        db.add(ev)
        db.commit()
        return {"ok": True, "event_id": ev.id}
    finally:
        db.close()


class DedupCheckIn(BaseModel):
    secret: str = ""
    ip: str = ""


@router.post("/dedup-check")
def dedup_check(body: DedupCheckIn):
    """防重复访客：查该页该访客 IP 时间窗内是否访问过（landing_events.ip_hash, event_type=visit）。"""
    from datetime import datetime, timezone, timedelta
    db = SuperSessionLocal()
    try:
        page = _find_page_by_secret(db, body.secret)
        if not page or not page.dedup_enabled:
            return {"repeat": False}
        ip_hash = _hash_ip(body.ip, body.secret or "nosalt")
        if not ip_hash:
            return {"repeat": False}
        since = datetime.now(timezone.utc) - timedelta(hours=page.dedup_window_hours or 24)
        recent = db.query(LandingEvent).filter(
            LandingEvent.page_id == page.id,
            LandingEvent.ip_hash == ip_hash,
            LandingEvent.event_type == "visit",
            LandingEvent.created_at >= since,
        ).first()
        return {"repeat": bool(recent)}
    finally:
        db.close()


class FreqCheckIn(BaseModel):
    secret: str = ""
    ip: str = ""
    max: int = 3
    window_min: int = 60


@router.post("/frequency-check")
def frequency_check(body: FreqCheckIn):
    """频次检查：同一 IP 在 window_min 分钟内是否已访问 >= max 次。
    Worker 调此端点（secret 校验 + IP hash），超出则拦截。"""
    from datetime import datetime, timezone, timedelta
    db = SuperSessionLocal()
    try:
        page = _find_page_by_secret(db, body.secret)
        if not page:
            return {"exceeded": False}
        ip_hash = _hash_ip(body.ip, body.secret or "nosalt")
        if not ip_hash:
            return {"exceeded": False}
        since = datetime.now(timezone.utc) - timedelta(minutes=body.window_min or 60)
        count = db.query(LandingEvent).filter(
            LandingEvent.page_id == page.id,
            LandingEvent.ip_hash == ip_hash,
            LandingEvent.event_type.in_(["visit", "redirect"]),
            LandingEvent.created_at >= since,
        ).count()
        return {"exceeded": count >= (body.max or 3), "count": count}
    finally:
        db.close()


class RouteNextIn(BaseModel):
    secret: str = ""
    slug: str = ""
    ad_id: str = ""
    act_id: str = ""  # 本次点击的广告账户（worker 从 ?act= 透传；多账户复用按它 fire 正确像素）


@router.post("/router/next")
def route_next(body: RouteNextIn):
    """子码路由：slug → target_url（rotation: sequential/random/first，doc 02 §C）+ 子码级像素。

    公开端点（secret 校验）。Worker 调此决定 /a/{slug} 跳转目标 + fire 哪些像素。
    返回 {target_url, mode, pixel_ids, conversion_event}。
    pixel_ids 按本次点击的账户(body.act_id，来自 ?act= 宏)优先 fire——多账户复用一子码
    时按真实账户 fire 正确像素；无 act 则回退子码绑的账户，再回退页级。
    """
    import json as _json
    db = SuperSessionLocal()
    try:
        page = _find_page_by_secret(db, body.secret)
        link = db.query(LandingAdLink).filter(LandingAdLink.slug == body.slug).first() if body.slug else None
        # 跨页防护：slug 全局唯一，但若该子码不属于本页(老数据/迁移)，不当本页子码用(避免 fire 错像素/跳错)
        if link and page and link.page_id and link.page_id != page.id:
            link = None

        # 1. 算 target_url + mode
        #    优先级：广告级跳转覆盖(?ad= 带的广告若有专属 target) > 子码专属跳转 > 页轮换默认
        target_url = None
        mode = "no_page"
        if body.ad_id and page:
            from ..models.launch import AdRedirectOverride
            ov = db.query(AdRedirectOverride).filter(
                AdRedirectOverride.tenant_id == page.tenant_id,
                AdRedirectOverride.ad_id == str(body.ad_id),
            ).first()
            if ov and ov.target_url:
                target_url, mode = ov.target_url, "ad_override"
        if target_url is None and link and link.target_urls:
            try:
                urls = _json.loads(link.target_urls) if link.target_urls.startswith("[") else [link.target_urls]
            except Exception:
                urls = []
            if urls:
                target_url, mode = urls[0], "ad_link_first"
        if target_url is None and page and page.target_urls:
            urls = _json.loads(page.target_urls) if page.target_urls.startswith("[") else [page.target_urls]
            m = (page.rotation_mode or "first").lower()
            if not urls:
                mode = "no_targets"
            elif m == "random":
                import secrets as _s
                target_url, mode = _s.choice(urls), "random"
            elif m == "sequential":
                cnt = db.query(LandingEvent).filter(
                    LandingEvent.page_id == page.id,
                    LandingEvent.event_type.in_(["visit", "redirect"]),
                ).count()
                target_url, mode = urls[cnt % len(urls)], "sequential"
            else:
                target_url, mode = urls[0], "first"

        # 2. pixel_ids：按广告组绑定的像素 fire（FB ground truth: promoted_object.pixel_id）
        #    优先级：adset pixel_id(ads_cache) → LandingPixel by act_id → 页级 pixel_ids
        def _clean_act(a):
            a = str(a) if a else ""
            return a if (a and "{{" not in a) else None

        _derived_act = None
        _derived_pixel = None  # adset 级像素（FB promoted_object.pixel_id）
        if body.ad_id and page:
            from ..models.ads_cache import AdsCache
            for _row in db.query(AdsCache).filter(AdsCache.tenant_id == page.tenant_id).all():
                try:
                    _ads = _json.loads(_row.ads_json or "[]")
                    _found_ad = None
                    for _ad in _ads:
                        if str(_ad.get("id")) == str(body.ad_id):
                            _found_ad = _ad
                            _derived_act = _row.act_id
                            break
                    if _found_ad:
                        _asid = _found_ad.get("adset_id")
                        _asid = str(_asid.get("id") if isinstance(_asid, dict) else _asid) if _asid else None
                        if _asid:
                            for _as in _json.loads(_row.adsets_json or "[]"):
                                if str(_as.get("id")) == _asid:
                                    _po = _as.get("promoted_object") or {}
                                    if isinstance(_po, str):
                                        try: _po = _json.loads(_po)
                                        except Exception: _po = {}
                                    _pid = _po.get("pixel_id")
                                    if _pid: _derived_pixel = str(_pid)
                                    break
                        break
                except Exception:
                    continue
        pixel_ids = []
        if _derived_pixel:
            pixel_ids = [_derived_pixel]
        if not pixel_ids:
            _candidate_acts = [c for c in [_derived_act, _clean_act(body.act_id),
                                           (link.act_id if link else None)] if c]
            for _act in _candidate_acts:
                pixel_ids = [p.pixel_id for p in db.query(LandingPixel).filter(
                    LandingPixel.act_id == _act, LandingPixel.status == "active"
                ).all()]
                if pixel_ids:
                    break
        if not pixel_ids and page and page.pixel_ids:
            try:
                pixel_ids = _json.loads(page.pixel_ids)
            except Exception:
                pixel_ids = []

        conversion_event = (page.conversion_event if page else None)
        conversion_events = []
        if page and page.conversion_events:
            try:
                conversion_events = _json.loads(page.conversion_events)
            except Exception:
                pass
        if not conversion_events and conversion_event:
            conversion_events = [conversion_event]
        return {"target_url": target_url, "mode": mode,
                "pixel_ids": pixel_ids, "conversion_event": conversion_event,
                "conversion_events": conversion_events}
    finally:
        db.close()
