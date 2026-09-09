"""广告管理器路由：读 ads_cache（巡检同步的缓存）+ perf_snapshots 消耗，跨账户汇总，0 FB。

对齐 FB Ads Manager：三层独立列表 + perf 聚合消耗。手动刷新（refresh=1）强制重拉。
"""
import json
import time
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from pydantic import BaseModel
from ..core.database import get_db
from ..core.deps import CurrentUser, require_permission
from ..core.i18n import req_locale, L
from ..core.fb_tokens import client_for_account
from ..core.fb_client import FbApiError
from ..core.tt_client import TtApiError
from ..models.perf import PerfSnapshot
from ..models.fb import Account
from ..models.ads_cache import AdsCache
from ..models.launch import LandingAdLink
from ..services.guard_engine import from_minor_units

router = APIRouter(prefix="/ads", tags=["ads"])


@router.post("/sync-cache")
def sync_ads_cache(background_tasks: BackgroundTasks,
                   user: CurrentUser = Depends(require_permission("ads.read"))):
    """手动触发广告实体缓存采集（后台跑 run_ads_cache_sync——自带 advisory lock 111，
    已在跑时重复触发自动 skip）。自动 15min 一次；此为手动即采（建了新广告后立即同步看效果）。"""
    from ..services.ads_cache_sync import run_ads_cache_sync
    background_tasks.add_task(run_ads_cache_sync)
    return {"started": True}


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
        if not lock:
            # 别的 worker 正在刷（pg_try 拿不到=已有人持有）——不重复跑，避免并发写同租户 cache
            _REFRESH_STATE[tenant_id] = {"running": False, "started_at": "", "done": 0, "total": 0}
            return
        db = SuperSessionLocal()
        # 平台分发（P0-3 的过滤止血已被 #2 取代）：FB/TT 账户都刷——client_for_account
        # 按账户 platform 返回 FbClient/TtClient，_sync_one 按平台归一后同构 upsert
        if act_id:
            accs = db.query(Account).filter(
                Account.tenant_id == tenant_id, Account.act_id == act_id).all()
        else:
            accs = db.query(Account).filter(
                Account.tenant_id == tenant_id, Account.is_managed == True,  # noqa: E712
                Account.account_status == 1).all()
        _REFRESH_STATE[tenant_id]["total"] = len(accs)
        for a in accs:
            fb = client_for_account(db, tenant_id, a.act_id, "read")
            if fb:
                _sync_one(db, tenant_id, a.act_id, fb, platform=_acc_platform(a),
                          currency=(a.currency or "USD"))
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
                    m[_aid] = (cr.act_id, cr.platform or "fb")  # 带 platform：诊断反查账户时消歧
        except Exception:
            continue
    _AD_ACT_MAP[tenant_id] = (now, m)
    if len(_AD_ACT_MAP) > 100:
        _AD_ACT_MAP.clear()
    return m


# FB 口径成效（results_fb）采集上线时刻：0093 迁移部署（0e1f61d，2026-09-08 23:46 CST）。
# 此前写入的快照行 results_fb 为迁移 server_default 0（非实测）。巡检每轮滚动刷新近 7 天
# 行并 bump updated_at，故 updated_at 晚于该时刻即代表该行由采集代码真实写入。
_FB_RESULTS_EPOCH = datetime(2026, 9, 8, 16, 0, tzinfo=timezone.utc)


def _perf_map(db: Session, tenant_id: int, act_id: str, date_from: str, date_to: str) -> dict:
    """ad 级 perf 聚合 → {ad_id: {spend(本币), spend_usd, conv, ...}}。act_id 空=跨账户全部。

    perf_snapshots.spend 巡检写入时已 to_usd 换算（USD），spend_native 是本币原值——
    跨账户 SUM(spend) 即为正确 USD 合计，无需再按币种换算；本币合计只在单广告（单账户单币种）内有意义。
    """
    q = db.query(PerfSnapshot.ad_id, func.sum(PerfSnapshot.spend), func.sum(PerfSnapshot.spend_native),
                 func.sum(PerfSnapshot.conversions),
                 func.sum(PerfSnapshot.impressions), func.sum(PerfSnapshot.clicks), func.sum(PerfSnapshot.reach),
                 func.sum(PerfSnapshot.results_fb), func.count(PerfSnapshot.results_fb),
                 func.count(PerfSnapshot.id), func.min(PerfSnapshot.updated_at),
                 PerfSnapshot.act_id, PerfSnapshot.platform).filter(
        PerfSnapshot.tenant_id == tenant_id)
    if act_id:
        q = q.filter(PerfSnapshot.act_id == act_id)
    if date_from:
        q = q.filter(PerfSnapshot.snapshot_date >= date_from)
    if date_to:
        q = q.filter(PerfSnapshot.snapshot_date <= date_to)
    rows = q.group_by(PerfSnapshot.ad_id, PerfSnapshot.act_id, PerfSnapshot.platform).all()
    out = {}
    for r in rows:
        usd = float(r[1] or 0)
        native = float(r[2] or 0)
        if native == 0 and usd > 0:
            native = usd  # 旧快照行缺 spend_native（列上线前写入）——按 USD 金额兜底展示
        _upd = r[10]
        if _upd is not None and _upd.tzinfo is None:
            _upd = _upd.replace(tzinfo=timezone.utc)
        # results_fb_available：范围内确有 FB 口径采集（非 0093 迁移默认 0）。任一行非零 → 真；
        # 否则要求全部行都晚于采集上线时刻（0093 部署 2026-09-09 00:00 CST）——更早的行
        # results_fb 是 server_default 0（迁移回填，非实测），不能冒充实测 0。TT 行无 FB 口径
        # 采集（报表 actions 非 FB 格式，恒 0）→ 恒 False，前端按缺失呈现并看综合转化列。
        _avail = ((r[12] or "fb") == "fb"
                  and (int(r[7] or 0) > 0
                       or (_upd is not None and _upd >= _FB_RESULTS_EPOCH)))
        out[(r[12] or "fb", str(r[11]), str(r[0]))] = {
            "spend": native, "spend_usd": usd, "conv": int(r[3] or 0),
            "impressions": int(r[4] or 0), "clicks": int(r[5] or 0), "reach": int(r[6] or 0),
            "results_fb": int(r[7] or 0), "results_fb_complete": r[8] == r[9],
            "results_fb_available": _avail,
            "metrics_updated_at": r[10].isoformat() if r[10] else None}
    return out


def _entity_key(item: dict, node_id=None):
    return (item.get("platform") or "fb", str(item.get("act_id")),
            str(_id_of(item.get("id") if node_id is None else node_id)))


