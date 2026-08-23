"""广告管理器路由：读 ads_cache（巡检同步的缓存）+ perf_snapshots 消耗，跨账户汇总，0 FB。

对齐 FB Ads Manager：三层独立列表 + perf 聚合消耗。手动刷新（refresh=1）强制重拉。
"""
import json
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from ..core.database import get_db
from ..core.deps import CurrentUser, require_permission
from ..core.i18n import req_locale, L
from ..core.fb_tokens import client_for_account
from ..core.fb_client import FbApiError
from ..models.perf import PerfSnapshot
from ..models.fb import Account
from ..models.ads_cache import AdsCache
from ..models.launch import LandingAdLink
from ..services.guard_engine import from_minor_units

router = APIRouter(prefix="/ads", tags=["ads"])


@router.post("/sync-cache")
def sync_ads_cache(user: CurrentUser = Depends(require_permission("ads.read"))):
    """手动触发广告实体缓存采集（拉 campaigns/adsets/ads → ads_cache）。
    自动 15min 一次；此为手动即采（建了新广告后立即同步看效果）。"""
    from ..services.ads_cache_sync import run_ads_cache_sync
    return run_ads_cache_sync()


def _id_of(v):
    if isinstance(v, dict):
        return v.get("id")
    return v


# ad_id → act_id 反查表（5min 模块缓存——诊断面板每次打开不再 json.loads 全部账户 ads_json）
_AD_ACT_MAP: dict = {}   # {tenant_id: (built_at, {ad_id: act_id})}
_AD_ACT_TTL = 300

# 后台刷新状态（gunicorn 多 worker 各自一份，可接受——同租户并发刷只是多花 FB 配额）
# {tenant_id: {"running": bool, "started_at": ts, "done": n, "total": n}}
_REFRESH_STATE: dict = {}

# list_ads 聚合段 30s 内存缓存（照 dashboard _CACHE 样板）：slug 反查 + landing 聚合
_AGG_CACHE: dict = {}
_AGG_CACHE_TTL = 30


def _bg_refresh(tenant_id: int, act_id: str):
    """后台逐账户刷 ads_cache（advisory lock 112 单实例互斥）。"""
    from ..core.database import SuperSessionLocal, acquire_run_lock, release_run_lock
    st = _REFRESH_STATE.get(tenant_id)
    if st and st.get("running"):
        return
    lock = None
    db = None
    _REFRESH_STATE[tenant_id] = {"running": True, "started_at": datetime.now(timezone.utc).isoformat(), "done": 0, "total": 0}
    try:
        lock = acquire_run_lock(112)
        db = SuperSessionLocal()
        acts = [act_id] if act_id else [a.act_id for a in db.query(Account).filter(
            Account.tenant_id == tenant_id, Account.is_managed == True,  # noqa: E712
            Account.account_status == 1).all()]
        _REFRESH_STATE[tenant_id]["total"] = len(acts)
        for a in acts:
            fb = client_for_account(db, tenant_id, a, "read")
            if fb:
                _sync_one(db, tenant_id, a, fb)
            _REFRESH_STATE[tenant_id]["done"] += 1
        db.commit()
    except Exception:
        if db:
            db.rollback()
    finally:
        if db:
            db.close()
        if lock:
            release_run_lock(lock, 112)
        _REFRESH_STATE[tenant_id]["running"] = False


