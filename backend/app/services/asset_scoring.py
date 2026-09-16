"""素材评分（2026-09-16 设计定稿实施）。

数据链：assets.fb_image_hashes/fb_video_ids（{act_id: hash}）⨝ ads_cache 创意的
image_hash/video_id → asset_ad_links → perf_snapshots 聚合（唯一真源）。
评分 = 相对同租户基准（绝对值无跨行业可比性）：CTR 40% / 转化 30% / 置信 15% / 覆盖 15%。
无投放数据素材不评分（前端显示 AI 内容预估分并明确标注「预」）。
跟帖模式（object_story_id 引用帖子，无 hash）不参与匹配——口径如实排除。
"""
import json
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import text

log = logging.getLogger("toveads.asset_scoring")

# 评分窗口（北京业务日，与看板/日志同口径）
WINDOW_30D = 30
WINDOW_7D = 7


def sync_asset_ad_links(db, tenant_id: int) -> int:
    """hash 匹配回填 asset_ad_links（幂等，可反复跑）。返回本轮新增链接数。"""
    from ..models.launch import Asset
    from ..models.ads_cache import AdsCache
    from ..models.scoring import AssetAdLink  # noqa: F401 — 见文件底部说明（延迟导入本地表模型）

    assets = db.query(Asset).filter(
        Asset.tenant_id == tenant_id, Asset.status == "active").all()
    # 素材侧索引：{(act_id, kind, value): asset_id}
    key_map: dict[tuple, int] = {}
    for a in assets:
        for field, kind in ((a.fb_image_hashes, "image"), (a.fb_video_ids, "video")):
            if not field:
                continue
            try:
                m = json.loads(field)
            except Exception:
                continue
            for act_id, val in (m or {}).items():
                if val:
                    key_map[(str(act_id), kind, str(val))] = a.id

    existing = {(r.ad_id, r.platform) for r in db.query(AssetAdLink).filter(
        AssetAdLink.tenant_id == tenant_id).all()}
    added = 0
    for cache in db.query(AdsCache).filter(AdsCache.tenant_id == tenant_id).all():
        act = cache.act_id
        for ad in json.loads(cache.ads_json or "[]"):
            ad_id = str(ad.get("id") or "")
            if not ad_id or (ad_id, cache.platform or "fb") in existing:
                continue
            spec = ((ad.get("creative") or {}).get("object_story_spec") or {})
            cands = []
            ld = spec.get("link_data") or {}
            if ld.get("image_hash"):
                cands.append(("image", str(ld["image_hash"])))
            vd = spec.get("video_data") or {}
            if vd.get("video_id"):
                cands.append(("video", str(vd["video_id"])))
            for kind, val in cands:
                asset_id = key_map.get((act, kind, val))
                if asset_id:
                    # ON CONFLICT 幂等（复审P1：撞唯一约束曾致整租户评分永久瘫痪）
                    from sqlalchemy.dialects.postgresql import insert as _pg_insert
                    _stmt = _pg_insert(AssetAdLink).values(
                        tenant_id=tenant_id, asset_id=asset_id,
                        ad_id=ad_id, act_id=act, platform=cache.platform or "fb"
                    ).on_conflict_do_nothing(constraint="uq_asset_ad_links_ad")
                    db.execute(_stmt)
                    existing.add((ad_id, cache.platform or "fb"))
                    added += 1
                    break
    db.commit()
    return added


def _perf_agg(db, tenant_id: int, ad_ids: list[str], since_date: str):
    """聚合一批广告的 perf（北京日窗）。返回 dict 或 None（无数据）。"""
    rows = db.execute(text("""
        SELECT coalesce(sum(impressions),0), coalesce(sum(clicks),0),
               coalesce(sum(conversions),0), coalesce(sum(spend),0)
        FROM perf_snapshots
        WHERE tenant_id = :t AND ad_id = ANY(:ads) AND snapshot_date >= :d
    """), {"t": tenant_id, "ads": ad_ids, "d": since_date}).fetchone()
    if not rows or (rows[0] or 0) == 0 and (rows[3] or 0) == 0:
        return None
    imp, clk, cnv, spend = (float(rows[0] or 0), float(rows[1] or 0), float(rows[2] or 0), float(rows[3] or 0))
    return {"impressions": imp, "clicks": clk, "conversions": cnv, "spend": round(spend, 2),
            "ctr": (clk / imp * 100) if imp > 0 else 0.0,
            "cpa": (spend / cnv) if cnv > 0 else None}