def _attach_perf(items: list, perf_map: dict) -> list:
    out = []
    for it in items:
        p = perf_map.get(_entity_key(it), {"spend": 0.0, "spend_usd": 0.0, "conv": 0,
                                        "impressions": 0, "clicks": 0, "reach": 0})
        spend, usd, conv = p["spend"], p["spend_usd"], p["conv"]
        imp, clk, reach = p["impressions"], p["clicks"], p["reach"]
        fb = p.get("results_fb") if p.get("results_fb_complete") else None
        out.append({**it, "spend": round(spend, 2), "spend_usd": round(usd, 2), "conversions": conv,
                    "results_fb": fb, "results_fb_complete": fb is not None,
                    "results_fb_available": bool(p.get("results_fb_available")),
                    "metrics_updated_at": p.get("metrics_updated_at"),
                    "cost_per_result": round(spend / fb, 2) if fb else None,
                    "cost_per_result_usd": round(usd / fb, 2) if fb else None,
                    "cpa": round(spend / conv, 2) if conv else 0.0,
                    "cpa_usd": round(usd / conv, 2) if conv else 0.0,
                    "impressions": imp, "clicks": clk, "reach": reach,
                    "frequency": round(imp / reach, 2) if reach else 0.0,
                    "ctr": round(clk / imp * 100, 2) if imp else 0.0})
    return out


def _sync_one(db: Session, tenant_id: int, act_id: str, fb, platform: str = "fb",
              currency: str = "USD", include_ads: bool = True) -> bool:
    """拉单账户 campaigns/adsets[/ads] → upsert ads_cache。返回是否成功。

    platform='tt'：TtClient duck-type 同方法面拉原生行 → tt_to_fb_* 归一成 FB 形状
    （键名/状态/预算单位）再 upsert（platform='tt' 行）——/ads/list 与前端零平台分支。
    client_for_account 已按账户 platform 分发返回 FbClient/TtClient，这里只按参归一。
    include_ads=False（15min cron FB 路径）：不拉 /ads、不覆盖 ads_json——FB 广告层由
    巡检独家供数（每 5min 回写全状态，同 edge 重复拉是冗余）；TT 无巡检回写恒拉；
    手动刷新（refresh/live-status）走默认 True 保全量。
    """
    try:
        campaigns = fb.get_campaigns(act_id)
        adsets = fb.get_adsets(act_id, effective_status=None)
        ads = None
        if platform != "tt" and include_ads:
            # 广告层新鲜度跳过（批AE遗留）：巡检每 5min 回写全状态广告层——手动刷新时
            # 广告层 <5min 新就不重拉 /ads（3→2 次调用/账户，新鲜度等价）
            _r0 = db.query(AdsCache.ads_updated_at).filter(
                AdsCache.tenant_id == tenant_id, AdsCache.act_id == act_id,
                AdsCache.platform == platform).first()
            if _r0 and _r0[0] and (datetime.now(timezone.utc) - _r0[0]).total_seconds() < 300:
                include_ads = False
        if include_ads or platform == "tt":
            ads = fb.get_ads(act_id, effective_status=None)
    except (FbApiError, Exception):
        return False
    if platform == "tt":
        from ..core.tt_client import tt_to_fb_campaign, tt_to_fb_adset, tt_to_fb_ad
        campaigns = [tt_to_fb_campaign(c, currency) for c in campaigns]
        adsets = [tt_to_fb_adset(a, currency) for a in adsets]
        if ads is not None:
            ads = [tt_to_fb_ad(a, currency) for a in ads]
    # Row update time is also advanced by guard writeback; preserve a true
    # per-entity structure fetch time inside the existing JSON (no schema change).
    fetched_at = datetime.now(timezone.utc).isoformat()
    for entity in [*campaigns, *adsets]:
        entity["snapshot_at"] = fetched_at
    row = db.query(AdsCache).filter(
        AdsCache.tenant_id == tenant_id, AdsCache.act_id == act_id,
        AdsCache.platform == platform).first()
    if not row:
        row = AdsCache(tenant_id=tenant_id, act_id=act_id, platform=platform)
        db.add(row)
    row.campaigns_json = json.dumps(campaigns)
    row.adsets_json = json.dumps(adsets)
    if ads is not None:
        # 死广告不进 cache（与巡检回写同口径——用户明确不要归档/已删除）
        _live = [a for a in ads
                 if str((a.get("effective_status") or a.get("status") or "")).upper()
                 not in ("ARCHIVED", "DELETED")]
        row.ads_json = json.dumps(_live)
        row.ads_updated_at = datetime.now(timezone.utc)   # 广告层独立时间戳（0086）
    row.updated_at = datetime.now(timezone.utc)
    return True


def _managed_account(db: Session, user, act_id: str, platform: str = ""):
    """账户访问闸（批AG 权鉴修正）：is_managed + operator 只看名下（与 /fb/accounts 口径一致）。
    platform 非空时参与过滤（同 act_id 双平台共存时取对行）。返回 Account 或 None。"""
    from ..core.deps import account_operable
    q = db.query(Account).filter(
        Account.tenant_id == user.tenant_id, Account.act_id == act_id,
        Account.is_managed == True,  # noqa: E712
    )
    if platform:
        q = q.filter(Account.platform == platform)
    acc = q.first()
    if acc and not account_operable(user, acc):
        return None
    return acc


def _acc_platform(acc) -> str:
    """账户平台归一（'tt' → tt，空/历史缺省 → fb）。"""
    return "tt" if (getattr(acc, "platform", None) or "fb") == "tt" else "fb"