def _agg_cached(tenant_id: int, act_id: str, date_from: str, date_to: str, db) -> tuple:
    """slug 反查 + landing 聚合（30s 缓存），返回 (slug_map, landing_map)。"""
    import time as _t
    from sqlalchemy import text as _text
    key = f"agg:{tenant_id}:{act_id}:{date_from}:{date_to}"
    now = _t.time()
    ent = _AGG_CACHE.get(key)
    if ent and now - ent[0] < _AGG_CACHE_TTL:
        return ent[1], ent[2]
    slug_map = {}
    try:
        _ev_rows = db.execute(_text("""
            SELECT DISTINCT ON (ad_id) ad_id, slug
            FROM landing_events
            WHERE tenant_id = :tid AND ad_id IS NOT NULL AND ad_id != ''
              AND slug IS NOT NULL AND slug != ''
            ORDER BY ad_id, created_at DESC
        """), {"tid": tenant_id}).fetchall()
        for _r in _ev_rows:
            slug_map[str(_r.ad_id)] = _r.slug
    except Exception:
        pass
    for _r in db.query(LandingAdLink.ad_id, LandingAdLink.slug).filter(
        LandingAdLink.tenant_id == tenant_id,
        LandingAdLink.ad_id.isnot(None),
        LandingAdLink.ad_id != "",
        LandingAdLink.status.notin_(["archived", "deleted"]),
    ).all():
        slug_map.setdefault(str(_r.ad_id), _r.slug)
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    _BZ = _tz(_td(hours=8))
    _us = _dt.strptime(date_from, "%Y-%m-%d").replace(tzinfo=_BZ).astimezone(_tz.utc)
    _ue = _dt.strptime(date_to, "%Y-%m-%d").replace(tzinfo=_BZ).astimezone(_tz.utc) + _td(days=1)
    landing = {}
    for _r in db.execute(_text("""
        SELECT ad_id,
               SUM(CASE WHEN event_type IN ('visit','redirect') THEN 1 ELSE 0 END) AS lv,
               COUNT(DISTINCT CASE WHEN event_type IN ('redirect','click') THEN ip_hash END) AS lp
        FROM landing_events
        WHERE tenant_id = :tid AND ad_id IS NOT NULL AND ad_id != ''
          AND created_at >= :s AND created_at < :e
        GROUP BY ad_id
    """), {"tid": tenant_id, "s": _us, "e": _ue}).fetchall():
        landing[str(_r.ad_id)] = {"visits": int(_r.lv or 0), "pass": int(_r.lp or 0)}
    if len(_AGG_CACHE) > 200:
        _AGG_CACHE.clear()
    _AGG_CACHE[key] = (now, slug_map, landing)
    return slug_map, landing


def _ad_act_lookup(db: Session, tenant_id: int) -> dict:
    import time as _t
    ent = _AD_ACT_MAP.get(tenant_id)
    now = _t.time()
    if ent and now - ent[0] < _AD_ACT_TTL:
        return ent[1]
    m = {}
    for cr in db.query(AdsCache).filter(AdsCache.tenant_id == tenant_id).all():
        try:
            for _a in json.loads(cr.ads_json or "[]"):
                _aid = str(_id_of(_a.get("id")) if isinstance(_a, dict) else _a.get("id"))
                if _aid:
                    m[_aid] = cr.act_id
        except Exception:
            continue
    _AD_ACT_MAP[tenant_id] = (now, m)
    if len(_AD_ACT_MAP) > 100:
        _AD_ACT_MAP.clear()
    return m


def _perf_map(db: Session, tenant_id: int, act_id: str, date_from: str, date_to: str) -> dict:
    """ad 级 perf 聚合 → {ad_id: {spend, conv, impressions, clicks, reach}}。act_id 空=跨账户全部。"""
    q = db.query(PerfSnapshot.ad_id, func.sum(PerfSnapshot.spend), func.sum(PerfSnapshot.conversions),
                 func.sum(PerfSnapshot.impressions), func.sum(PerfSnapshot.clicks), func.sum(PerfSnapshot.reach)).filter(
        PerfSnapshot.tenant_id == tenant_id)
    if act_id:
        q = q.filter(PerfSnapshot.act_id == act_id)
    if date_from:
        q = q.filter(PerfSnapshot.snapshot_date >= date_from)
    if date_to:
        q = q.filter(PerfSnapshot.snapshot_date <= date_to)
    rows = q.group_by(PerfSnapshot.ad_id).all()
    return {r[0]: {"spend": float(r[1] or 0), "conv": int(r[2] or 0),
                   "impressions": int(r[3] or 0), "clicks": int(r[4] or 0), "reach": int(r[5] or 0)} for r in rows}