def _bj_date(days_ago: int) -> str:
    bj = datetime.now(timezone(timedelta(hours=8)))
    return (bj - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def compute_asset_scores(db, tenant_id: int) -> int:
    """重算全租户素材评分（先 sync 链接）。返回参与评分的素材数。"""
    from ..models.launch import Asset
    from ..models.scoring import AssetAdLink, AssetScore

    sync_asset_ad_links(db, tenant_id)

    links = db.query(AssetAdLink).filter(AssetAdLink.tenant_id == tenant_id).all()
    by_asset: dict[int, list] = {}
    all_ad_ids: set[str] = set()
    for l in links:
        by_asset.setdefault(l.asset_id, []).append(l)
        all_ad_ids.add(l.ad_id)

    d30, d7, dprev7 = _bj_date(WINDOW_30D - 1), _bj_date(WINDOW_7D - 1), _bj_date(2 * WINDOW_7D - 1)
    ads_list = list(all_ad_ids) or ["-"]
    agg30 = _perf_agg(db, tenant_id, ads_list, d30)
    agg7 = _perf_agg(db, tenant_id, ads_list, d7)
    # 基准 = 租户内全部关联广告的加权（7 天窗——短期基准对素材迭代更有参考性）
    base_ctr = (agg7 or agg30 or {}).get("ctr") or 0
    base_cpa = (agg7 or agg30 or {}).get("cpa")

    assets = {a.id: a for a in db.query(Asset).filter(
        Asset.tenant_id == tenant_id, Asset.status == "active").all()}
    now = datetime.now(timezone.utc)
    scored = 0
    for asset_id, a in assets.items():
        row = db.query(AssetScore).filter(AssetScore.asset_id == asset_id).first()
        ls = by_asset.get(asset_id) or []
        stats = _perf_agg(db, tenant_id, [l.ad_id for l in ls] or ["-"], d30) if ls else None
        s7 = _perf_agg(db, tenant_id, [l.ad_id for l in ls] or ["-"], d7) if ls else None
        sprev7 = _perf_agg(db, tenant_id, [l.ad_id for l in ls] or ["-"], dprev7) if ls else None
        if not row:
            row = AssetScore(tenant_id=tenant_id, asset_id=asset_id)
            db.add(row)
        row.computed_at = now
        if not stats or (stats["impressions"] or 0) < 100 or ls == []:
            # 无投放数据/展示量太小：不评分（score=null 前端走 AI 预估位）
            row.score = None; row.grade = None; row.dims = None; row.stats = None
            continue
        scored += 1
        ctr = stats["ctr"]
        cnv, spend = stats["conversions"], stats["spend"]
        cpa = stats["cpa"]
        # 维度（相对基准：比值 1.0 → 50 分，2 倍基准 → 100）
        ctr_score = min(100, round(ctr / base_ctr * 50)) if base_ctr > 0 else 50
        if cnv > 0 and base_cpa and cpa and cpa > 0:
            conv_score = min(100, round(base_cpa / cpa * 50))
        elif cnv > 0:
            conv_score = 60
        else:
            conv_score = 10 if spend >= 20 else 25   # 花了钱没转化=低；钱少没转化=未知不重罚
        conf_score = 100 if spend >= 100 else 70 if spend >= 20 else 40 if spend >= 5 else 15
        n_ads = len({l.ad_id for l in ls})
        n_acts = len({l.act_id for l in ls})
        cov_score = min(100, n_ads * 25)
        total = round(0.4 * ctr_score + 0.3 * conv_score + 0.15 * conf_score + 0.15 * cov_score)
        grade = "S" if total >= 85 else "A" if total >= 70 else "B" if total >= 55 else "C" if total >= 40 else "D"
        trend = None
        if s7 and sprev7 and sprev7["impressions"] >= 1000 and s7["impressions"] >= 1000:
            t = s7["ctr"] - sprev7["ctr"]
            trend = "up" if t > 0.1 else ("down" if t < -0.1 else "flat")
        row.score = total
        row.grade = grade
        row.dims = json.dumps({"ctr": ctr_score, "conv": conv_score, "conf": conf_score, "cov": cov_score})
        row.stats = json.dumps({
            **stats, "ads_n": n_ads, "acts_n": n_acts, "trend": trend,
            "ctr_7d": (s7 or {}).get("ctr"), "base_ctr": round(base_ctr, 2),
            "base_cpa": round(base_cpa, 2) if base_cpa else None,
        }, ensure_ascii=False)
    db.commit()
    return scored


def maybe_recompute(db, tenant_id: int, max_age_h: int = 6):
    """列表前惰性重算（过期才跑）。advisory lock 防并发双跑（复审P1：两用户同开
    素材页曾会撞 uq_asset_scores 整体回滚）；拿不到锁=别人在算，直接跳过本请求。"""
    from ..models.scoring import AssetScore
    latest = db.query(AssetScore.computed_at).filter(
        AssetScore.tenant_id == tenant_id).order_by(AssetScore.computed_at.desc()).first()
    if not latest or not latest[0] or datetime.now(timezone.utc) - latest[0] > timedelta(hours=max_age_h):
        from ..core.database import acquire_run_lock, release_run_lock
        lock = acquire_run_lock(db, 120)   # try 模式：拿不到立即返回 None
        if not lock:
            return
        try:
            n = compute_asset_scores(db, tenant_id)
            log.info(f"[AssetScore] tenant={tenant_id} recomputed, scored={n}")
        except Exception as e:
            db.rollback()
            log.warning(f"[AssetScore] tenant={tenant_id} 重算失败（列表不带新分）: {e}")
        finally:
            release_run_lock(db, 120)
