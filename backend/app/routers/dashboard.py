"""看板路由：读 perf_snapshots 缓存表（秒开），不调 FB API（doc 08 + 1.0 架构移植）。

巡检引擎每 5min 写 perf_snapshots → 看板直接 SELECT → 毫秒级响应。
30s 内存缓存防 spam。支持 date_preset + date_from/date_to。
"""
import time as _time
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from ..core.database import get_db, SuperSessionLocal
from ..core.deps import CurrentUser, require_permission
from ..models.fb import Account
from ..models.perf import PerfSnapshot
from ..models.log import ActionLog
from ..models.guard import GuardAllowance

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# 30s 内存缓存（照搬 1.0 _SUMMARY_CACHE）
_CACHE = {}
_CACHE_TTL = 30

# 业务日基准：北京时区（UTC+8）——看数据用。
# snapshot_date 是账户本地日（和 FB insights 对齐），看板按业务日历日字符串查
# → WHERE snapshot_date='YYYY-MM-DD' 天然命中各账户本地该日，无需换算。
# （加白是另一套基准：账户本地当日，见 guard_engine._account_local_today。）
BUSINESS_TZ = timezone(timedelta(hours=8))


def _business_today() -> str:
    """业务今日（北京日历日 YYYY-MM-DD）。"""
    return datetime.now(BUSINESS_TZ).strftime("%Y-%m-%d")