def _attach_perf(items: list, perf_map: dict) -> list:
    out = []
    for it in items:
        p = perf_map.get(it.get("id"), {"spend": 0.0, "conv": 0, "impressions": 0, "clicks": 0, "reach": 0})
        spend, conv, imp, clk, reach = p["spend"], p["conv"], p["impressions"], p["clicks"], p["reach"]
        out.append({**it, "spend": round(spend, 2), "conversions": conv,
                    "cpa": round(spend / conv, 2) if conv else 0.0,
                    "impressions": imp, "clicks": clk, "reach": reach,
                    "frequency": round(imp / reach, 2) if reach else 0.0,
                    "ctr": round(clk / imp * 100, 2) if imp else 0.0})
    return out


def _sync_one(db: Session, tenant_id: int, act_id: str, fb) -> bool:
    """拉单账户 campaigns/adsets/ads → upsert ads_cache。返回是否成功。"""
    try:
        campaigns = fb.get_campaigns(act_id)
        adsets = fb.get_adsets(act_id, effective_status=None)
        ads = fb.get_ads(act_id, effective_status=None)
    except (FbApiError, Exception):
        return False
    row = db.query(AdsCache).filter(
        AdsCache.tenant_id == tenant_id, AdsCache.act_id == act_id).first()
    if not row:
        row = AdsCache(tenant_id=tenant_id, act_id=act_id)
        db.add(row)
    row.campaigns_json = json.dumps(campaigns)
    row.adsets_json = json.dumps(adsets)
    row.ads_json = json.dumps(ads)
    row.updated_at = datetime.now(timezone.utc)
    return True


@router.get("/list")
def list_ads(
    act_id: str = "",
    date_from: str = "",
    date_to: str = "",
    refresh: int = 0,
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = None,
):
    """广告管理器列表：读 ads_cache（跨账户汇总，0 FB）+ perf 消耗。

    act_id 空=全部账户汇总；refresh=1 起后台刷新（立即返回当前缓存 + refreshing=true）。
    """
    if not date_from:
        date_from = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")
    if not date_to:
        date_to = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    refreshing = False
    if refresh:
        # 改后台刷：立即返回缓存，前端轮询 /ads/refresh-status 直到完成
        background_tasks.add_task(_bg_refresh, user.tenant_id, act_id)
        refreshing = True
    # 读缓存——只看 managed 账户（已移除的不显示广告）
    managed_ids = {a.act_id for a in db.query(Account).filter(
        Account.tenant_id == user.tenant_id, Account.is_managed == True  # noqa: E712
    ).all()}
    q = db.query(AdsCache).filter(AdsCache.tenant_id == user.tenant_id)
    if act_id:
        q = q.filter(AdsCache.act_id == act_id)
    caches = [c for c in q.all() if c.act_id in managed_ids]
    # 账户名 + currency 映射（只查 managed）
    _acc_rows = db.query(Account).filter(
        Account.tenant_id == user.tenant_id, Account.is_managed == True  # noqa: E712
    ).all()
    acc_map = {a.act_id: a.name for a in _acc_rows}
    cur_map = {a.act_id: (a.currency or "USD") for a in _acc_rows}
    # 合并三层（跨账户）+ 标 act_id/account_name
    all_campaigns, all_adsets, all_ads = [], [], []
    ad_to_adset, ad_to_camp = {}, {}
    for c in caches:
        for cm in json.loads(c.campaigns_json or "[]"):
            cm["act_id"] = c.act_id; cm["account_name"] = acc_map.get(c.act_id, c.act_id)
            all_campaigns.append(cm)
        for as_ in json.loads(c.adsets_json or "[]"):
            as_["act_id"] = c.act_id; as_["account_name"] = acc_map.get(c.act_id, c.act_id)
            all_adsets.append(as_)
        for ad in json.loads(c.ads_json or "[]"):
            ad["act_id"] = c.act_id; ad["account_name"] = acc_map.get(c.act_id, c.act_id)
            ad_to_adset[ad.get("id")] = _id_of(ad.get("adset_id"))
            ad_to_camp[ad.get("id")] = _id_of(ad.get("campaign_id"))
            all_ads.append(ad)
    # perf 跨账户 + adset/campaign 聚合
    perf = _perf_map(db, user.tenant_id, act_id, date_from, date_to)
    adset_perf, camp_perf = {}, {}
    for ad_id, p in perf.items():
        for tgt, key in [(adset_perf, ad_to_adset.get(ad_id)), (camp_perf, ad_to_camp.get(ad_id))]:
            if not key:
                continue
            d = tgt.setdefault(key, {"spend": 0.0, "conv": 0, "impressions": 0, "clicks": 0, "reach": 0})
            d["spend"] += p["spend"]; d["conv"] += p["conv"]
            d["impressions"] += p["impressions"]; d["clicks"] += p["clicks"]; d["reach"] += p["reach"]
    def _conv_budget(items):
        for it in items:
            cur = cur_map.get(it.get("act_id"), "USD")
            if it.get("daily_budget"):
                it["daily_budget_amount"] = from_minor_units(it["daily_budget"], cur)
            if it.get("lifetime_budget"):
                it["lifetime_budget_amount"] = from_minor_units(it["lifetime_budget"], cur)
        return items

    # 落地聚合 + 子码反查（30s 缓存，口径同仪表盘：visit+redirect=访问, redirect+click=通过）
    _slug_map, _landing = _agg_cached(user.tenant_id, act_id, date_from, date_to, db)
    for ad in all_ads:
        _ls = _landing.get(str(ad.get("id")))
        ad["landing_visits"] = _ls["visits"] if _ls else 0
        ad["landing_pass"] = _ls["pass"] if _ls else 0
        # 提取 creative 的 effective_object_story_id 供"复用此帖铺放"入口
        _cr = ad.get("creative")
        _sid = ""
        if isinstance(_cr, dict):
            _sid = _cr.get("effective_object_story_id") or ""
            if not _sid and isinstance(_cr.get("data"), list) and _cr["data"]:
                _sid = (_cr["data"][0] or {}).get("effective_object_story_id") or ""
        ad["object_story_id"] = _sid
        ad["slug"] = _slug_map.get(str(ad.get("id"))) or ""

    return {
        "act_id": act_id, "date_from": date_from, "date_to": date_to,
        "cached_at": str(caches[0].updated_at) if caches and caches[0].updated_at else "",
        "refreshing": refreshing,
        "campaigns": _conv_budget(_attach_perf(all_campaigns, camp_perf)),
        "adsets": _conv_budget(_attach_perf(all_adsets, adset_perf)),
        "ads": _attach_perf(all_ads, perf),
    }