def patch_account_cache_status(db: Session, tenant_id: int, act_id: str, ad_id: str,
                               status: str, platform: str | None = None) -> bool:
    """单条广告状态写回 ads_cache（实时性消费侧，供 guard_engine/哨兵/规则暂停广告后调用，
    管理器立即可见新状态，不等 15min 全量同步）。

    - 只 patch ads_json 的 ad 行三键 status/effective_status/configured_status
      （语义与 services/ad_ops._patch_cache_status 一致，不跨文件依赖它）。
    - 不动 updated_at：它表示"上次全量同步时间"，状态 patch 是部分刷新，
      不伪造整行新鲜度（/ads/list 的 cache_age/last_sync 仍按全量同步计）。
    - platform 空=patch 该 act_id 全部平台行（FB/TT 的 ad_id 空间独立，按 ad_id 匹配天然消歧）。
    - 不 commit（调用方控制事务）。返回是否有行被实际改动。
    """
    rows = db.query(AdsCache).filter(
        AdsCache.tenant_id == tenant_id, AdsCache.act_id == act_id)
    if platform:
        rows = rows.filter(AdsCache.platform == platform)
    changed = False
    for row in rows.all():
        raw = row.ads_json
        if not raw:
            continue
        try:
            items = json.loads(raw)
        except Exception:
            continue
        row_changed = False
        for it in items:
            if isinstance(it, dict) and str(it.get("id") or "") == str(ad_id):
                it["status"] = status
                it["effective_status"] = status
                it["configured_status"] = status
                row_changed = True
        if row_changed:
            row.ads_json = json.dumps(items, ensure_ascii=False)
            changed = True
    return changed


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
    # 读缓存——只看 managed 账户（已移除的不显示广告）+ operator 只看名下（批AG 权鉴一致）
    from ..core.deps import scope_account_query
    _mg_q = scope_account_query(db.query(Account).filter(
        Account.tenant_id == user.tenant_id, Account.is_managed == True  # noqa: E712
    ), user)
    _acc_rows = _mg_q.all()
    managed_ids = {a.act_id for a in _acc_rows}
    q = db.query(AdsCache).filter(AdsCache.tenant_id == user.tenant_id)
    if act_id:
        q = q.filter(AdsCache.act_id == act_id)
    caches = [c for c in q.all() if c.act_id in managed_ids]
    # 账户名 + currency 映射（managed + 同归属口径，与上面同一查询结果）
    acc_map = {a.act_id: a.name for a in _acc_rows}
    cur_map = {a.act_id: (a.currency or "USD") for a in _acc_rows}
    # 合并三层（跨账户）+ 标 act_id/account_name/currency
    all_campaigns, all_adsets, all_ads = [], [], []
    ad_to_adset, ad_to_camp = {}, {}
    for c in caches:
        for cm in json.loads(c.campaigns_json or "[]"):
            cm["act_id"] = c.act_id; cm["account_name"] = acc_map.get(c.act_id, c.act_id)
            cm["currency"] = cur_map.get(c.act_id, "USD")
            cm["platform"] = c.platform or "fb"
            cm["snapshot_at"] = cm.get("snapshot_at")
            all_campaigns.append(cm)
        for as_ in json.loads(c.adsets_json or "[]"):
            as_["act_id"] = c.act_id; as_["account_name"] = acc_map.get(c.act_id, c.act_id)
            as_["currency"] = cur_map.get(c.act_id, "USD")
            as_["platform"] = c.platform or "fb"
            as_["snapshot_at"] = as_.get("snapshot_at")
            all_adsets.append(as_)
        for ad in json.loads(c.ads_json or "[]"):
            ad["act_id"] = c.act_id; ad["account_name"] = acc_map.get(c.act_id, c.act_id)
            ad["currency"] = cur_map.get(c.act_id, "USD")
            ad["platform"] = c.platform or "fb"
            ad_at = c.ads_updated_at or c.updated_at
            ad["snapshot_at"] = ad_at.isoformat() if ad_at else None
            if _id_of(ad.get("adset_id")):
                ad_to_adset[_entity_key(ad)] = _entity_key(ad, ad["adset_id"])
            if _id_of(ad.get("campaign_id")):
                ad_to_camp[_entity_key(ad)] = _entity_key(ad, ad["campaign_id"])
            all_ads.append(ad)
    # perf 跨账户 + adset/campaign 聚合（本币/USD 双列——跨币种 rollup 只有 USD 合计有意义）
    perf = _perf_map(db, user.tenant_id, act_id, date_from, date_to)
    adset_perf, camp_perf = {}, {}
    for ad_id, p in perf.items():
        for tgt, key in [(adset_perf, ad_to_adset.get(ad_id)), (camp_perf, ad_to_camp.get(ad_id))]:
            if not key:
                continue
            d = tgt.setdefault(key, {"spend": 0.0, "spend_usd": 0.0, "conv": 0,
                                     "impressions": 0, "clicks": 0, "reach": 0,
                                     "results_fb": 0, "results_fb_complete": True,
                                     "results_fb_available": True,
                                     "metrics_updated_at": None})
            d["spend"] += p["spend"]; d["spend_usd"] += p["spend_usd"]; d["conv"] += p["conv"]
            d["impressions"] += p["impressions"]; d["clicks"] += p["clicks"]; d["reach"] += p["reach"]
            d["results_fb"] += p["results_fb"]
            d["results_fb_complete"] = d["results_fb_complete"] and p["results_fb_complete"]
            # 父层口径可采：任一子广告缺实测 FB 口径 → 合计被默认 0 稀释，整体按不可用呈现
            d["results_fb_available"] = d["results_fb_available"] and p.get("results_fb_available", False)
            times = [v for v in (d["metrics_updated_at"], p["metrics_updated_at"]) if v]
            d["metrics_updated_at"] = min(times) if times else None
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
        # 批AM：综合转化=落地访问口径 max(FB, 落地访问)——「从广告真实进入落地页」即成效
        # （用户定义）；点击量（点了按钮）在「落地通过」列直观展示
        ad["conversions"] = max(int(ad.get("conversions") or 0), int(ad["landing_visits"] or 0))
        # 提取 creative 的 effective_object_story_id 供"复用此帖铺放"入口
        _cr = ad.get("creative")
        _sid = ""
        if isinstance(_cr, dict):
            _sid = _cr.get("effective_object_story_id") or ""
            if not _sid and isinstance(_cr.get("data"), list) and _cr["data"]:
                _sid = (_cr["data"][0] or {}).get("effective_object_story_id") or ""
        ad["object_story_id"] = _sid
        ad["slug"] = _slug_map.get(str(ad.get("id"))) or ""

    # 每账户读令牌可用性（纯 DB 查询 0 API）：false=数据源已断，前端对这类账户的状态标
    # 「快照」（cache 里的最后已知状态，非实时——令牌失效后 cache 停更，别误导"还在投放"）。
    # 按 platform 分发：FB 走 cred_for_account_op；TT 走 tt_client_for_account（FB 版对
    # platform='tt' 直接 raise，曾恒 True 漏标）。FB 的租户级 RR 兜底保留——巡检同一函数
    # 选令牌，兜底令牌拉得动就真会更新（同源判定自洽），拉不动 skip 告警会发声。
    from ..core.fb_tokens import cred_for_account_op as _cred_ok
    _token_status = {}
    for _a in _acc_rows:
        try:
            if _acc_platform(_a) == "tt":
                from ..core.fb_tokens import tt_client_for_account
                _token_status[_a.act_id] = bool(
                    tt_client_for_account(db, user.tenant_id, _a.act_id, "read")[0])
            else:
                _token_status[_a.act_id] = bool(
                    _cred_ok(db, user.tenant_id, _a.act_id, "read"))
        except Exception:
            _token_status[_a.act_id] = True   # 查询失败按可用（不误标快照）
    # cached_at/last_sync/cache_ages 全按 ads 层时间戳（0086：ads_updated_at，回退 updated_at）——
    # 用户在管理器看的核心是广告行，结构层（campaigns/adsets 15min sync 刷 updated_at）的新鲜
    # 不该冒充广告层新鲜（令牌切换间隙曾「缓存不到1分钟」配陈旧广告数据误导）。
    # 批K：令牌已断的账户 cache 恒冻结（拉不动）——把它算进「数据更新至」会让整页时间戳被
    # 僵尸账户钉死（Roly-V21 令牌过期后页头停在 9/8 06:36，用户连问多次）。死令牌账户的
    # 冻结状态由行内「快照」标+顶部警示条表达；全部账户都死时回退全量（仍给个时间）。
    # last_sync/cache_ages 是实时性戳：last_sync=最新一行的广告层时间（前端显示"数据 X 分钟前"）；
    # cache_ages=每账户缓存龄秒数（前端据此提示哪些账户该 live-status 核对）。
    def _ads_at(c):
        return getattr(c, "ads_updated_at", None) or c.updated_at
    # 批K v2：排除两类"数据断流"账户——①无可用令牌；②广告层数据龄 >1h（有兜底令牌但对
    # 该账户无权限/令牌过期，选得出令牌≠拉得动数据，Roly 实证：token_status=true 但 cache
    # 停更 23h）。正常链路最慢 15min 结构同步 + 5min 巡检，1h 未动=断流。全空回退全量。
    _t0 = datetime.now(timezone.utc)
    _agg_caches = []
    for c in caches:
        if not _token_status.get(c.act_id, True):
            continue
        _at = _ads_at(c)
        if _at:
            _u = _at if _at.tzinfo else _at.replace(tzinfo=timezone.utc)
            if (_t0 - _u).total_seconds() > 3600:
                continue
        _agg_caches.append(c)
    _agg_caches = _agg_caches or caches
    _cached_ats = [_ads_at(c) for c in _agg_caches if _ads_at(c)]
    _cache_ages: dict[str, int] = {}
    _now_utc = datetime.now(timezone.utc)
    for c in caches:
        _at = _ads_at(c)
        if not _at:
            continue
        _u = _at if _at.tzinfo else _at.replace(tzinfo=timezone.utc)
        _age = max(0, int((_now_utc - _u).total_seconds()))
        # 同 act_id 双平台行并存时取较新一行（最新数据口径）
        if c.act_id not in _cache_ages or _age < _cache_ages[c.act_id]:
            _cache_ages[c.act_id] = _age
    _curs = {cur_map.get(c.act_id, "USD") for c in caches}
    mixed_currency = len(_curs) > 1
    # 大图与缺图兜底：creative.image_hash → 原图直链（big_thumb）。
    # ①FB adimages 图片库反查（hash→原尺寸 CDN URL，账户级 1h 缓存）——覆盖系统/FB 侧建的
    #   全部广告；②本地素材兜底（Asset.fb_image_hashes → static-assets）。前端列表缩略图与
    #   点开大图统一用 big_thumb（thumbnail_url 只有 128px，弹窗放大是糊图）。
    try:
        import time as _time
        _ih_ads = []
        for ad in all_ads:
            _cr = ad.get("creative") or {}
            _ih = ((_cr.get("object_story_spec") or {}).get("link_data") or {}).get("image_hash")
            if _ih:
                ad["_ih"] = str(_ih)
                _ih_ads.append(ad)
        if _ih_ads:
            from ..models.launch import Asset
            from ..routers.assets import PUBLIC_BASE as _ASSET_BASE
            _urls: dict = {}
            # ① adimages（有缓存就 0 API；FB 调用失败静默走本地兜底）
            for _act in {a.get("act_id") for a in _ih_ads if a.get("act_id")}:
                _key = f"adimg:{user.tenant_id}:{_act}"
                _ent = _AGG_CACHE.get(_key)
                if _ent and _time.time() - _ent[0] < 3600:
                    _urls.update(_ent[1])
                    continue
                try:
                    _fb2 = client_for_account(db, user.tenant_id, _act, "read")
                    if _fb2:
                        _rows = _fb2.get_paged(f"act_{_act}/adimages",
                                               {"fields": "hash,url", "limit": "200"})
                        _m = {str(r.get("hash")): r.get("url")
                              for r in _rows if r.get("hash") and r.get("url")}
                        if _m:
                            _AGG_CACHE[_key] = (_time.time(), _m)
                            _urls.update(_m)
                except Exception:
                    continue
            # ② 本地素材兜底
            _local = {}
            for _ar in db.query(Asset).filter(
                Asset.tenant_id == user.tenant_id,
                Asset.fb_image_hashes.isnot(None),
            ).all():
                try:
                    _m = json.loads(_ar.fb_image_hashes or "{}")
                except Exception:
                    continue
                for _h in (_m or {}).values():
                    _local[str(_h)] = f"{_ASSET_BASE}/static-assets/{_ar.storage_key}"
            for ad in _ih_ads:
                _u = _urls.get(ad["_ih"]) or _local.get(ad["_ih"])
                if _u:
                    ad["big_thumb"] = _u
                    if not (ad.get("creative") or {}).get("thumbnail_url"):
                        ad["local_thumb"] = _u   # 兼容旧字段（前端 thumbOf 兜底链）
                ad.pop("_ih", None)
    except Exception:
        for ad in all_ads:
            ad.pop("_ih", None)
    return {
        "act_id": act_id, "date_from": date_from, "date_to": date_to,
        "cached_at": min(_cached_ats).isoformat() if _cached_ats else "",
        "last_sync": max(_cached_ats).isoformat() if _cached_ats else "",
        "cache_ages": _cache_ages,
        "token_status": _token_status,
        "refreshing": refreshing,
        "mixed_currency": mixed_currency,
        "currency": "USD" if mixed_currency else (next(iter(_curs)) if _curs else "USD"),
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
    """手动刷新 ads_cache（单账户 act_id 或全部）。FB/TT 平台分发（同 _bg_refresh）。"""
    if act_id:
        from ..core.deps import scope_account_query
        accs = scope_account_query(db.query(Account).filter(
            Account.tenant_id == user.tenant_id, Account.act_id == act_id), user).all()
    else:
        from ..core.deps import scope_account_query as _sc
        accs = _sc(db.query(Account).filter(
            Account.tenant_id == user.tenant_id, Account.is_managed == True,  # noqa: E712
            Account.account_status == 1), user).all()
    ok = 0
    for a in accs:
        fb = client_for_account(db, user.tenant_id, a.act_id, "read")
        if fb and _sync_one(db, user.tenant_id, a.act_id, fb, platform=_acc_platform(a),
                            currency=(a.currency or "USD")):
            ok += 1
    db.commit()
    return {"refreshed": ok, "total": len(accs)}


# live-status 同账户 10s 内存缓存（防连点/列表抖动重复打 FB；多 worker 各自一份，可接受）
_LIVE_STATUS_CACHE: dict = {}  # {f"{tenant_id}:{act_id}": (fetched_ts, resp)}
_DIAG_CACHE: dict = {}   # {f"{tenant_id}:{ad_id}": (ts, result)}——诊断面板 60s 响应缓存
_LIVE_STATUS_TTL = 10


@router.get("/live-status")
def ads_live_status(
    act_id: str = "",
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """单账户实时广告状态（轻量：id+name+effective_status，只读直连平台 API）。

    /ads/list 主体读 ads_cache（15min 全量同步）；本端点给前端"立即核对"单账户——
    哨兵/规则暂停后 cache 未回写时（审计 P1-2 消费侧兜底），前端可在此拉真状态。
    平台分发：FB get_ads 轻字段；TT get_ads 归一成 FB 形状（tt_to_fb_ad）。
    同账户 10s 内存缓存防连点。"""
    aid = (act_id or "").replace("act_", "").replace("ACT_", "").strip()
    if not aid:
        raise HTTPException(400, "缺 act_id")
    acc = _managed_account(db, user, aid)
    if not acc:
        raise HTTPException(404, "账户未纳管")
    _plat = _acc_platform(acc)
    _key = f"{user.tenant_id}:{aid}"
    _now_ts = time.time()
    from ..services.ad_ops import LIVE_STALE_MARKS   # 写路径失效标记（复审C P2）
    _ent = _LIVE_STATUS_CACHE.get(_key)
    # 写路径打过失效标记（刚暂停/改预算）→ 缓存作废重拉
    _stale = LIVE_STALE_MARKS.get(_key, 0.0)
    if _ent and _now_ts - _ent[0] < _LIVE_STATUS_TTL and _ent[0] > _stale:
        return {**_ent[1], "cached": True}
    client = client_for_account(db, user.tenant_id, aid, "read")
    if client is None:
        raise HTTPException(400, "该账户无可用读令牌")
    try:
        if _plat == "tt":
            from ..core.tt_client import tt_to_fb_ad
            rows = [tt_to_fb_ad(r, acc.currency or "USD") for r in client.get_ads(
                aid, effective_status=None,
                fields=["ad_id", "ad_name", "status", "opt_status", "show_status"])]
        else:
            rows = client.get_ads(aid, effective_status=None, fields="id,name,effective_status")
    except (FbApiError, TtApiError) as e:
        raise HTTPException(400, getattr(e, "friendly", str(e)))
    ads_out = [{"id": str(_id_of(r.get("id")) or ""), "name": r.get("name") or "",
                "effective_status": r.get("effective_status") or ""} for r in rows]
    resp = {"act_id": aid, "platform": _plat,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "count": len(ads_out), "ads": ads_out, "cached": False}
    if len(_LIVE_STATUS_CACHE) > 500:
        _LIVE_STATUS_CACHE.clear()
    _LIVE_STATUS_CACHE[_key] = (_now_ts, resp)
    return resp


# ── 细分（Breakdowns）：广告行按年龄/性别/版位拉 FB insights 分组（弹窗按需直连，0 缓存表）──

_BREAKDOWN_DIMS = {
    "age": "age",
    "gender": "gender",
    "placement": "publisher_platform,platform_position,impression_device",
    # 转化发生位置（FB 细分→按操作）：action 级维度，走 action_breakdowns 参数（非 breakdowns）
    "conversion_location": "conversion_destination",
}
_FB_DATE_PRESETS = {"today", "yesterday", "last_3d", "last_7d", "last_14d", "last_30d",
                    "last_90d", "this_month", "last_month", "maximum"}
# 弹窗结果 60s 内存缓存（防连点/切维度重复打 FB；refresh=1 绕过）
_BREAKDOWN_CACHE: dict = {}
_BREAKDOWN_CACHE_TTL = 60


@router.get("/insights/breakdown")
def ads_insights_breakdown(
    act_id: str = "",
    ad_id: str = "",
    dimension: str = "age",
    date_preset: str = "",
    date_from: str = "",
    date_to: str = "",
    refresh: int = 0,
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """单条广告的 FB insights 细分（age/gender/placement）。按需直连 FB（读令牌）。

    date_from/date_to 优先（与列表页日期筛选同源，账户本地日）；否则用 FB date_preset 白名单。
    TT 账户不支持（报表无 FB breakdowns 结构）。每行成效走 resolve_kpi（与列表 FB 口径同源）。
    """
    aid = (act_id or "").replace("act_", "").replace("ACT_", "").strip()
    dim = (dimension or "age").strip()
    _ad = str(ad_id or "").strip()
    if not aid or not _ad:
        raise HTTPException(400, "缺 act_id/ad_id")
    if dim not in _BREAKDOWN_DIMS:
        raise HTTPException(400, "不支持的细分维度")
    acc = _managed_account(db, user, aid)
    if not acc:
        raise HTTPException(404, "账户未纳管")
    if _acc_platform(acc) == "tt":
        raise HTTPException(400, "TikTok 账户暂不支持细分")
    fb = client_for_account(db, user.tenant_id, aid, "read")
    if not fb:
        raise HTTPException(400, "该账户无可用读令牌")

    key = f"bd:{user.tenant_id}:{aid}:{_ad}:{dim}:{date_preset}:{date_from}:{date_to}"
    _now = time.time()
    if not refresh:
        _ent = _BREAKDOWN_CACHE.get(key)
        if _ent and _now - _ent[0] < _BREAKDOWN_CACHE_TTL:
            return _ent[1]

    params = {
        "fields": "spend,impressions,clicks,ctr,reach,frequency,campaign_id,adset_id,actions",
        "limit": "100",
    }
    if dim == "conversion_location":
        params["action_breakdowns"] = "conversion_destination"
    else:
        params["breakdowns"] = _BREAKDOWN_DIMS[dim]
    if date_from and date_to:
        params["time_range"] = json.dumps({"since": date_from, "until": date_to})
    else:
        preset = (date_preset or "today").strip()
        if preset not in _FB_DATE_PRESETS:
            raise HTTPException(400, "不支持的日期预设")
        params["date_preset"] = preset
    try:
        rows = fb.get_paged(f"{_ad}/insights", params, limit=100)
    except FbApiError as e:
        raise HTTPException(400, getattr(e, "friendly", str(e)))

    # 目标反查（同 guard obj_map：AdsCache campaigns 的 objective——insights 行不请求该字段）
    obj_map = {}
    og_map = {}
    _cr = db.query(AdsCache).filter(
        AdsCache.tenant_id == user.tenant_id, AdsCache.act_id == aid,
        AdsCache.platform == "fb").first()
    if _cr:
        try:
            for c in json.loads(_cr.campaigns_json or "[]"):
                obj_map[str(_id_of(c.get("id")))] = c.get("objective") or ""
        except Exception:
            pass
        try:
            for st in json.loads(_cr.adsets_json or "[]"):
                og = (st.get("optimization_goal") or "").upper()
                if og and st.get("id"):
                    og_map[str(_id_of(st.get("id")))] = og
        except Exception:
            pass
    from ..services.kpi_resolver import resolve_kpi
    out = []
    if dim == "conversion_location":
        # action 级维度：消耗/展示等行级指标无法按转化位置拆分（FB 同口径——只拆成效），
        # 行内 actions 逐条过 resolve_kpi 判定是否计入成效口径，按 conversion_destination 分桶
        buckets: dict[str, int] = {}
        for r in rows:
            for a in (r.get("actions") or []):
                dest = str(a.get("conversion_destination") or "").strip() or "-"
                try:
                    kpi = resolve_kpi(db, user.tenant_id, r.get("campaign_id", ""),
                                      obj_map.get(str(r.get("campaign_id") or ""), ""),
                                      og_map.get(str(r.get("adset_id") or ""), ""), [a])
                    v = int(kpi.get("results_fb") or 0)
                except Exception:
                    v = 0
                if v:
                    buckets[dest] = buckets.get(dest, 0) + v
        for dest, v in sorted(buckets.items(), key=lambda x: -x[1]):
            out.append({"dimension_value": dest, "spend": None, "impressions": None,
                        "clicks": None, "ctr": None, "reach": None, "frequency": None,
                        "results": v})
        resp = {"act_id": aid, "ad_id": _ad, "dimension": dim,
                "currency": acc.currency or "USD",
                "date_from": date_from, "date_to": date_to, "date_preset": date_preset,
                "rows": out}
        _BREAKDOWN_CACHE[key] = (_now, resp)
        return resp
    for r in rows:
        try:
            kpi = resolve_kpi(db, user.tenant_id, r.get("campaign_id", ""),
                              obj_map.get(str(r.get("campaign_id") or ""), ""),
                              og_map.get(str(r.get("adset_id") or ""), ""),
                              r.get("actions") or [])
            results = int(kpi.get("results_fb") or 0)
        except Exception:
            results = 0
        if dim == "placement":
            label = " · ".join(str(r.get(k) or "")
                               for k in ("publisher_platform", "platform_position",
                                         "impression_device")).strip(" ·")
        else:
            label = str(r.get(dim) or "-")
        out.append({
            "dimension_value": label,
            "spend": round(float(r.get("spend") or 0), 2),
            "impressions": int(r.get("impressions") or 0),
            "clicks": int(r.get("clicks") or 0),
            "ctr": float(r.get("ctr") or 0),
            "reach": int(r.get("reach") or 0),
            "frequency": float(r.get("frequency") or 0),
            "results": results,
        })
    out.sort(key=lambda x: -x["spend"])
    resp = {"act_id": aid, "ad_id": _ad, "dimension": dim,
            "currency": acc.currency or "USD",
            "date_from": date_from, "date_to": date_to, "date_preset": date_preset,
            "rows": out}
    if len(_BREAKDOWN_CACHE) > 200:
        _BREAKDOWN_CACHE.clear()
    _BREAKDOWN_CACHE[key] = (_now, resp)
    return resp


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
    """改广告/组/系列状态（ACTIVE/PAUSED/ARCHIVED）。回读验证 + 缓存 patch。
    平台分发：TT 账户走 tt_set_status（opt_status 语义），FB 走原 set_status。"""
    from ..services.ad_ops import set_status_any
    # 只允许操作已纳管账户（P2-1：未纳管/已软删账户不应再被改状态）
    if not _managed_account(db, user, body.act_id):
        raise HTTPException(404, "账户未纳管")
    r = set_status_any(db, user.tenant_id, body.act_id, body.node_id, body.level, body.status, operator=user.email)
    if not r.get("success"):
        raise HTTPException(400, r.get("error", "操作失败"))
    return r


@router.post("/batch-status")
def batch_set_status(
    body: BatchStatusIn,
    user: CurrentUser = Depends(require_permission("ads.update")),
    db: Session = Depends(get_db),
):
    """批量改状态（≤100）。逐条异常隔离：任一条失败/异常不影响其余条目执行；每条统一返回
    act_id/node_id/level/success/verified，失败带 error。逐条按账户 platform 分发（FB/TT 可混批）。"""
    from ..services.ad_ops import set_status_any
    if len(body.items) > 100:
        raise HTTPException(400, "批量操作上限 100 条")
    results = []
    for item in body.items[:100]:
        entry = {"act_id": item.act_id, "node_id": item.node_id, "level": item.level,
                 "success": False, "verified": None}
        try:
            # is_managed 门（全库审查 P2）：单端点都有，批量曾绕过——软删账户广告仍可被批量操作
            if not _managed_account(db, user, item.act_id):
                entry["error"] = "account not managed"
            else:
                r = set_status_any(db, user.tenant_id, item.act_id, item.node_id,
                                   item.level, item.status, operator=user.email)
                entry.update({k: v for k, v in r.items() if k != "act_id"})
                entry["success"] = bool(r.get("success"))
                entry.setdefault("verified", None)
        except Exception as e:
            # 单条异常不拖垮整批：回滚该条未提交写入后继续（结果逐条带 error 回传，不静默）
            try:
                db.rollback()
                # rollback 会连同依赖注入时事务内的 set_config 一起回滚（RLS 租户上下文丢失，
                # rls-setconfig-rollback-pitfall）——必须重设，否则后续条目 RLS 下静默查空
                db.execute(text("SELECT set_config('app.tenant_id', :tid, false)"),
                           {"tid": str(user.tenant_id or "")})
                db.execute(text("SELECT set_config('app.is_superadmin', :s, false)"),
                           {"s": "true" if user.is_superadmin else "false"})
            except Exception:
                pass
            entry["error"] = str(e)[:200]
        results.append(entry)
    return {"results": results, "success_count": sum(1 for r in results if r.get("success"))}


@router.post("/budget")
def set_ad_budget(
    body: BudgetIn,
    user: CurrentUser = Depends(require_permission("ads.update")),
    db: Session = Depends(get_db),
):
    """改预算（本币金额→minor units，回读验证）。日预算/总预算二选一，对象类型必须匹配。
    平台分发：TT 账户走 tt_set_budget（整本币 int + 仅 adgroup 层），FB 走原 set_budget。"""
    from ..services.ad_ops import set_budget_any
    # 只允许操作已纳管账户（P2-1；原实现未纳管也能改预算）
    acc = _managed_account(db, user, body.act_id)
    if not acc:
        raise HTTPException(404, "账户未纳管")
    cur = acc.currency or "USD"
    r = set_budget_any(db, user.tenant_id, body.act_id, body.node_id, body.level,
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
    """硬删广告（FB：DELETE /{id}；TT：opt_status=DELETE 软删——TT 无硬删端点）。"""
    from ..services.ad_ops import delete_node_any
    # 只允许操作已纳管账户（P2-1：未纳管/已软删账户不应再被删广告）
    if not _managed_account(db, user, body.act_id):
        raise HTTPException(404, "账户未纳管")
    r = delete_node_any(db, user.tenant_id, body.act_id, body.node_id, operator=user.email)
    if not r.get("success"):
        raise HTTPException(400, r.get("error", "删除失败"))
    return r


class RenameIn(BaseModel):
    act_id: str
    node_id: str
    level: str = "ad"  # ad/adset/campaign
    name: str


@router.post("/rename")
def rename_ad_node(
    body: RenameIn,
    user: CurrentUser = Depends(require_permission("ads.update")),
    db: Session = Depends(get_db),
):
    """改名（campaign/adset/ad 通用，POST /{node_id} {"name"}）。ad_ops 同款：node 级 advisory
    lock + 回读验证 + ads_cache patch + SuperSessionLocal 审计。权限对齐 status/budget=ads.update。
    """
    import hashlib
    from ..core.database import SuperSessionLocal, acquire_run_lock, release_run_lock
    from ..core.log_utils import write_log, new_trace_id
    name = (body.name or "").strip()
    if not name or len(name) > 200:
        raise HTTPException(400, "名称不能为空且不超过 200 字符")
    if body.level not in ("ad", "adset", "campaign"):
        raise HTTPException(400, "level 必须是 ad/adset/campaign")
    # 平台分发：TT 账户走 services.ad_ops.tt_rename_node（各层端点与 name 字段名不同，
    # 广告主维度必带；锁/回读/cache patch/审计与下方 FB 内联版同构）。FB 路径原样保留。
    # is_managed 门（P2-1）：未纳管/已软删账户不可再操作。
    _acc = _managed_account(db, user, body.act_id)
    if not _acc:
        raise HTTPException(404, "账户未纳管")
    if (_acc.platform or "fb") == "tt":
        from ..services.ad_ops import tt_rename_node
        r = tt_rename_node(db, user.tenant_id, body.act_id, body.node_id, body.level, name,
                           operator=user.email)
        if not r.get("success"):
            raise HTTPException(400, r.get("error", "操作失败"))
        return r
    fb = client_for_account(db, user.tenant_id, body.act_id, "write")
    if not fb:
        raise HTTPException(400, "无可用写令牌（operate/manage）")
    lock_key = int(hashlib.md5(f"ad_rename:{body.node_id}".encode()).hexdigest()[:8], 16)
    lock = acquire_run_lock(lock_key)
    if not lock:
        raise HTTPException(409, "该对象正在被其他操作处理")
    try:
        before = fb.get_node(body.node_id, "id,name")
        fb.rename_node(body.node_id, name)
        time.sleep(0.8)
        after = fb.get_node(body.node_id, "id,name")
        verified = (after.get("name") or "").strip() == name
        # patch ads_cache（写后立即生效，不等 15min 同步；FB 分支只 patch platform=fb 行）
        row = db.query(AdsCache).filter(
            AdsCache.tenant_id == user.tenant_id, AdsCache.act_id == body.act_id,
            AdsCache.platform == "fb").first()
        if row:
            for field in ["campaigns_json", "adsets_json", "ads_json"]:
                raw = getattr(row, field)
                if not raw:
                    continue
                try:
                    items = json.loads(raw)
                    changed = False
                    for it in items:
                        if it.get("id") == body.node_id or str(it.get("id")) == str(body.node_id):
                            it["name"] = name
                            changed = True
                    if changed:
                        setattr(row, field, json.dumps(items))
                except Exception:
                    pass
        db.commit()
        _sdb = SuperSessionLocal()
        try:
            write_log(_sdb, tenant_id=user.tenant_id, trace_id=new_trace_id(),
                      actor_type="user", actor_user_id=0,
                      target_type="ad", target_id=body.node_id,
                      action_type="manual_rename", source="ad_ops",
                      result="success" if verified else "partial",
                      trigger_detail=f"level={body.level} old={before.get('name')} new={name}")
            _sdb.commit()
        finally:
            _sdb.close()
        return {"success": True, "verified": verified, "name": name}
    except FbApiError as e:
        return {"success": False, "error": e.friendly, "fb_error": e.friendly}
    finally:
        release_run_lock(lock, lock_key)


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
    from ..core.deps import scope_account_query
    _own = {a.act_id for a in scope_account_query(db.query(Account).filter(
        Account.tenant_id == user.tenant_id), user).all()}
    rows = db.query(AdRedirectOverride).filter(
        AdRedirectOverride.tenant_id == user.tenant_id).all()
    # 批AJ：operator 只见名下账户广告的跳转（ad→act 反查）
    if user.role == "operator":
        from ..models.ads_cache import AdsCache as _AC
        _ad2act = {}
        for c in db.query(_AC).filter(_AC.tenant_id == user.tenant_id).all():
            try:
                for _a in json.loads(c.ads_json or "[]"):
                    _aid = _id_of(_a.get("id")) if isinstance(_a, dict) else _a.get("id")
                    if _aid: _ad2act[str(_aid)] = c.act_id
            except Exception:
                continue
        rows = [r for r in rows if _ad2act.get(str(r.ad_id)) in _own]
    return {r.ad_id: r.target_url for r in rows}


@router.get("/redirects")
def list_redirects(
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """列出所有广告跳转覆盖（管理列表用）。"""
    from ..models.launch import AdRedirectOverride
    m = redirects_map(user=user, db=db)   # 批AJ：复用归属过滤（operator 只见名下）
    _vis = set(m.keys())
    rows = db.query(AdRedirectOverride).filter(
        AdRedirectOverride.tenant_id == user.tenant_id
    ).order_by(AdRedirectOverride.updated_at.desc()).all()
    return [{"ad_id": r.ad_id, "target_url": r.target_url,
             "updated_at": r.updated_at.isoformat() if r.updated_at else ""}
            for r in rows if str(r.ad_id) in _vis]


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
    _req_ad_gate(db, user, body.ad_id)   # 批AJ：operator 只能改名下账户广告的跳转
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
    _req_ad_gate(db, user, ad_id)   # 批AJ：归属闸
    db.query(AdRedirectOverride).filter(
        AdRedirectOverride.tenant_id == user.tenant_id,
        AdRedirectOverride.ad_id == ad_id,
    ).delete()
    db.commit()
    return {"ad_id": ad_id, "cleared": True}


def _req_ad_gate(db: Session, user, ad_id: str):
    """跳转端点归属闸（批AJ）：ad→act 反查（_AD_ACT_MAP 5min 缓存），operator 名下外 404。"""
    if getattr(user, "role", None) != "operator":
        return
    _act = _ad_act_lookup(db, user.tenant_id).get(str(ad_id))
    if not _act or not _managed_account(db, user, _act[0]):
        raise HTTPException(404, "广告不在你的名下账户")


@router.post("/redirects/reset")
def reset_redirects(
    user: CurrentUser = Depends(require_permission("ads.update")),
    db: Session = Depends(get_db),
):
    """一键清空所有广告跳转覆盖（全部恢复落地页默认跳转）。批AJ：operator 只清名下（曾可清全租户）。"""
    from ..models.launch import AdRedirectOverride
    _vis = set(redirects_map(user=user, db=db).keys())
    q = db.query(AdRedirectOverride).filter(AdRedirectOverride.tenant_id == user.tenant_id)
    if user.role == "operator":
        from sqlalchemy import or_
        if not _vis:
            return {"cleared": 0}
        q = q.filter(AdRedirectOverride.ad_id.in_(_vis))
    n = q.delete(synchronize_session=False)
    db.commit()
    return {"cleared": n}


@router.get("/{ad_id}/diagnose")
def diagnose_ad(
    ad_id: str,
    request: Request,
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """广告诊断：实时拉 FB 数据 + 落地数据 + 规则评估 + 冷却状态，返回完整诊断面板数据。
    整响应 60s 内存缓存（批AE遗留项）：面板重复打开/连点不重打 FB insights（1 次/分钟/广告）。"""
    _dck = f"{user.tenant_id}:u{user.id}:{ad_id}"   # 批AJ：键加用户域——owner 的缓存不得喂给 operator，且 fb_error 含 locale 互串
    _hit0 = _DIAG_CACHE.get(_dck)
    if _hit0 and time.time() - _hit0[0] < 60:
        return _hit0[1]
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
    _hit = _ad_act_lookup(db, user.tenant_id).get(_ad_short) or \
           _ad_act_lookup(db, user.tenant_id).get(ad_id)
    if not _hit:
        raise HTTPException(404, "广告不在缓存中，请先刷新广告列表")
    _act_id, _cache_plat = _hit  # (act_id, platform)——同 act_id 双平台可共存

    acc = _managed_account(db, user, _act_id, platform=_cache_plat)   # 批AJ：TT 分支同过归属闸（曾漏）
    if not acc:
        raise HTTPException(404, "账户未纳管或已移除")
    _plat = "tt" if (acc.platform or "fb") == "tt" else "fb"   # 快照/报表查询按账户实际平台

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
            if _plat == "tt":
                # TT get_ad_insights 签名（advertiser_id/date_preset/since/until/only_active/limit）
                # 与 FB 参数序不同——必须 kwargs，位置参数会把 limit 错位进 since
                ads = fb.get_ad_insights(_act_id, since=acc_today, until=acc_today, limit=100)
            else:
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
        if _plat == "tt":
            # TT 报表行不含投放状态——从 ads_cache（TT 归一形状，与管理器同源）回填
            _crow = db.query(AdsCache).filter(
                AdsCache.tenant_id == user.tenant_id, AdsCache.act_id == _act_id,
                AdsCache.platform == "tt").first()
            if _crow:
                for _a in json.loads(_crow.ads_json or "[]"):
                    if str(_a.get("id") or "") == _ad_short:
                        result["fb_status"] = _a.get("effective_status") or result["fb_status"]
                        break
        result["spend"] = spend
        result["spend_usd"] = (lambda u: round(u, 2) if u is not None else None)(to_usd(spend, acc.currency or "USD"))   # to_usd 未知币种返 None（guard_engine P0-2），None 安全传递
        result["impressions"] = int(ad_insights.get("impressions", 0) or 0)
        result["clicks"] = int(ad_insights.get("clicks", 0) or 0)
        result["reach"] = int(ad_insights.get("reach", 0) or 0)

        # KPI 解析（批I：FB 广告组优化目标优先——CTW/对话广告数会话不数点击；查不到回落
        # OFFSITE_CONVERSIONS 语义，与旧口径一致）
        try:
            camp_id = ad_insights.get("campaign_id", "")
            obj = ad_insights.get("objective", "")
            _diag_og = ""
            if _plat == "fb":
                _fcrow = db.query(AdsCache).filter(
                    AdsCache.tenant_id == user.tenant_id, AdsCache.act_id == _act_id,
                    AdsCache.platform == "fb").first()
                if _fcrow:
                    _og_map = {str(_id_of(s.get("id"))): (s.get("optimization_goal") or "").upper()
                               for s in json.loads(_fcrow.adsets_json or "[]") if s.get("id")}
                    _diag_og = _og_map.get(str(_id_of(ad_insights.get("adset_id"))), "")
            kpi = resolve_kpi(db, user.tenant_id, camp_id, obj,
                              _diag_og or "OFFSITE_CONVERSIONS", ad_insights.get("actions", []))
            result["fb_conversions"] = kpi["conversions"]
            result["fb_kpi_source"] = kpi.get("source", "")
            result["fb_kpi_field"] = kpi.get("kpi_field", "")
            result["target_cpa"] = kpi.get("target_cpa")
            if _plat == "tt" and ad_insights.get("conversions"):
                # TT 报表行自带 goal conversions（TT 侧已按 campaign 目标聚合）；resolver 无
                # actions 可解析时以其兜底——同 guard_engine 口径，防有转化的 TT 广告被当空耗误杀
                try:
                    _ttc = int(float(ad_insights.get("conversions") or 0))
                    if _ttc > result["fb_conversions"]:
                        result["fb_conversions"] = _ttc
                except (TypeError, ValueError):
                    pass
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
                    PerfSnapshot.platform == _plat,
                    PerfSnapshot.snapshot_date >= _since,
                    PerfSnapshot.snapshot_date < acc_today,
                ).order_by(PerfSnapshot.snapshot_date.desc()).all()
            if rule.rule_type == "budget_burn_fast":
                _prev = db.query(PerfSnapshot).filter(
                    PerfSnapshot.ad_id == _ad_short,
                    PerfSnapshot.platform == _plat,
                    PerfSnapshot.snapshot_date == acc_today,
                ).first()
                _prev_spend = _prev.spend if _prev else None

            try:
                hit, detail = _evaluate_rule(rule, ad_insights, conversions=_conv,
                                             kpi_field=result.get("fb_kpi_field") or "",   # 批AJ：kpi_scope 限定规则面板与引擎同口径
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

    if len(_DIAG_CACHE) > 500:
        _DIAG_CACHE.clear()
    _DIAG_CACHE[_dck] = (time.time(), result)
    return result