@router.get("")
def dashboard(
    date_preset: str = "today",
    date_from: str = "",
    date_to: str = "",
    conversion_category: str = "",  # ① 转化分类筛选：全部/购物/私信/线索/互动/流量（只统计符合 KPI 类型的广告）
    act_ids: str = "",  # ③ 账户多选筛选：逗号分隔 act_id
    fresh: bool = False,  # 手动刷新跳过 30s 内存缓存（只读库，不触发 FB 采集）
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """汇总看板：读 perf_snapshots 缓存（秒开）。巡检 5min 刷新。

    date_preset: today/yesterday/last_7d/last_30d（快照表按 snapshot_date 过滤）
    date_from+date_to: 自定义范围（YYYY-MM-DD）
    """
    # 看数据按业务日（北京）；snapshot_date 是账户本地日，按业务日历日字符串查即命中各账户本地该日。
    today = _business_today()
    if date_from and date_to:
        since, until = date_from, date_to
    elif date_preset == "yesterday":
        y = (datetime.now(BUSINESS_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
        since = until = y
    elif date_preset == "last_2d":
        since = (datetime.now(BUSINESS_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")  # 昨天+今天 = 2 天
        until = today
    elif date_preset == "last_7d":
        since = (datetime.now(BUSINESS_TZ) - timedelta(days=6)).strftime("%Y-%m-%d")
        until = today
    elif date_preset == "last_30d":
        since = (datetime.now(BUSINESS_TZ) - timedelta(days=29)).strftime("%Y-%m-%d")
        until = today
    else:  # today
        since = until = today

    # 内存缓存（fresh=True 跳过：手动刷新只读库，绕 30s 缓存看最新快照）
    cache_key = f"{user.tenant_id}:{since}:{until}:{conversion_category}:{act_ids}"
    now = _time.time()
    if not fresh and cache_key in _CACHE:
        entry = _CACHE[cache_key]
        if now - entry[0] < _CACHE_TTL:
            return entry[1]

    # 查 perf_snapshots：按账户聚合（支持转化分类① + 账户多选③过滤）
    from sqlalchemy import bindparam
    KPI_CATEGORY = {
        "shopping": ["offsite_conversion.fb_pixel_purchase", "purchase", "omni_purchase",
                     "onsite_web_purchase", "web_in_store_purchase", "onsite_web_app_purchase"],
        "messaging": ["onsite_conversion.messaging_conversation_started_7d"],
        "leads": ["onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead"],
        "engagement": ["like", "post_engagement", "page_likes"],
        "traffic": ["link_click", "landing_page_view"],
    }
    sql_text = """
        SELECT act_id,
               MAX(act_id) as keep_act,
               SUM(spend) as total_spend_usd,
               SUM(spend_native) as total_spend_native,
               MAX(currency) as currency,
               SUM(conversions) as total_conversions,
               SUM(impressions) as total_impressions,
               SUM(clicks) as total_clicks,
               SUM(reach) as total_reach,
               AVG(frequency) as avg_frequency,
               AVG(ctr) as avg_ctr,
               AVG(cpc) as avg_cpc,
               AVG(roas) as avg_roas,
               MAX(updated_at) as last_synced
        FROM perf_snapshots
        WHERE tenant_id = :tid
          AND snapshot_date >= :since
          AND snapshot_date <= :until
    """
    params = {"tid": user.tenant_id, "since": since, "until": until}
    binds = []
    cat_fields = KPI_CATEGORY.get(conversion_category)
    if cat_fields:
        sql_text += "  AND resolved_kpi IN :cat_fields\n"
        params["cat_fields"] = cat_fields
        binds.append(bindparam("cat_fields", expanding=True))
    sel_ids = [s.strip() for s in act_ids.split(",") if s.strip()] if act_ids else []
    if sel_ids:
        sql_text += "  AND act_id IN :act_ids\n"
        params["act_ids"] = sel_ids
        binds.append(bindparam("act_ids", expanding=True))
    sql_text += "        GROUP BY act_id"
    stmt = text(sql_text)
    if binds:
        stmt = stmt.bindparams(*binds)
    rows = db.execute(stmt, params).fetchall()

    # 账户信息（余额等）
    accounts = db.query(Account).filter(Account.tenant_id == user.tenant_id).all()
    acc_map = {a.act_id: a for a in accounts}

    # 止损：按所选范围 + 归属到账户本地日（数据/事件同天统一）。
    # 拉宽 UTC 窗口（覆盖各账户时区偏移 ±1 天），再按账户本地日过滤到 [since, until]。
    from zoneinfo import ZoneInfo as _ZI
    def _act(detail):
        if not detail:
            return ""
        for seg in (detail or "").split("|"):
            s = seg.strip()
            if s.startswith("act="):
                return s[4:].split("(")[0].strip()
        return ""
    acc_tz = {a.act_id: (a.timezone_name or "UTC") for a in accounts}

    def _pause_local_day(p):
        try:
            return p.created_at.astimezone(_ZI(acc_tz.get(_act(p.trigger_detail), "UTC"))).date().isoformat()
        except Exception:
            return p.created_at.astimezone(timezone.utc).date().isoformat()

    _fetch_start = (datetime.strptime(since, "%Y-%m-%d") - timedelta(days=1)).replace(tzinfo=BUSINESS_TZ).astimezone(timezone.utc)
    _fetch_end = (datetime.strptime(until, "%Y-%m-%d") + timedelta(days=2)).replace(tzinfo=BUSINESS_TZ).astimezone(timezone.utc)
    _pause_cand = db.query(ActionLog).filter(
        ActionLog.tenant_id == user.tenant_id,
        ActionLog.action_type == "pause",
        ActionLog.result == "success",
        ActionLog.created_at >= _fetch_start,
        ActionLog.created_at < _fetch_end,
    ).order_by(ActionLog.created_at.desc()).limit(200).all()
    _pause_in_range = [p for p in _pause_cand if since <= _pause_local_day(p) <= until]
    pause_count = len(_pause_in_range)

    # 放行计数/明细：按各账户本地今日（多时区账户不能一刀切 UTC；和加白写入/巡检查询对齐）
    from ..services.guard_engine import _account_local_today
    local_today = {a.act_id: _account_local_today(a) for a in accounts}
    today_dates = set(local_today.values())  # 租户内各账户本地今日（通常 1~2 个）
    allow_cand = db.query(GuardAllowance).filter(
        GuardAllowance.tenant_id == user.tenant_id,
        GuardAllowance.status == "active",
        GuardAllowance.allowance_date.in_(today_dates),
    ).all() if today_dates else []
    today_allows = [a for a in allow_cand if local_today.get(a.act_id) == a.allowance_date]
    allowance_count = len(today_allows)

    # 止损明细（已按账户本地日过滤到 [since, until]，与快照同天）
    pause_details = [{
        "target_id": p.target_id, "trigger_type": p.trigger_type or "",
        "detail": (p.trigger_detail or "").split("|")[0].strip()[:80],
        "act_id": _act(p.trigger_detail),
        "time": p.created_at.isoformat() if p.created_at else "",
    } for p in _pause_in_range[:50]]

    # 放行明细（复用上面按账户本地今日过滤的结果）
    allowance_details = [{
        "act_id": a.act_id, "ad_id": a.ad_id,
        "account_name": (acc_map.get(a.act_id).name if acc_map.get(a.act_id) else a.act_id),
        "allowance_date": a.allowance_date,
        "timezone": (acc_map.get(a.act_id).timezone_name if acc_map.get(a.act_id) else ""),
        "is_cross_tz": local_today.get(a.act_id) != today,
    } for a in today_allows[:50]]

    # 汇总
    total_spend = sum(r.total_spend_usd or 0 for r in rows)
    total_conv = sum(r.total_conversions or 0 for r in rows)
    total_imp = sum(r.total_impressions or 0 for r in rows)
    total_clicks = sum(r.total_clicks or 0 for r in rows)
    total_reach = sum(r.total_reach or 0 for r in rows)
    total_cpa = round(total_spend / total_conv, 2) if total_conv > 0 else 0.0
    # 可用额度（照搬 1.0 _calc_available_balance：spend_cap - amount_spent，balance 不参与——
    # FB balance 是账单/欠款≠能花的钱；旧版 /25400 写死汇率且只对 VND，是 bug）
    from ..services.guard_engine import calc_available_balance, from_minor_units, to_usd
    def _money_native(val, cur):
        v = from_minor_units(val, cur)
        return round(v, 2) if v is not None else 0.0
    def _money_usd(val, cur):
        v = from_minor_units(val, cur)
        return round(to_usd(v, cur), 2) if v is not None else 0.0
    avail_map = {acc.act_id: calc_available_balance(acc.spend_cap, acc.amount_spent, acc.currency or "USD")
                 for acc in accounts}
    total_balance = sum(avail for avail, _k in avail_map.values() if avail is not None)
    unlimited_count = sum(1 for avail, _k in avail_map.values() if avail is None)

    # 最后同步时间
    last_synced = max((r.last_synced for r in rows if r.last_synced), default=None)

    # 账户明细
    account_details = []
    for r in rows:
        acc = acc_map.get(r.act_id)
        if not acc:
            # 账户已硬删（取消纳管前的旧行为）—— 仍展示其历史消耗，名字标"已移除"，
            # 让消耗明细对得上总额。accounts 表里没有这条，余额/状态字段留空。
            spend_usd = r.total_spend_usd or 0
            conv = r.total_conversions or 0
            account_details.append({
                "act_id": r.act_id, "name": "（已移除账户）", "currency": "USD", "timezone": "",
                "account_status": None, "is_managed": False, "removed": True,
                "spend": round(spend_usd, 2), "spend_usd": round(spend_usd, 2),
                "conversions": conv, "cpa": round(spend_usd / conv, 2) if conv > 0 else 0.0,
                "roas": round(float(r.avg_roas), 2) if r.avg_roas else 0.0,
                "impressions": r.total_impressions or 0, "clicks": r.total_clicks or 0,
                "reach": r.total_reach or 0,
                "frequency": round(float(r.avg_frequency), 2) if r.avg_frequency else 0.0,
                "ctr": round(float(r.avg_ctr), 2) if r.avg_ctr else 0.0,
                "cpc": round(float(r.avg_cpc), 2) if r.avg_cpc else 0.0,
                "balance": None, "balance_kind": "limited",
                "spend_cap": None, "amount_spent": None, "spend_cap_usd": None, "amount_spent_usd": None,
            })
            continue
        spend_usd = r.total_spend_usd or 0
        conv = r.total_conversions or 0
        cpa = round(spend_usd / conv, 2) if conv > 0 else 0.0
        account_details.append({
            "act_id": r.act_id, "name": acc.name, "currency": acc.currency or "USD", "timezone": acc.timezone_name or "",
            "account_status": acc.account_status, "is_managed": acc.is_managed if acc.is_managed is not None else True,
            "last_inspected_at": acc.last_inspected_at.isoformat() if acc.last_inspected_at else None,
            "spend": round(r.total_spend_native or 0, 2),
            "spend_usd": round(spend_usd, 2),
            "conversions": conv, "cpa": cpa,
            "roas": round(float(r.avg_roas), 2) if r.avg_roas else 0.0,
            "impressions": r.total_impressions or 0,
            "clicks": r.total_clicks or 0,
            "reach": r.total_reach or 0,
            "frequency": round(float(r.avg_frequency), 2) if r.avg_frequency else 0.0,
            "ctr": round(float(r.avg_ctr), 2) if r.avg_ctr else 0.0,
            "cpc": round(float(r.avg_cpc), 2) if r.avg_cpc else 0.0,
            "balance": avail_map[r.act_id][0],  # 可用额度 USD（None=无上限/超高）
            "balance_kind": avail_map[r.act_id][1],  # limited / unlimited / very_high_limit
            "spend_cap": _money_native(acc.spend_cap, acc.currency or "USD"),
            "amount_spent": _money_native(acc.amount_spent, acc.currency or "USD"),
            "spend_cap_usd": _money_usd(acc.spend_cap, acc.currency or "USD"),
            "amount_spent_usd": _money_usd(acc.amount_spent, acc.currency or "USD"),
        })

    # 加上没有快照但有账户的（error / 未产生数据）
    snap_acts = {r.act_id for r in rows}
    for acc in accounts:
        if acc.act_id not in snap_acts:
            # 区分：跨时区（账户本地日≠北京业务日，看板查不到属正常）vs 巡检未覆盖（同日但无快照，需关注）
            try:
                acc_local = _account_local_today(acc)
            except Exception:
                acc_local = today
            _recent = acc.last_inspected_at and acc.last_inspected_at > datetime.now(timezone.utc) - timedelta(minutes=15)
            if acc.account_status != 1:
                err = None  # 禁用/异常账户本就不巡检，不算巡检未覆盖（避免误报停滞）
            elif acc_local != today:
                err = f"跨时区（账户本地 {acc_local}，看板查 {today}）"
            elif _recent:
                err = None  # 已巡检但无活跃广告 = 正常，不算异常
            else:
                err = "巡检未覆盖"
            account_details.append({
                "act_id": acc.act_id, "name": acc.name, "currency": acc.currency or "USD", "timezone": acc.timezone_name or "",
                "account_status": acc.account_status, "is_managed": acc.is_managed if acc.is_managed is not None else True,
                "spend": 0, "spend_usd": 0, "conversions": 0, "cpa": 0, "roas": 0,
                "impressions": 0, "clicks": 0, "reach": 0, "frequency": 0,
                "ctr": 0, "cpc": 0,
                "balance": avail_map[acc.act_id][0],
                "balance_kind": avail_map[acc.act_id][1],
                "spend_cap": _money_native(acc.spend_cap, acc.currency or "USD"),
                "amount_spent": _money_native(acc.amount_spent, acc.currency or "USD"),
                "spend_cap_usd": _money_usd(acc.spend_cap, acc.currency or "USD"),
                "amount_spent_usd": _money_usd(acc.amount_spent, acc.currency or "USD"),
                "error": err,
            })

    # 巡检心跳（全局，绕 RLS——巡检是平台级服务，不按租户）
    _hb_db = SuperSessionLocal()
    try:
        _hb = _hb_db.query(ActionLog).filter(
            ActionLog.action_type == "inspection_heartbeat"
        ).order_by(ActionLog.id.desc()).first()
    finally:
        _hb_db.close()

    result = {
        "date_preset": date_preset or "custom",
        "total_spend": round(total_spend, 2),
        "total_conversions": total_conv,
        "total_cpa": total_cpa,
        "total_roas": round(sum(float(r.avg_roas or 0) for r in rows) / max(1, sum(1 for r in rows if r.avg_roas)), 2) if any(r.avg_roas for r in rows) else 0.0,
        "total_impressions": total_imp,
        "total_clicks": total_clicks,
        "total_reach": total_reach,
        "pause_count": pause_count,
        "pause_details": pause_details,
        "allowance_count": allowance_count,
        "allowance_details": allowance_details,
        "total_balance": round(total_balance, 2),
        "unlimited_count": unlimited_count,
        "accounts_count": len(accounts),
        "last_synced": str(last_synced) if last_synced else None,
        "last_heartbeat": str(_hb.created_at) if _hb else None,
        "next_inspection_in": "约5分钟（定时巡检）",
        "accounts": account_details,
    }

    _CACHE[cache_key] = (now, result)
    return result


@router.get("/trend")
def trend_data(
    date_preset: str = "last_7d",
    date_from: str = "",
    date_to: str = "",
    granularity: str = "",
    act_ids: str = "",
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """趋势折线数据。

    时间范围：跟看板一致（date_preset 或 date_from/date_to）。
    颗粒度：5min/30min/hour → perf_snapshot_ticks 聚合；day → perf_snapshots 聚合。
    """
    today = _business_today()
    if date_from and date_to:
        since, until = date_from, date_to
    else:
        days_map = {"today": 0, "last_2d": 1, "last_7d": 7, "last_30d": 30}
        days = days_map.get(date_preset, 7)
        since = (datetime.now(BUSINESS_TZ) - timedelta(days=days)).strftime("%Y-%m-%d")
        until = today
    sel_ids = [s.strip() for s in act_ids.split(",") if s.strip()] if act_ids else []

    # 颗粒度未指定 → 按范围自动选
    if not granularity:
        if since == until:
            granularity = "5min"
        elif (datetime.strptime(until, "%Y-%m-%d") - datetime.strptime(since, "%Y-%m-%d")).days <= 1:
            granularity = "hour"
        else:
            granularity = "day"

    if granularity == "day":
        sql = """
            SELECT snapshot_date, SUM(spend) as spend, SUM(conversions) as conversions
            FROM perf_snapshots
            WHERE tenant_id = :tid AND snapshot_date >= :since AND snapshot_date <= :until
        """
        params = {"tid": user.tenant_id, "since": since, "until": until}
        if sel_ids:
            sql += "  AND act_id IN :act_ids"
            params["act_ids"] = sel_ids
            stmt = text(sql + " GROUP BY snapshot_date ORDER BY snapshot_date").bindparams(bindparam("act_ids", expanding=True))
        else:
            stmt = text(sql + " GROUP BY snapshot_date ORDER BY snapshot_date")
        rows = db.execute(stmt, params).fetchall()
        labels, spend, conv, cpa = [], [], [], []
        for r in rows:
            s = round(float(r.spend or 0), 2)
            c = int(r.conversions or 0)
            # 日粒度标签 = snapshot_date（YYYY-MM-DD），前端截取显示
            labels.append(r.snapshot_date or "?")
            spend.append(s); conv.append(c)
            cpa.append(round(s / c, 2) if c > 0 else None)
        return {"labels": labels, "spend": spend, "conversions": conv, "cpa": cpa, "granularity": "day"}

    # ── tick 粒度（5min/30min/hour）──
    trunc_map = {"5min": "minute", "30min": "minute", "hour": "hour"}
    trunc = trunc_map.get(granularity, "hour")
    interval_min = {"5min": 5, "30min": 30, "hour": 60}.get(granularity, 60)
    # 用 date_trunc + 间隔分组（5min/30min 取 nearest bucket）
    bucket_expr = f"date_trunc('{trunc}', snapshot_at)" if trunc == "hour" else \
        f"to_timestamp(floor(extract(epoch from snapshot_at)/{interval_min*60})*{interval_min*60})"
    sql = f"""
        SELECT bucket, SUM(spend) as spend, SUM(conversions) as conversions FROM (
            SELECT DISTINCT ON (act_id, bucket) act_id, bucket, spend, conversions FROM (
                SELECT act_id, {bucket_expr} as bucket, snapshot_at, spend, conversions
                FROM perf_snapshot_ticks
                WHERE tenant_id = :tid AND snapshot_date >= :since AND snapshot_date <= :until
    """
    params = {"tid": user.tenant_id, "since": since, "until": until}
    if sel_ids:
        sql += "  AND act_id IN :act_ids"
        params["act_ids"] = sel_ids
        sql += "  ORDER BY act_id, bucket, snapshot_at DESC) d) latest GROUP BY bucket ORDER BY bucket"
        stmt = text(sql).bindparams(bindparam("act_ids", expanding=True))
    else:
        sql += "  ORDER BY act_id, bucket, snapshot_at DESC) d) latest GROUP BY bucket ORDER BY bucket"
        stmt = text(sql)
    rows = db.execute(stmt, params).fetchall()
    labels, raw_times, spend, conv, cpa = [], [], [], [], []
    for r in rows:
        b = r.bucket
        if not b:
            labels.append("?"); raw_times.append(None)
            spend.append(0); conv.append(0); cpa.append(None)
            continue
        # 返回原始 UTC 时间戳，前端用 fmtTime 按用户显示时区转
        raw_times.append(b.isoformat() if b else None)
        s = round(float(r.spend or 0), 2)
        c = int(r.conversions or 0)
        spend.append(s); conv.append(c)
        cpa.append(round(s / c, 2) if c > 0 else None)
    return {"labels": raw_times, "spend": spend, "conversions": conv, "cpa": cpa, "granularity": granularity}


@router.get("/ads")
def ad_breakdown(
    act_id: str,
    date_preset: str = "today",
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """单账户广告级（从 perf_snapshots 读，秒开）。看数据按业务日（北京），
    snapshot_date 是账户本地日，按业务日历日查即命中该账户本地该日。"""
    today = _business_today()
    rows = db.query(PerfSnapshot).filter(
        PerfSnapshot.tenant_id == user.tenant_id,
        PerfSnapshot.act_id == act_id,
        PerfSnapshot.snapshot_date == today,
    ).all()
    return {
        "act_id": act_id, "date_preset": date_preset,
        "ads": [{
            "ad_id": r.ad_id, "spend": r.spend, "spend_native": r.spend_native,
            "currency": r.currency, "conversions": r.conversions, "cpa": r.cpa,
            "roas": r.roas, "impressions": r.impressions, "clicks": r.clicks,
            "reach": r.reach, "frequency": r.frequency, "ctr": r.ctr, "cpc": r.cpc,
        } for r in rows],
    }


@router.get("/landing")
def landing_overview(
    date_preset: str = "today",
    date_from: str = "",
    date_to: str = "",
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """落地页数据看板：访问/通过/屏蔽/CPC，按子码(slug)聚合。

    口径（对齐 1.0，列含义在前端 tooltip 标注）：
      - 访问量 = event_type='visit'（到达落地页的有效访问，已通过防护）
      - 通过量 = event_type='click'（点 CTA 进入目标，≈ 1.0"通过=redirect"）
      - 屏蔽量 = event_type='block'（被防护规则拦截）
      - CPC = 广告消耗 ÷ 通过量(CTA点击)（落地 CPC，评估每个有效点击的成本）
    时间窗按业务日（北京）→ UTC（landing_events.created_at 是 UTC timestamptz；
    perf_snapshots.snapshot_date 是账户本地日，按业务日历日字符串匹配各账户本地该日）。
    """
    # 日期范围（北京业务日）
    today = _business_today()
    if date_from and date_to:
        since, until = date_from, date_to
    elif date_preset == "yesterday":
        y = (datetime.now(BUSINESS_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
        since = until = y
    elif date_preset == "last_2d":
        since = (datetime.now(BUSINESS_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
        until = today
    elif date_preset == "last_7d":
        since = (datetime.now(BUSINESS_TZ) - timedelta(days=6)).strftime("%Y-%m-%d")
        until = today
    elif date_preset == "last_30d":
        since = (datetime.now(BUSINESS_TZ) - timedelta(days=29)).strftime("%Y-%m-%d")
        until = today
    else:
        since = until = today
    # 业务日 → UTC 时间窗（landing_events.created_at）
    utc_start = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=BUSINESS_TZ).astimezone(timezone.utc)
    utc_end = datetime.strptime(until, "%Y-%m-%d").replace(tzinfo=BUSINESS_TZ).astimezone(timezone.utc) + timedelta(days=1)
    tid = user.tenant_id

    # ① 落地事件按子码聚合（访问/通过/屏蔽）
    #    访问 = visit + redirect（到达的有效访问，redirect 模式也算）
    #    通过 = redirect + click（到达目标：自动跳转 或 点了按钮）
    #    屏蔽 = block（被防护拦截）
    event_rows = db.execute(text("""
        SELECT e.slug, e.ad_id, MAX(e.act_id) AS act_id,
               MAX(lp.custom_domain) AS domain,
               SUM(CASE WHEN e.event_type IN ('visit','redirect') THEN 1 ELSE 0 END) AS visits,
               COUNT(DISTINCT CASE WHEN e.event_type IN ('redirect','click') THEN e.ip_hash END) AS clicks,
               SUM(CASE WHEN e.event_type='block' THEN 1 ELSE 0 END) AS blocked
        FROM landing_events e
        LEFT JOIN landing_pages lp ON lp.id = e.page_id
        WHERE e.tenant_id = :tid
          AND e.created_at >= :s
          AND e.created_at < :e
          AND e.slug IS NOT NULL
        GROUP BY e.slug, e.ad_id
        HAVING SUM(CASE WHEN e.event_type IN ('visit','redirect','click','block') THEN 1 ELSE 0 END) > 0
        ORDER BY visits DESC
        LIMIT 50
    """), {"tid": tid, "s": utc_start, "e": utc_end}).fetchall()

    # ② 广告消耗 by ad_id（业务日 snapshot_date 范围；perf_snapshots 是账户本地日）
    spend_rows = db.execute(text("""
        SELECT ad_id, SUM(spend) AS spend, SUM(conversions) AS conv
        FROM perf_snapshots
        WHERE tenant_id = :tid AND snapshot_date >= :since AND snapshot_date <= :until
        GROUP BY ad_id
    """), {"tid": tid, "since": since, "until": until}).fetchall()
    spend_map = {r.ad_id: (float(r.spend or 0), int(r.conv or 0)) for r in spend_rows}

    # ②b 账户名（子码表现展示该子码对应广告所属账户）
    #    事件带的 act_id 多是 FB 没填的字面量 {{account.id}} → 用 ad_id 反查真实 act_id：
    #    ads_cache（当前在投广告）+ perf_snapshots（历史快照，覆盖已下架/已删账户的广告）
    from ..models.fb import Account as _Acc
    from ..models.ads_cache import AdsCache as _AdsCache
    from ..models.perf import PerfSnapshot as _Perf
    import json as _json
    acc_map = {a.act_id: a.name for a in db.query(_Acc.act_id, _Acc.name).filter(_Acc.tenant_id == tid).all()}
    ad_act_map = {}  # ad_id -> act_id
    for _row in db.query(_AdsCache.act_id, _AdsCache.ads_json).filter(_AdsCache.tenant_id == tid).all():
        try:
            for _ad in _json.loads(_row.ads_json or "[]"):
                if _ad.get("id"):
                    ad_act_map[str(_ad["id"])] = _row.act_id
        except Exception:
            continue
    # perf_snapshots 兜底：历史广告（含已删账户的）也有 act_id
    for _r in db.query(_Perf.ad_id, _Perf.act_id).filter(_Perf.tenant_id == tid, _Perf.ad_id.isnot(None)).distinct().all():
        if _r.ad_id:
            ad_act_map.setdefault(str(_r.ad_id), _r.act_id)
    def _resolve_acc(act_id, ad_id):
        aid = act_id if (act_id and "{{" not in str(act_id)) else ad_act_map.get(str(ad_id) if ad_id else "")
        return (aid or ""), (acc_map.get(aid, "") if aid else "")

    # ③ 屏蔽明细分布（reason / country / platform 各 top 8；field 为白名单硬编码，无注入）
    def _block_top(field: str):
        return [{"key": r.k, "count": r.cnt} for r in db.execute(text(f"""
            SELECT COALESCE({field}, '未知') AS k, COUNT(*) AS cnt
            FROM landing_events
            WHERE tenant_id = :tid AND event_type = 'block'
              AND created_at >= :s AND created_at < :e
            GROUP BY k ORDER BY cnt DESC LIMIT 8
        """), {"tid": tid, "s": utc_start, "e": utc_end}).fetchall()]
    block_detail = {
        "by_reason": _block_top("reason"),
        "by_country": _block_top("country"),
        "by_platform": _block_top("platform"),
    }

    # ④ 合并 + 派生 CPC/CVR/通过率/屏蔽率/决策态
    rows = []
    t_visits = t_clicks = t_blocked = t_conv = 0
    t_spend = 0.0
    for r in event_rows:
        spend, conv = spend_map.get(r.ad_id, (0.0, 0))
        visits, clicks, blocked = int(r.visits or 0), int(r.clicks or 0), int(r.blocked or 0)
        t_visits += visits; t_clicks += clicks; t_blocked += blocked
        t_spend += spend; t_conv += conv
        _act, _acc = _resolve_acc(r.act_id, r.ad_id)
        if conv > 0:
            state = "good"
        elif spend > 0 and conv == 0:
            state = "waste"
        elif visits > 0 or clicks > 0:
            state = "watch"
        else:
            state = "no_data"
        rows.append({
            "slug": r.slug, "ad_id": r.ad_id, "act_id": _act,
            "account": _acc,
            "domain": r.domain,
            "visits": visits, "clicks": clicks, "blocked": blocked,
            "pass_rate": round(clicks / visits * 100, 1) if visits else None,        # 通过率=CTA点击率
            "block_rate": round(blocked / (visits + blocked) * 100, 1) if (visits + blocked) else None,
            "spend_usd": round(spend, 2), "conversions": conv,
            "cpc": round(spend / clicks, 2) if clicks else None,                     # 落地 CPC=消耗÷CTA点击
            "cvr": round(conv / clicks * 100, 2) if clicks else None,
            "state": state,
        })

    total_req = t_visits + t_blocked
    return {
        "date_preset": date_preset or "custom",
        "totals": {
            "visits": t_visits, "clicks": t_clicks, "blocked": t_blocked,
            "pass_rate": round(t_clicks / t_visits * 100, 1) if t_visits else None,
            "block_rate": round(t_blocked / total_req * 100, 1) if total_req else None,
            "spend_usd": round(t_spend, 2), "conversions": t_conv,
            "cpc": round(t_spend / t_clicks, 2) if t_clicks else None,
        },
        "rows": rows,
        "block_detail": block_detail,
    }