@router.get("/refresh-status")
def ads_refresh_status(
    user: CurrentUser = Depends(require_permission("ads.read")),
):
    """后台刷新进度（本 worker 进程内；多 worker 下读到的可能是旧态，前端轮询有上限兜底）。"""
    st = _REFRESH_STATE.get(user.tenant_id)
    return st or {"running": False, "done": 0, "total": 0}


@router.post("/refresh")
def refresh_ads(
    act_id: str = "",
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """手动刷新 ads_cache（单账户 act_id 或全部）。"""
    acts = [act_id] if act_id else [a.act_id for a in db.query(Account).filter(
        Account.tenant_id == user.tenant_id, Account.is_managed == True,  # noqa: E712
        Account.account_status == 1).all()]
    ok = 0
    for a in acts:
        fb = client_for_account(db, user.tenant_id, a, "read")
        if fb and _sync_one(db, user.tenant_id, a, fb):
            ok += 1
    db.commit()
    return {"refreshed": ok, "total": len(acts)}


# ── 写操作（Phase D2）──

class StatusIn(BaseModel):
    act_id: str
    node_id: str
    level: str = "ad"  # ad/adset/campaign
    status: str  # ACTIVE/PAUSED/ARCHIVED


class BatchStatusIn(BaseModel):
    items: list[StatusIn]


class BudgetIn(BaseModel):
    act_id: str
    node_id: str
    level: str = "adset"
    daily_budget: float | None = None
    lifetime_budget: float | None = None
    budget_type: str = "daily"  # daily / lifetime；显式金额优先


class DeleteIn(BaseModel):
    act_id: str
    node_id: str


@router.post("/status")
def set_ad_status(
    body: StatusIn,
    user: CurrentUser = Depends(require_permission("ads.update")),
    db: Session = Depends(get_db),
):
    """改广告/组/系列状态（ACTIVE/PAUSED/ARCHIVED）。回读验证 + 缓存 patch。"""
    from ..services.ad_ops import set_status
    r = set_status(db, user.tenant_id, body.act_id, body.node_id, body.level, body.status, operator=user.email)
    if not r.get("success"):
        raise HTTPException(400, r.get("error", "操作失败"))
    return r


@router.post("/batch-status")
def batch_set_status(
    body: BatchStatusIn,
    user: CurrentUser = Depends(require_permission("ads.update")),
    db: Session = Depends(get_db),
):
    """批量改状态（≤100）。逐条执行，返回每条结果。"""
    from ..services.ad_ops import set_status
    if len(body.items) > 100:
        raise HTTPException(400, "批量操作上限 100 条")
    results = []
    for item in body.items[:100]:
        r = set_status(db, user.tenant_id, item.act_id, item.node_id, item.level, item.status, operator=user.email)
        results.append({"node_id": item.node_id, "level": item.level, **r})
    return {"results": results, "success_count": sum(1 for r in results if r.get("success"))}


@router.post("/budget")
def set_ad_budget(
    body: BudgetIn,
    user: CurrentUser = Depends(require_permission("ads.update")),
    db: Session = Depends(get_db),
):
    """改预算（本币金额→minor units，回读验证）。日预算/总预算二选一，对象类型必须匹配。"""
    from ..services.ad_ops import set_budget
    acc = db.query(Account).filter(
        Account.tenant_id == user.tenant_id, Account.act_id == body.act_id).first()
    cur = (acc.currency or "USD") if acc else "USD"
    r = set_budget(db, user.tenant_id, body.act_id, body.node_id, body.level,
                   daily_budget=body.daily_budget, lifetime_budget=body.lifetime_budget,
                   currency=cur, budget_type=body.budget_type, operator=user.email)
    if not r.get("success"):
        raise HTTPException(400, r.get("error", "操作失败"))
    return r


@router.post("/delete")
def delete_ad(
    body: DeleteIn,
    user: CurrentUser = Depends(require_permission("ads.delete")),
    db: Session = Depends(get_db),
):
    """硬删广告（DELETE /{id}，不可恢复）。"""
    from ..services.ad_ops import delete_node
    r = delete_node(db, user.tenant_id, body.act_id, body.node_id, operator=user.email)
    if not r.get("success"):
        raise HTTPException(400, r.get("error", "删除失败"))
    return r


# ── 广告级跳转链接覆盖（多广告复用一子码时，给单条广告配独立 target_url）──

class RedirectOverrideIn(BaseModel):
    ad_id: str
    target_url: str


@router.get("/redirects/map")
def redirects_map(
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """{ad_id: target_url} 映射，广告列表内联显示"已设跳转"用。"""
    from ..models.launch import AdRedirectOverride
    rows = db.query(AdRedirectOverride).filter(
        AdRedirectOverride.tenant_id == user.tenant_id).all()
    return {r.ad_id: r.target_url for r in rows}


@router.get("/redirects")
def list_redirects(
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """列出所有广告跳转覆盖（管理列表用）。"""
    from ..models.launch import AdRedirectOverride
    rows = db.query(AdRedirectOverride).filter(
        AdRedirectOverride.tenant_id == user.tenant_id
    ).order_by(AdRedirectOverride.updated_at.desc()).all()
    return [{"ad_id": r.ad_id, "target_url": r.target_url,
             "updated_at": r.updated_at.isoformat() if r.updated_at else ""} for r in rows]


@router.post("/redirects")
def set_redirect(
    body: RedirectOverrideIn,
    user: CurrentUser = Depends(require_permission("ads.update")),
    db: Session = Depends(get_db),
):
    """给某条广告设跳转链接覆盖（已有则更新；target_url 空则删除）。"""
    from ..models.launch import AdRedirectOverride
    from datetime import datetime, timezone
    if not body.ad_id:
        raise HTTPException(400, "缺 ad_id")
    target = (body.target_url or "").strip()
    row = db.query(AdRedirectOverride).filter(
        AdRedirectOverride.tenant_id == user.tenant_id,
        AdRedirectOverride.ad_id == body.ad_id,
    ).first()
    if not target:
        if row:
            db.delete(row); db.commit()
        return {"ad_id": body.ad_id, "cleared": True}
    if not target.startswith("http://") and not target.startswith("https://"):
        raise HTTPException(400, "跳转链接必须以 http:// 或 https:// 开头")
    if row:
        row.target_url = target
    else:
        row = AdRedirectOverride(tenant_id=user.tenant_id, ad_id=body.ad_id, target_url=target)
        db.add(row)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"ad_id": body.ad_id, "target_url": target}


@router.delete("/redirects/{ad_id}")
def delete_redirect(
    ad_id: str,
    user: CurrentUser = Depends(require_permission("ads.update")),
    db: Session = Depends(get_db),
):
    """删单条广告的跳转覆盖（恢复到子码/页默认）。"""
    from ..models.launch import AdRedirectOverride
    db.query(AdRedirectOverride).filter(
        AdRedirectOverride.tenant_id == user.tenant_id,
        AdRedirectOverride.ad_id == ad_id,
    ).delete()
    db.commit()
    return {"ad_id": ad_id, "cleared": True}


@router.post("/redirects/reset")
def reset_redirects(
    user: CurrentUser = Depends(require_permission("ads.update")),
    db: Session = Depends(get_db),
):
    """一键清空所有广告跳转覆盖（全部恢复落地页默认跳转）。"""
    from ..models.launch import AdRedirectOverride
    n = db.query(AdRedirectOverride).filter(
        AdRedirectOverride.tenant_id == user.tenant_id).delete()
    db.commit()
    return {"cleared": n}


@router.get("/{ad_id}/diagnose")
def diagnose_ad(
    ad_id: str,
    request: Request,
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """广告诊断：实时拉 FB 数据 + 落地数据 + 规则评估 + 冷却状态，返回完整诊断面板数据。"""
    loc = req_locale(request)
    from ..core.fb_tokens import client_for_account
    from ..core.fb_client import FbClient
    from ..core.encryption import decrypt
    from ..models.fb import Account
    from ..models.ads_cache import AdsCache
    from ..models.guard import GuardRule, GuardAllowance
    from ..models.launch import LandingAdLink
    from ..models.landing_event import LandingEvent
    from ..models.log import ActionLog
    from ..services.guard_engine import _evaluate_rule, RULE_DEFAULTS, _broader_conversions, COOLDOWN_MIN
    from ..services.kpi_resolver import resolve_kpi
    from ..services.ad_ops import from_minor_units
    from zoneinfo import ZoneInfo
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import func as _f, text as _ft
    import json as _json

    # 1. 找到这个广告属于哪个账户（反查表 5min 缓存——原每次诊断 json.loads 全部账户 ads_json）
    _ad_short = ad_id.replace("act_", "").strip()
    _act_id = _ad_act_lookup(db, user.tenant_id).get(_ad_short) or \
              _ad_act_lookup(db, user.tenant_id).get(ad_id)
    if not _act_id:
        raise HTTPException(404, "广告不在缓存中，请先刷新广告列表")

    acc = db.query(Account).filter(
        Account.tenant_id == user.tenant_id, Account.act_id == _act_id,
        Account.is_managed.is_(True)).first()
    if not acc:
        raise HTTPException(404, "账户未纳管或已移除")

    # 2. 初始化 result（先建，令牌不可用时也能返回部分数据）
    result = {
        "ad_id": _ad_short, "act_id": _act_id, "account_name": acc.name,
        "account_currency": acc.currency or "USD", "account_timezone": acc.timezone_name or "UTC",
        "fb_status": None, "fb_error": None, "spend": None, "spend_usd": None,
        "fb_conversions": 0, "fb_kpi_source": "", "fb_kpi_field": "", "target_cpa": None,
        "impressions": 0, "clicks": 0, "reach": 0,
        "landing_clicks": 0, "landing_visits": 0, "effective_conversions": 0,
        "conversion_source": "either", "landing_metric": "pass",
        "rules": [], "cooldown": None, "whitelisted": False, "recent_actions": [], "subcode": "",
    }

    # 3. 拉 FB 实时数据
    fb = client_for_account(db, user.tenant_id, _act_id, "read")
    if not fb:
        result["fb_error"] = L(loc, "ads.fbTokenUnavailable")

    tz = ZoneInfo(acc.timezone_name or "UTC")
    acc_today = datetime.now(tz).strftime("%Y-%m-%d")
    ad_insights = None
    fb_error = None
    try:
        if fb:
            ads = fb.get_ad_insights(_act_id, "today", 100, only_active=False, since=acc_today, until=acc_today)
            for a in ads:
                if str(a.get("ad_id", "")) == _ad_short or str(a.get("ad_id", "")) == ad_id:
                    ad_insights = a
                    break
    except Exception as e:
        result["fb_error"] = str(e)[:100]

    if ad_insights:
        from ..services.guard_engine import to_usd
        spend = float(ad_insights.get("spend", 0))
        result["fb_status"] = ad_insights.get("effective_status", "")
        result["spend"] = spend
        result["spend_usd"] = round(to_usd(spend, acc.currency or "USD"), 2)
        result["impressions"] = int(ad_insights.get("impressions", 0) or 0)
        result["clicks"] = int(ad_insights.get("clicks", 0) or 0)
        result["reach"] = int(ad_insights.get("reach", 0) or 0)

        # KPI 解析
        try:
            camp_id = ad_insights.get("campaign_id", "")
            obj = ad_insights.get("objective", "")
            kpi = resolve_kpi(db, user.tenant_id, camp_id, obj, "OFFSITE_CONVERSIONS", ad_insights.get("actions", []))
            result["fb_conversions"] = kpi["conversions"]
            result["fb_kpi_source"] = kpi.get("source", "")
            result["fb_kpi_field"] = kpi.get("kpi_field", "")
            result["target_cpa"] = kpi.get("target_cpa")
        except Exception:
            pass

    # 3. 落地页数据（账户本地日）
    _tz_name = acc.timezone_name or "UTC"
    _local_date_expr = _ft("(landing_events.created_at AT TIME ZONE 'UTC' AT TIME ZONE '{}')::date".format(_tz_name))
    try:
        result["landing_clicks"] = db.query(_f.count(_f.distinct(LandingEvent.ip_hash))).filter(
            LandingEvent.tenant_id == user.tenant_id,
            LandingEvent.ad_id == _ad_short,
            LandingEvent.event_type.in_(["click", "redirect"]),
            LandingEvent.ip_hash.isnot(None),
            _local_date_expr == acc_today,
        ).scalar() or 0
        result["landing_visits"] = db.query(_f.count(LandingEvent.id)).filter(
            LandingEvent.tenant_id == user.tenant_id,
            LandingEvent.ad_id == _ad_short,
            LandingEvent.event_type.in_(["visit", "redirect"]),
            _local_date_expr == acc_today,
        ).scalar() or 0
    except Exception:
        pass

    # 子码
    link = db.query(LandingAdLink).filter(LandingAdLink.ad_id == _ad_short).first()
    if link:
        result["subcode"] = link.slug

    # 4. 规则评估
    rules = db.query(GuardRule).filter(
        GuardRule.tenant_id == user.tenant_id, GuardRule.enabled == True).all()
    acc_rules = [r for r in rules if not r.scope_act_id or _act_id in [s.strip() for s in r.scope_act_id.split(",")]]

    fb_conv = result["fb_conversions"]
    landing_val = result["landing_clicks"]  # metric=pass 默认
    result["effective_conversions"] = max(fb_conv, landing_val) if landing_val > fb_conv else fb_conv

    if ad_insights:
        for rule in acc_rules:
            _params = _json.loads(rule.params) if rule.params else {}
            _cs = (rule.conversion_source or "either").lower()
            _lm = (_params.get("landing_metric") or "pass").lower()
            _lv = result["landing_clicks"] if _lm == "pass" else result["landing_visits"]
            _conv = fb_conv
            if _cs == "landing":
                _conv = _lv
            elif _cs == "either" and _lv > _conv:
                _conv = _lv

            # consecutive_bad 需要历史快照；budget_burn_fast 需要 prev_spend
            _history = None
            _prev_spend = None
            if rule.rule_type == "consecutive_bad":
                _hist_days = int(_params.get("param_days", 2))
                _since = (datetime.now(tz) - timedelta(days=_hist_days)).strftime("%Y-%m-%d")
                _history = db.query(PerfSnapshot).filter(
                    PerfSnapshot.ad_id == _ad_short,
                    PerfSnapshot.snapshot_date >= _since,
                    PerfSnapshot.snapshot_date < acc_today,
                ).order_by(PerfSnapshot.snapshot_date.desc()).all()
            if rule.rule_type == "budget_burn_fast":
                _prev = db.query(PerfSnapshot).filter(
                    PerfSnapshot.ad_id == _ad_short,
                    PerfSnapshot.snapshot_date == acc_today,
                ).first()
                _prev_spend = _prev.spend if _prev else None

            try:
                hit, detail = _evaluate_rule(rule, ad_insights, conversions=_conv,
                                             target_cpa=result["target_cpa"], currency=acc.currency or "USD",
                                             landing_clicks=result["landing_clicks"],
                                             landing_visits=result["landing_visits"],
                                             history=_history, prev_spend=_prev_spend)
            except Exception as e:
                hit, detail = False, f"评估异常: {e}"

            result["rules"].append({
                "rule_id": rule.id,
                "rule_name": rule.name,
                "rule_type": rule.rule_type,
                "conversion_source": _cs,
                "hit": hit,
                "detail": detail,
                "fb_conversions": fb_conv,
                "effective_conversions": _conv,
                "landing_clicks": result["landing_clicks"],
                "cpa": round(result["spend_usd"] / _conv, 2) if _conv and result["spend_usd"] else None,
            })

    result["conversion_source"] = (acc_rules[0].conversion_source if acc_rules else "either") or "either"

    # 5. 冷却状态
    now_utc = datetime.now(timezone.utc)
    succ_cd = now_utc - timedelta(minutes=COOLDOWN_MIN)
    for r in acc_rules:
        succ = db.query(ActionLog).filter(
            ActionLog.tenant_id == user.tenant_id,
            ActionLog.target_id == _ad_short,
            ActionLog.trigger_type == r.rule_type,
            ActionLog.action_type == "pause",
            ActionLog.result == "success",
            ActionLog.created_at >= succ_cd,
        ).first()
        if succ:
            cd_until = succ.created_at + timedelta(minutes=COOLDOWN_MIN)
            result["cooldown"] = {
                "rule": r.name,
                "rule_type": r.rule_type,
                "paused_at": succ.created_at.isoformat(),
                "cooldown_until": cd_until.isoformat(),
                "remaining_min": max(0, int((cd_until - now_utc).total_seconds() / 60)),
            }
            break

    # 6. 加白状态
    wl = db.query(GuardAllowance).filter(
        GuardAllowance.tenant_id == user.tenant_id,
        GuardAllowance.ad_id == _ad_short,
        GuardAllowance.allowance_date == acc_today,
        GuardAllowance.status == "active",
    ).first()
    result["whitelisted"] = bool(wl)

    # 7. 最近操作
    for r in db.query(ActionLog).filter(
        ActionLog.tenant_id == user.tenant_id,
        ActionLog.target_id == _ad_short,
    ).order_by(ActionLog.created_at.desc()).limit(5).all():
        result["recent_actions"].append({
            "time": r.created_at.isoformat() if r.created_at else "",
            "action": r.action_type,
            "trigger": r.trigger_type or "",
            "result": r.result or "",
            "detail": (r.trigger_detail or "")[:80],
        })

    return result
