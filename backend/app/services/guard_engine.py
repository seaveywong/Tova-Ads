"""巡检引擎（doc 03 §2）：定时读 FB insights → 匹配规则 → 停广告 → 记日志+通知。

核心流程：遍历租户 → 取规则 → 取账户 → 读 insights → 评估 → 命中则停。
dry_run=True 时不真停（只记日志 + 通知），用于首次验证。
"""
import json
import logging
import time
import html
from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from ..core.database import SuperSessionLocal, acquire_run_lock, release_run_lock
from ..core.encryption import decrypt
from ..core.fb_client import FbClient, FbApiError
from ..core.log_utils import write_log, new_trace_id
from ..core.notify_utils import emit_notification, emit_token_expired_if_due, dedup_recent
from ..services.kpi_resolver import resolve_kpi, SOURCE_LABELS
from ..core.fb_tokens import client_for_account, cred_for_account_op, mark_cred_cooldown
from ..models.ads_cache import AdsCache


def _esc(s) -> str:
    """TG HTML 转义（用户提供的广告/账户名可能含 <>&，避免破坏 parse_mode=HTML）。"""
    return html.escape(str(s if s is not None else ""))
from ..models.guard import GuardRule, GuardAllowance
from ..models.fb import FbCredential, Account
from ..models.log import ActionLog
from ..models.perf import PerfSnapshot, PerfSnapshotTick

# 告警/暂停冷却（分钟）—— 同一 ad+rule 在冷却内不重复告警/暂停（防通知 spam）
COOLDOWN_MIN = 60

logger = logging.getLogger("toveads.guard")

# 规则类型 → 客户面类别（doc 03 §2.1，8 类止损规则）
RULE_CATEGORY = {
    "bleed_abs": "空耗止损", "click_no_conv": "空耗止损", "reach_no_conv": "空耗止损",
    "low_ctr_no_conv": "空耗止损", "budget_burn_fast": "空耗止损",
    "cpa_exceed": "成本超标", "trend_drop": "效果下滑", "consecutive_bad": "效果下滑",
}

# 默认参数（审计项目9：8 规则默认值表）
RULE_DEFAULTS = {
    "bleed_abs":        {"spend_threshold": 20},
    "cpa_exceed":       {"cpa_target": 8, "ratio": 1.3},
    "click_no_conv":    {"min_clicks": 50},
    "low_ctr_no_conv":  {"min_spend": 10, "max_ctr": 0.5},   # min_spend=USD, max_ctr=百分比
    "reach_no_conv":    {"reach_threshold": 1000, "min_spend": 10},
    "trend_drop":       {"drop_threshold": 40},               # ROAS 下滑百分比
    "consecutive_bad":  {"param_days": 2, "ratio": 1.3, "cpa_target": 8},
    "budget_burn_fast": {"threshold_abs": 20},                # 两轮巡检间消耗增量 USD
}


def _campaign_objectives(fb, campaign_ids) -> dict:
    """批量取 {campaign_id: (objective, optimization_goal)}（FB ?ids=batch 单次，省 N→1 请求）。"""
    ids = list(dict.fromkeys(cid for cid in campaign_ids if cid))  # 去重保序
    out = {}
    if not ids:
        return out
    # FB ?ids=cid1,cid2 一次拉（每批最多 50）
    for i in range(0, len(ids), 50):
        batch = ids[i:i + 50]
        try:
            data = fb.get("", {"ids": ",".join(batch), "fields": "id,objective,optimization_goal"})
            if isinstance(data, dict):
                for cid, c in data.items():
                    if isinstance(c, dict):
                        out[cid] = ((c.get("objective") or "").upper(), (c.get("optimization_goal") or "").upper())
        except Exception:
            # batch 失败 → 逐个 fallback（保可用性）
            for cid in batch:
                if cid in out:
                    continue
                try:
                    c = fb.get(cid, {"fields": "id,objective,optimization_goal"})
                    out[cid] = ((c.get("objective") or "").upper(), (c.get("optimization_goal") or "").upper())
                except Exception:
                    out[cid] = ("", "")
    for cid in ids:
        out.setdefault(cid, ("", ""))
    return out


def _account_local_today(acc) -> str:
    """账户本地今日（YYYY-MM-DD），用 timezone_name。"""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(acc.timezone_name or "UTC")).strftime("%Y-%m-%d")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _max_history_days(rules: list) -> int:
    """需要拉多少天历史快照（consecutive_bad 的 param_days 最大值）。"""
    n = 0
    for r in rules:
        if r.rule_type == "consecutive_bad":
            try:
                n = max(n, int((json.loads(r.params) or {}).get("param_days", 2)))
            except Exception:
                n = max(n, 2)
    return n


def _evaluate_rule(rule: GuardRule, ad_insights: dict, conversions: int = 0,
                   target_cpa: float | None = None, yesterday_insight: dict | None = None,
                   prev_spend: float | None = None, history: list | None = None,
                   currency: str = "USD", landing_clicks: int = 0,
                   landing_visits: int = 0) -> tuple[bool, str]:
    """评估单条规则对单条广告。返回 (命中, 命中详情)。

    conversions：FB 转化数（KPI resolver，目标感知）。
    landing_clicks：落地通过量（click+redirect，按钮点击/跳转）。
    landing_visits：落地访问量（visit+redirect，到达量，含未点击）。
    conversion_source（rule）：fb/landing/either。
    landing_metric（rule params）：pass（通过量，默认）/ visit（访问量）。
    """
    # 转化归因：按规则 conversion_source + landing_metric 取 effective conversions
    cs = (getattr(rule, "conversion_source", None) or "either").lower()
    raw_params = json.loads(rule.params) if rule.params else {}
    landing_metric = (raw_params.pop("landing_metric", None) or "pass").lower()
    # landing 侧取哪个指标：pass=通过量(click+redirect) / visit=访问量(visit+redirect)
    landing_val = landing_clicks if landing_metric == "pass" else landing_visits
    # CPA 类规则不受 either 稀释（落地点击≠购买，CPA 必须按真实转化算）
    # 空耗类规则用 either 防误杀（有点击说明不是纯空耗）
    if cs == "landing":
        conversions = landing_val
    elif cs == "either" and landing_val > conversions:
        conversions = landing_val
    raw_params = {k: v for k, v in raw_params.items() if v not in (None, "", [])}
    defaults = RULE_DEFAULTS.get(rule.rule_type, {})
    p = {**defaults, **raw_params}
    spend = float(ad_insights.get("spend", 0))
    spend_usd = to_usd(spend, currency)
    clicks = int(ad_insights.get("clicks", 0))
    impressions = int(ad_insights.get("impressions", 0))
    reach = int(ad_insights.get("reach", 0))
    rt = rule.rule_type

    if rt == "bleed_abs":
        threshold = float(p.get("spend_threshold", 20))
        if spend_usd >= threshold and conversions == 0:
            # BLEED_ABORT 守卫（23）：broader_conv>0 不触发（防 KPI 字段错配误杀有转化的广告）
            if _broader_conversions(ad_insights.get("actions", [])) > 0:
                return False, ""
            return True, f"空耗 {fmt_spend(spend, currency)}（阈值 ${threshold}）"
        return False, ""

    if rt == "cpa_exceed":
        target = target_cpa if target_cpa else float(p.get("cpa_target", 8))  # KPI target_cpa 优先
        ratio = float(p.get("ratio", 1.3))
        if conversions > 0:
            cpa_usd = spend_usd / conversions
            if cpa_usd > target * ratio:
                tgt = f"KPI ${target}" if target_cpa else f"${target}"
                return True, f"CPA ≈${cpa_usd:.2f} 超目标 {tgt}×{ratio}（{fmt_spend(spend, currency)}/{conversions}转化）"
        return False, ""

    if rt == "click_no_conv":
        min_clicks = int(p.get("min_clicks", 50))
        if clicks >= min_clicks and conversions == 0:
            return True, f"{clicks} 次点击（阈值 {min_clicks} 次）"
        return False, ""

    if rt == "low_ctr_no_conv":
        min_spend = float(p.get("min_spend", 10))
        max_ctr = float(p.get("max_ctr", 0.5))
        ctr = float(ad_insights.get("ctr", 0) or 0)
        if spend_usd >= min_spend and impressions >= 100 and conversions == 0 and ctr <= max_ctr:
            return True, f"CTR {ctr:.2f}%≤{max_ctr}% / 空 {fmt_spend(spend, currency)}"
        return False, ""

    if rt == "reach_no_conv":
        reach_threshold = int(p.get("reach_threshold", 1000))
        min_spend = float(p.get("min_spend", 10))
        if reach >= reach_threshold and spend_usd >= min_spend and conversions == 0:
            return True, f"触达 {reach}≥{reach_threshold} / 空 {fmt_spend(spend, currency)}"
        return False, ""

    if rt == "trend_drop":
        threshold = float(p.get("drop_threshold", 40))
        y = yesterday_insight or {}
        y_roas = float(y.get("purchase_roas") or 0)
        t_roas_raw = ad_insights.get("purchase_roas")
        if y_roas > 0 and t_roas_raw is not None:
            t_roas = float(t_roas_raw)
            drop = (y_roas - t_roas) / y_roas * 100
            if drop >= threshold:
                return True, f"ROAS 下滑 {drop:.0f}%（昨 {y_roas:.2f}→今 {t_roas:.2f}，阈值 {threshold}%）"
        return False, ""

    if rt == "budget_burn_fast":
        threshold = float(p.get("threshold_abs", 20))
        if prev_spend is not None:
            delta_usd = spend_usd - to_usd(prev_spend, currency)
            if delta_usd >= threshold:
                return True, f"瞬烧 ≈${delta_usd:.2f}（上轮→今 {fmt_spend(spend, currency)}，阈值 ${threshold}）"
        return False, ""

    if rt == "consecutive_bad":
        days = int(p.get("param_days", 2))
        ratio = float(p.get("ratio", 1.3))
        target = target_cpa if target_cpa else float(p.get("cpa_target", 8))
        rows = history or []
        if len(rows) >= days:
            over = [r for r in rows if (r.cpa or 0) > 0 and r.cpa > target * ratio]
            if len(over) >= days:
                return True, f"连续 {days} 天 CPA > ${target}×{ratio}"
        return False, ""

    # 未知规则类型
    return False, ""


class _DefaultBleedRule:
    """规则兜底：账户/租户无任何规则时注入的默认空耗止血线（保底防裸奔）。
    用户配了任何规则 → acc_rules 非空 → 不注入（用户优先）。
    阈值 $20 固定；用户想改 → 建自己的 bleed_abs 规则覆盖（acc_rules 非空即接管）。"""
    rule_type = "bleed_abs"
    params = json.dumps({"spend_threshold": 20})
    conversion_source = "fb"
    action = "pause"
    name = "默认空耗止血（兜底$20）"
    scope_act_id = None


_DEFAULT_BLEED_ABS_RULE = _DefaultBleedRule()


def run_inspection():
    """巡检主函数。遍历所有租户，评估规则，命中按 rule.action 动作。

    动作由 rule.action 唯一控制（observe=只告警 / pause=停广告 / pause_adset=停组 /
    pause_campaign=停系列）——无全局 dry_run（2026-07-07 用户决策）。
    规则作用域：全局(scope_act_id NULL=名下所有账户) + 账户级(scope_act_id=指定账户)，并存各评估。
    多 worker：advisory lock 保证每轮只有一个 worker 真跑（防 TG spam）。
    """
    lock = acquire_run_lock(101)
    if not lock:
        return {"skipped": "lock_busy"}
    db = SuperSessionLocal()
    trace_id = new_trace_id()
    total_evaluated = 0
    total_hits = 0
    total_paused = 0
    total_skipped_spend = 0  # 有消耗但被 active_ids 过滤掉的广告数（覆盖丢失，止损盲区）
    paused_details = []  # [{act_id, ad_id, ad_name, level, target, reason}]

    try:
        # 取所有有 active 凭证的租户（不只 guard_rules——租户无规则也巡检，注入保底止血线，防裸奔）
        tenant_ids = db.query(FbCredential.tenant_id).filter(
            FbCredential.status == "active"
        ).distinct().all()

        for (tenant_id,) in tenant_ids:
            all_rules = db.query(GuardRule).filter(
                GuardRule.tenant_id == tenant_id,
                GuardRule.enabled == True,
            ).all()
            if not all_rules:
                # 规则兜底：租户无规则时注入默认空耗止血线（保底防裸奔，用户可建规则覆盖）
                all_rules = [_DEFAULT_BLEED_ABS_RULE]

            # 取本租户所有 active 凭证 → {cred_id: FbClient}（多 token，按账户绑定的 token 选）
            creds = db.query(FbCredential).filter(
                FbCredential.tenant_id == tenant_id,
                FbCredential.status == "active",
            ).all()
            if not creds:
                logger.info(f"[Guard] 租户 {tenant_id} 无 FB 凭证，跳过")
                continue
            # 取已纳管账户（is_managed=true 且 ACTIVE=1，跳过被 FB 禁用/宽限/违规的，省 Token 配额；
            # 也跳过已取消纳管的软删账户——它们保留历史但不再巡检）
            accounts = db.query(Account).filter(
                Account.tenant_id == tenant_id,
                Account.account_status == 1,
                Account.is_managed.is_(True),
            ).all()

            hist_days = _max_history_days(all_rules)  # consecutive_bad 需要的历史天数

            for acc in accounts:
                acc.last_inspected_at = datetime.now(timezone.utc)
                # 预热中账户跳过巡检（doc 03 §6 warmup 豁免——新账户保护期不停）
                if (acc.warmup_state or "none") == "warming":
                    continue
                # 按账户选 token（查 cooldown + op_kind=read + RR 兜底）；全灭 → 跳过
                cred = cred_for_account_op(db, tenant_id, acc.act_id, "read")
                if not cred:
                    continue
                fb = FbClient(decrypt(cred.access_token_enc))
                acc_today = _account_local_today(acc)  # 账户本地日（time_range 拉 insights + 写 snapshot_date，统一账户本地基准，避免跨时区累积）
                # 拿 ACTIVE 广告 ID 集（排除已停/被拒/删除的；含学习中的——学习中但 ACTIVE = 在花钱）
                try:
                    active_ads = fb.get_active_ads(acc.act_id)
                    active_ids = {a.get("id") for a in active_ads}
                except Exception:
                    active_ids = None  # FB API 拉失败，下面用 ads_cache 兜底
                # ads_cache 兜底：FB API 失败 或 补充过滤——只评估 effective_status=ACTIVE 的广告
                # 避免"已停广告还有今日消耗 → 重复告警"的幽灵告警
                if active_ids is None or len(active_ids) == 0:
                    try:
                        import json as _json_cache
                        _cache_row = db.query(AdsCache).filter(
                            AdsCache.tenant_id == tenant_id, AdsCache.act_id == acc.act_id).first()
                        if _cache_row:
                            _cache_ids = {str(_a.get("id")) for _a in
                                          _json_cache.loads(_cache_row.ads_json or "[]")
                                          if _a.get("effective_status") == "ACTIVE"}
                            if _cache_ids:
                                active_ids = _cache_ids
                                logger.info(f"[Guard] 账户 {acc.act_id} 用 ads_cache 兜底: {len(_cache_ids)} ACTIVE")
                    except Exception:
                        pass
                try:
                    ads = fb.get_ad_insights(acc.act_id, "today", 50, only_active=False, since=acc_today, until=acc_today)
                except FbApiError as e:
                    logger.warning(f"[Guard] 账户 {acc.act_id} 读 insights 失败: {e.friendly}")
                    _cred = cred
                    _alias = (_cred.alias if _cred else "") or ""
                    if e.category == "token_expired":
                        if _cred:
                            _cred.status = "expired"
                        emit_token_expired_if_due(db, tenant_id, _alias)
                    elif e.category in ("permissions", "permission"):
                        # 权限不足告警（交接包 §6.2：分级告警）。dedup 6h/账户，避免每轮巡检 spam
                        if not dedup_recent(db, tenant_id, "account_permission_error", acc.act_id, 360):
                            emit_notification(db, tenant_id=tenant_id, level="critical",
                                event_type="account_permission_error",
                                title=f"权限不足 · {_esc(acc.name)}",
                                body=f"账户：{_esc(acc.name)}（<code>{acc.act_id}</code>）\n"
                                     f"令牌：{_esc(_alias or '未命名')}\n"
                                     f"读取失败：<b>{_esc(e.friendly)}</b>\n"
                                     f"该令牌可能缺少广告读取权限，请重新授权。")
                            write_log(db, tenant_id=tenant_id, trace_id=trace_id, actor_type="system",
                                target_type="account", target_id=acc.act_id,
                                action_type="account_permission_error", source="guard",
                                result="fail", trigger_detail=f"act_id={acc.act_id} alias={_alias}")
                            db.commit()
                    elif e.category == "rate_limited":
                        # 限流：写冷却（下轮 client_for_account 跳过该 token）+ 告警
                        if _cred:
                            mark_cred_cooldown(db, _cred.id, minutes=30, status="rate_limited")
                        _rid = str(_cred.id) if _cred else acc.act_id
                        if not dedup_recent(db, tenant_id, "token_rate_limited", _rid, 60):
                            _affected = [a.name for a in db.query(Account).filter(
                                Account.fb_credential_id == cred.id).all()] if cred else []
                            emit_notification(db, tenant_id=tenant_id, level="warning",
                                event_type="token_rate_limited",
                                title=f"令牌限流 · {_esc(_alias or acc.act_id)}",
                                body=f"令牌：<b>{_esc(_alias or '未命名')}</b>\n读取被限流，30 分钟后自动恢复，或换其他令牌\n"
                                     f"影响账户：{_esc('、'.join(_affected[:10]) or '无')}")
                            write_log(db, tenant_id=tenant_id, trace_id=trace_id, actor_type="system",
                                target_type="fb_credential", target_id=_rid,
                                action_type="token_rate_limited", source="guard",
                                result="fail", trigger_detail=f"act_id={acc.act_id} alias={_alias}")
                            db.commit()
                    # fill forward：FB 拉失败时复制上一轮 tick，避免趋势消耗因漏采掉线
                    try:
                        _lt = db.query(PerfSnapshotTick).filter(
                            PerfSnapshotTick.act_id == acc.act_id,
                        ).order_by(PerfSnapshotTick.snapshot_at.desc()).first()
                        if _lt:
                            db.add(PerfSnapshotTick(
                                tenant_id=tenant_id, act_id=acc.act_id, snapshot_date=_lt.snapshot_date,
                                snapshot_at=datetime.now(timezone.utc),
                                spend=_lt.spend, conversions=_lt.conversions, cpa=_lt.cpa, roas=_lt.roas,
                            ))
                            db.commit()
                    except Exception:
                        pass
                    continue
                # 建 ads_cache ACTIVE 广告集（覆盖丢失告警用：区分"真盲区"vs"已停广告有历史消耗"）
                _cache_active_set = None
                try:
                    _cr = db.query(AdsCache).filter(
                        AdsCache.tenant_id == tenant_id, AdsCache.act_id == acc.act_id).first()
                    if _cr and _cr.ads_json:
                        _cache_active_set = {str(_a.get("id")) for _a in json.loads(_cr.ads_json)
                                             if _a.get("effective_status") == "ACTIVE"}
                except Exception:
                    pass
                # 昨日 insights（trend_drop 用；无 trend_drop 规则可跳过省 API 调用）
                yesterday_map: dict[str, dict] = {}
                if any(r.rule_type == "trend_drop" for r in all_rules):
                    try:
                        yest = (datetime.strptime(acc_today, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
                        for yad in fb.get_ad_insights(acc.act_id, "yesterday", 50, since=yest, until=yest):
                            yesterday_map[yad.get("ad_id", "")] = yad
                    except FbApiError:
                        pass  # 昨日读取失败不阻断今日评估
                # snapshot_date 用账户本地日（和 FB insights time_range 一致，账户本地基准）
                biz_today = acc_today
                # 取本账户广告涉及的 campaign objective（KPI 转化提取用，一次巡检缓存）
                obj_map = _campaign_objectives(fb, {ad.get("campaign_id") for ad in ads})
                # 该账户适用规则：全局(scope_act_id NULL) + 本账户(scope_act_id==acc.act_id)，并存各评估
                acc_rules = [r for r in all_rules if r.scope_act_id is None
                             or acc.act_id in [s.strip() for s in (r.scope_act_id or "").split(",")]]
                # 规则兜底：该账户无任何规则覆盖（如用户只配了别的账户级规则）→ 注入保底止血
                if not acc_rules:
                    acc_rules = [_DEFAULT_BLEED_ABS_RULE]

                # 趋势 tick 累计：本账户本次巡检所有 ACTIVE 广告的 spend/conv 总和（ad 循环后写一条聚合 tick）
                acc_tick_spend = 0.0
                acc_tick_conv = 0

                for ad in ads:
                    ad_id = ad.get("ad_id", "")
                    # tick spend + conv 累计所有广告（含已暂停——累计值不因暂停下降）
                    try:
                        acc_tick_spend += to_usd(float(ad.get("spend", 0)), acc.currency)
                        _obj_all = obj_map.get(ad.get("campaign_id", ""), ("", ""))
                        _kpi_all = resolve_kpi(db, tenant_id, ad.get("campaign_id", ""),
                                               _obj_all[0], _obj_all[1], ad.get("actions", []))
                        acc_tick_conv += int(_kpi_all["conversions"] or 0)
                    except Exception:
                        pass
                    # 过滤：只评估 ACTIVE 广告（拉了 active_ids 就用它；None=不过滤）
                    if active_ids is not None and ad_id not in active_ids:
                        # 有消耗却被过滤掉 = 覆盖丢失。但区分：
                        #   真盲区 = 广告在 ads_cache 里是 ACTIVE 但 active_ids 没拉到 → 告警
                        #   误报 = 广告已暂停/被拒（有历史消耗但不 ACTIVE）→ 不告警
                        try:
                            if float(ad.get("spend", 0) or 0) > 0:
                                # 查 ads_cache 看这广告当前状态
                                _ad_active = True  # 默认保守（cache 查不到=未知=可能active=告警）
                                if _cache_active_set is not None:
                                    _ad_active = ad_id in _cache_active_set
                                if _ad_active:
                                    total_skipped_spend += 1  # ACTIVE 但被漏掉 = 真盲区
                        except Exception:
                            pass
                        continue  # 已停/被拒/删除的广告跳过（用户：准备中/学习中 ACTIVE 就纳入）
                    ad_objective, ad_opt_goal = obj_map.get(ad.get("campaign_id", ""), ("", ""))
                    ad_name = ad.get("ad_name", ad_id)[:50]
                    total_evaluated += 1
                    spend = float(ad.get("spend", 0))
                    # KPI resolver：目标感知转化数 + target_cpa（审计项目10/11）
                    try:
                        kpi = resolve_kpi(db, tenant_id, ad.get("campaign_id", ""),
                                          ad_objective, ad_opt_goal, ad.get("actions", []))
                        conv = kpi["conversions"]
                        target_cpa = kpi["target_cpa"]
                    except Exception as e:
                        logger.warning(f"[Guard] KPI 解析异常 ad={ad_id}: {e}")
                        conv, target_cpa = 0, None
                        kpi = {"kpi_field": "", "source": "error"}
                    # 落地页侧转化数（conversion_source landing/either 用）
                    # landing_metric 配置取"通过"还是"访问"：
                    #   pass = click+redirect（按钮点击/跳转通过量，用户真实意向）
                    #   visit = visit+redirect（落地页到达量，含未点击的）
                    landing_clicks = 0
                    landing_visits = 0
                    if any((r.conversion_source or "either") in ("landing", "either") for r in acc_rules):
                        try:
                            from ..models.landing_event import LandingEvent
                            from sqlalchemy import func as _f, text as _ft
                            # 按账户本地日过滤（created_at 存 UTC，转成本地时区再取日期，和 FB insights 对齐）
                            _tz = acc.timezone_name or "UTC"
                            _local_date_expr = _ft("({} AT TIME ZONE 'UTC' AT TIME ZONE '{}')::date".format(
                                "landing_events.created_at", _tz))
                            # 通过量（click + redirect）—— 按 ip_hash 去重（同一人多次点击算1，减少误差）
                            landing_clicks = db.query(_f.count(_f.distinct(LandingEvent.ip_hash))).filter(
                                LandingEvent.ad_id == ad_id,
                                LandingEvent.event_type.in_(["click", "redirect"]),
                                LandingEvent.ip_hash.isnot(None),
                                _local_date_expr == acc_today,
                            ).scalar() or 0
                            # 访问量（visit + redirect）
                            landing_visits = db.query(_f.count(LandingEvent.id)).filter(
                                LandingEvent.ad_id == ad_id,
                                LandingEvent.event_type.in_(["visit", "redirect"]),
                                _local_date_expr == acc_today,
                            ).scalar() or 0
                        except Exception:
                            pass

                    # 查加白（账户本地当日跳过，和 snapshot_date / FB insights today 对齐）
                    whitelisted = db.query(GuardAllowance).filter(
                        GuardAllowance.act_id == acc.act_id,
                        GuardAllowance.ad_id == ad_id,
                        GuardAllowance.allowance_date == acc_today,
                        GuardAllowance.status == "active",
                    ).first()
                    if whitelisted:
                        continue

                    # 历史快照：上一轮的今日累计 spend（budget_burn_fast）+ 近 N 天（consecutive_bad）
                    prev_spend = None
                    history = None
                    if hist_days or any(r.rule_type == "budget_burn_fast" for r in all_rules):
                        prev_snap = db.query(PerfSnapshot).filter(
                            PerfSnapshot.ad_id == ad_id,
                            PerfSnapshot.snapshot_date == biz_today,
                        ).first()
                        if prev_snap:
                            prev_spend = prev_snap.spend
                        if hist_days:
                            since_date = (datetime.strptime(biz_today, "%Y-%m-%d") - timedelta(days=hist_days)).strftime("%Y-%m-%d")
                            history = db.query(PerfSnapshot).filter(
                                PerfSnapshot.ad_id == ad_id,
                                PerfSnapshot.snapshot_date >= since_date,
                                PerfSnapshot.snapshot_date < biz_today,
                            ).order_by(PerfSnapshot.snapshot_date.desc()).all()

                    # 评估每条规则（全局 + 本账户级，并存）
                    for rule in acc_rules:
                        hit, detail = _evaluate_rule(rule, ad, conversions=conv, target_cpa=target_cpa,
                                                     landing_clicks=landing_clicks,
                                                     landing_visits=landing_visits,
                                                     yesterday_insight=yesterday_map.get(ad_id),
                                                     prev_spend=prev_spend, history=history,
                                                     currency=acc.currency)
                        if not hit:
                            continue

                        # 冷却 dedup（22：成功 60min 阻断；失败仅 5min 重试冷却，下轮重试）
                        now_utc = datetime.now(timezone.utc)
                        succ_cd = now_utc - timedelta(minutes=COOLDOWN_MIN)
                        succ = db.query(ActionLog).filter(
                            ActionLog.tenant_id == tenant_id,
                            ActionLog.target_id == ad_id,
                            ActionLog.trigger_type == rule.rule_type,
                            ActionLog.action_type == "pause",
                            ActionLog.result == "success",
                            ActionLog.created_at >= succ_cd,
                        ).first()
                        if succ:
                            continue  # 成功暂停过，60min 内不重复
                        fail_cd = now_utc - timedelta(minutes=RETRY_COOLDOWN_MIN)
                        fail_recent = db.query(ActionLog).filter(
                            ActionLog.tenant_id == tenant_id,
                            ActionLog.target_id == ad_id,
                            ActionLog.trigger_type == rule.rule_type,
                            ActionLog.action_type == "pause",
                            ActionLog.result == "fail",
                            ActionLog.created_at >= fail_cd,
                        ).first()
                        if fail_recent:
                            continue  # 近 5min 暂停失败过，等下轮重试（不每轮 hammer）

                        total_hits += 1
                        category = RULE_CATEGORY.get(rule.rule_type, "止损")
                        campaign_id = ad.get("campaign_id", "")
                        campaign_name = ad.get("campaign_name", campaign_id)
                        adset_id = ad.get("adset_id", "")
                        adset_name = ad.get("adset_name", adset_id)
                        logger.info(f"[Guard] 命中！租户{tenant_id} 账户{acc.act_id} "
                                    f"广告[{ad_name}] 规则[{rule.name}] {detail}")

                        # 动作由 rule.action 控制：observe=只告警；其余=动态升级暂停
                        # （ad→adset→campaign，失败/假停逐级升级，移植 1.0 _pause_with_escalation）
                        ra = (rule.action or "default").lower()
                        action_text = "仅告警（规则设为观察）"
                        pause_result = "success"
                        if ra != "observe":
                            if ra in ("pause", "default"):
                                chain = [(ad_id, "广告"), (adset_id, "组"), (campaign_id, "系列")]
                            elif ra == "pause_adset":
                                chain = [(adset_id, "组"), (campaign_id, "系列")]
                            else:  # pause_campaign
                                chain = [(campaign_id, "系列")]
                            paused_ok = False
                            for pid, label in chain:
                                if not pid:
                                    continue
                                try:
                                    fb.pause_ad(pid)  # pause_ad 对 ad/adset/campaign 通用
                                    # A2 核验（ad 级）：停后单查 effective_status，仍 ACTIVE=假停→升级下一级
                                    # 单查比 get_active_ads(拉全账户+缓存) 快且准；sleep 2.5s 等 FB 写延迟
                                    if pid == ad_id:
                                        time.sleep(2.5)
                                        try:
                                            _node = fb.get_node(pid, "effective_status")
                                            if str(_node.get("effective_status", "")).upper() == "ACTIVE":
                                                continue  # 假停，升级下一级
                                        except Exception:
                                            pass  # 核验查询失败，信任 FB（视为成功，不升级）——宁可少停不误停整组
                                    total_paused += 1
                                    paused_details.append({"act_id": acc.act_id, "ad_id": ad_id,
                                                           "ad_name": ad_name, "level": label,
                                                           "target": pid, "reason": detail})
                                    action_text = f"已暂停{label} PAUSED" + ("（已核验）" if pid == ad_id else "")
                                    paused_ok = True
                                    break
                                except FbApiError as _pause_err:
                                    # 记录 Meta code/subcode 供排障（交接包 pitfall#7：不丢弃错误码）
                                    logger.warning(f"[Guard] 暂停{label}失败 ad={ad_id} pid={pid} code={getattr(_pause_err,'category','')} raw={str(getattr(_pause_err,'raw',''))[:100]}")
                                    continue  # 该级暂停失败，升级下一级
                            if not paused_ok:
                                action_text = "暂停失败（ad→组→系列均未生效）"
                                pause_result = "fail"

                        # 记日志（账户/系列/组/广告 ID + 本币花销 + 动作 + trace_id）
                        write_log(db, tenant_id=tenant_id, trace_id=trace_id,
                                  actor_type="system", target_type="ad", target_id=ad_id,
                                  action_type="pause", source="rule_engine", result=pause_result,
                                  trigger_type=rule.rule_type,
                                  trigger_detail=f"{detail} | act={acc.act_id}({acc.currency}) "
                                                 f"camp={campaign_id} adset={adset_id} ad={ad_id} "
                                                 f"spend={fmt_spend(spend, acc.currency)} "
                                                 f"conv={conv} action={action_text}",
                                  metadata={"campaign_id": campaign_id, "adset_id": adset_id,
                                            "ad_id": ad_id, "act_id": acc.act_id,
                                            "currency": acc.currency, "rule_action": ra,
                                            "action": action_text})

                        # 通知（去重 60min/广告：已停广告每轮重复命中不应重复 notify）
                        if not dedup_recent(db, tenant_id, "rule_pause_notified", ad_id, 60):
                            emit_notification(
                                db, tenant_id=tenant_id, level="warning",
                                event_type="rule_pause", trace_id=trace_id,
                                title=f"止损【{_esc(category)}】· {_esc(acc.name)}",
                                body=f"账户：{_esc(acc.name)}（<code>{acc.act_id}</code>）\n"
                                     f"广告：{_esc(ad_name)}（<code>{ad_id}</code>）\n"
                                     f"广告组：<code>{adset_id or '-'}</code>\n"
                                     f"系列：<code>{campaign_id or '-'}</code>\n"
                                     f"规则：{_esc(rule.name)}\n"
                                     f"触发：<b>{_esc(detail)}</b>\n"
                                     f"消耗：<b>{fmt_spend(spend, acc.currency)}</b> ｜ 转化：<b>{conv}</b>\n"
                                     f"KPI：{_esc(kpi.get('kpi_label') or '-')}"
                                     f"（{_esc(SOURCE_LABELS.get(kpi.get('source'), kpi.get('source') or '-'))}）",
                                target_type="ad", target_id=ad_id,
                                reply_markup={"inline_keyboard": [[
                                    {"text": "🛲 加白今日", "callback_data": f"allow|{tenant_id}|{acc.act_id}|{ad_id}"}
                                ]]},
                            )
                            write_log(db, tenant_id=tenant_id, trace_id=trace_id,
                                actor_type="system", target_type="ad", target_id=ad_id,
                                action_type="rule_pause_notified", source="rule_engine",
                                result="success", trigger_detail=f"ad={ad_id}")

                        db.commit()
                        break  # 一条广告命中一条规则就停，不重复评估

                    # upsert 今日快照（consecutive_bad / budget_burn_fast 数据源 + 看板缓存层）
                    try:
                        spend_usd_snap = to_usd(spend, acc.currency)
                        cpa = (spend_usd_snap / conv) if conv > 0 else None
                        impressions = int(ad.get("impressions", 0))
                        clicks = int(ad.get("clicks", 0))
                        reach = int(ad.get("reach", 0))
                        frequency = float(ad.get("frequency", 0) or 0)
                        ctr = float(ad.get("ctr", 0) or 0)
                        cpc = float(ad.get("cpc", 0) or 0)
                        roas_val = float(ad.get("purchase_roas", 0) or 0)
                        snap = db.query(PerfSnapshot).filter(
                            PerfSnapshot.ad_id == ad_id,
                            PerfSnapshot.snapshot_date == biz_today,
                        ).first()
                        if snap:
                            snap.spend = spend_usd_snap
                            snap.spend_native = spend
                            snap.currency = acc.currency
                            snap.conversions = conv
                            snap.cpa = cpa
                            snap.roas = roas_val if roas_val > 0 else None
                            snap.impressions = impressions
                            snap.clicks = clicks
                            snap.reach = reach
                            snap.frequency = frequency if frequency > 0 else None
                            snap.ctr = ctr if ctr > 0 else None
                            snap.cpc = cpc if cpc > 0 else None
                            snap.actions_json = json.dumps(ad.get("actions", []))[:4000]
                            snap.resolved_kpi = kpi.get("kpi_field", "")
                            snap.kpi_source = kpi.get("source", "")
                        else:
                            db.add(PerfSnapshot(
                                tenant_id=tenant_id, act_id=acc.act_id, ad_id=ad_id,
                                snapshot_date=biz_today, spend=spend_usd_snap,
                                spend_native=spend, currency=acc.currency,
                                conversions=conv, cpa=cpa,
                                roas=roas_val if roas_val > 0 else None,
                                impressions=impressions, clicks=clicks, reach=reach,
                                frequency=frequency if frequency > 0 else None,
                                ctr=ctr if ctr > 0 else None, cpc=cpc if cpc > 0 else None,
                                actions_json=json.dumps(ad.get("actions", []))[:4000],
                                resolved_kpi=kpi.get("kpi_field", ""),
                                kpi_source=kpi.get("source", ""),
                            ))
                        # tick conv 已在循环开头累计所有广告（含暂停）
                        db.commit()
                    except Exception as e:
                        logger.warning(f"[Guard] 快照写入异常 ad={ad_id}: {e}")

                # ── 账户级聚合 tick：本账户本次巡检所有广告 spend/conv 总和（0 广告也写一条保证趋势不断档）──
                try:
                    acc_tick_cpa = round(acc_tick_spend / acc_tick_conv, 2) if acc_tick_conv > 0 else None
                    db.add(PerfSnapshotTick(
                        tenant_id=tenant_id, act_id=acc.act_id, snapshot_date=biz_today,
                        snapshot_at=datetime.now(timezone.utc),
                        spend=round(acc_tick_spend, 2), conversions=acc_tick_conv,
                        cpa=acc_tick_cpa, roas=None,
                    ))
                    db.commit()
                except Exception:
                    pass

        logger.info(f"[Guard] 巡检完成: 评估 {total_evaluated} 条广告, "
                    f"命中 {total_hits}, 停止 {total_paused} (LIVE，按 rule.action)")
        # 巡检心跳（watchdog 用：长时间无成功心跳 = 巡检停滞）
        write_log(db, tenant_id=1, trace_id=trace_id, actor_type="system",
                  target_type="scheduler", action_type="inspection_heartbeat",
                  source="scheduled", result="success",
                  trigger_detail=f"eval={total_evaluated} hits={total_hits} skipped_spend={total_skipped_spend}")
        # 覆盖丢失告警：有消耗的广告被 active_ids 过滤掉（止损盲区）→ 告警（6h dedup 避免每轮 spam）
        if total_skipped_spend > 0:
            if not dedup_recent(db, tenant_id, "coverage_lost", "*", 360):
                # 写 action_log 让 dedup_recent 下轮命中（6h 内不再重复发）
                write_log(db, tenant_id=tenant_id, trace_id=trace_id,
                          actor_type="system", target_type="ad", target_id="*",
                          action_type="coverage_lost", source="guard", result="success",
                          trigger_detail=f"skipped={total_skipped_spend}")
                emit_notification(
                    db, tenant_id=tenant_id, level="warning",
                    event_type="coverage_lost", trace_id=trace_id,
                    title=f"巡检覆盖丢失：{total_skipped_spend} 条有消耗广告未被评估",
                    body=f"本轮有 {total_skipped_spend} 条今日有消耗的广告被排除在巡检外（active_ids 拉取失败/ads_cache 为空），止损规则对它们失效，请检查令牌/同步。",
                )
        db.commit()
        return {"evaluated": total_evaluated, "hits": total_hits, "paused": total_paused,
                "skipped_spend": total_skipped_spend, "details": paused_details}

    except Exception as e:
        logger.error(f"[Guard] 巡检异常: {e}", exc_info=True)
        # 异常也记心跳（result=fail）—— watchdog 区分"没跑"vs"跑了但失败"
        try:
            write_log(db, tenant_id=1, trace_id=trace_id, actor_type="system",
                      target_type="scheduler", action_type="inspection_heartbeat",
                      source="scheduled", result="fail", friendly_error=str(e)[:200])
            db.commit()
        except Exception:
            pass
        return {"error": str(e)}
    finally:
        db.close()
        release_run_lock(lock, 101)


# 巡检停滞阈值（分钟）：超过此无成功心跳 = 停滞（3 个 5-min 周期）
INSPECTION_STALL_MIN = 15
# 重试冷却（分钟）：暂停失败后缩短冷却，下轮（~5min）重试（22，1.0 _set_retry_cooldown）
RETRY_COOLDOWN_MIN = 5
# BLEED_ABORT：broader 转化 action 集（23，防 KPI 字段错配误杀 bleed_abs）
_BROAD_ACTIONS = {
    "purchase", "omni_purchase", "offsite_conversion.fb_pixel_purchase",
    "lead", "onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead",
    "add_to_cart", "offsite_conversion.fb_pixel_add_to_cart",
    "contact", "offsite_conversion.fb_pixel_contact",
    "complete_registration", "offsite_conversion.fb_pixel_complete_registration",
    "subscribe", "offsite_conversion",
}


def _broader_conversions(actions: list) -> float:
    """broader 转化（任何转化信号）。>0 时 bleed_abs 不触发（防 KPI 字段错配把有转化的广告误杀）。"""
    total = 0.0
    for a in actions or []:
        if a.get("action_type") in _BROAD_ACTIONS:
            try:
                total += float(a.get("value", 0))
            except Exception:
                pass
    return total
# token 即将过期预警阈值（天）
TOKEN_EXPIRY_WARN_DAYS = 7

# 货币→USD 近似汇率（SSOT，定期更新）。FB insights.spend 是账户本币，阈值是 USD——必须换算。
# 否则 VND 账户 ₫252198 会被当 $252198 比 $20 阈值，必误触发。
CURRENCY_TO_USD = {
    "USD": 1.0, "VND": 1 / 25400, "IDR": 1 / 16300, "THB": 1 / 36, "PHP": 1 / 58,
    "MYR": 1 / 4.7, "SGD": 1 / 1.34, "TWD": 1 / 32, "CNY": 1 / 7.25, "HKD": 1 / 7.8,
    "INR": 1 / 83, "BRL": 1 / 5.4, "MXN": 1 / 17, "EUR": 1.08, "GBP": 1.27,
    "JPY": 1 / 157, "KRW": 1 / 1380, "AUD": 1 / 1.52, "CAD": 1 / 1.36,
}


def to_usd(amount: float, currency: str) -> float:
    """账户本币 → USD（阈值比较用）。优先读 CurrencyRate 表（每日刷新），硬编码字典兜底。"""
    cur = (currency or "USD").upper()
    if cur == "USD" or not amount:
        return amount
    fx = _fx_map()
    if cur in fx and fx[cur] > 0:
        return amount / fx[cur]  # CurrencyRate: 1 USD = rate × 本币 → USD = amount / rate
    return amount * CURRENCY_TO_USD.get(cur, 1.0)  # 表里没有 → 硬编码兜底


# 汇率缓存（1h TTL；首次调用从 CurrencyRate 表懒加载，止损热路径不每条广告查 DB）
_FX_CACHE = {"by_code": None, "ts": 0.0}
_FX_TTL = 3600.0


def _fx_map() -> dict:
    import time as _t
    now = _t.time()
    if _FX_CACHE["by_code"] is not None and now - _FX_CACHE["ts"] < _FX_TTL:
        return _FX_CACHE["by_code"]
    try:
        from ..core.database import SuperSessionLocal
        from ..models.perf import CurrencyRate
        sdb = SuperSessionLocal()
        try:
            by_code = {r.code.upper(): r.rate for r in sdb.query(CurrencyRate).all()}
        finally:
            sdb.close()
        if by_code:
            _FX_CACHE["by_code"] = by_code
            _FX_CACHE["ts"] = now
            return by_code
    except Exception:
        pass
    return _FX_CACHE["by_code"] or {}


def reset_fx_cache():
    """汇率刷新后清缓存（fx_sync 调，让下一轮巡检立刻用新汇率）。"""
    _FX_CACHE["by_code"] = None
    _FX_CACHE["ts"] = 0.0


def fmt_spend(spend: float, currency: str) -> str:
    """花销展示：本币 + USD 等值（避歧义）。"""
    cur = (currency or "USD").upper()
    usd = to_usd(spend, cur)
    if cur == "USD":
        return f"${spend:.2f}"
    return f"{cur} {spend:.0f} (≈${usd:.2f})"


# ── 账户可用投放额度（照搬 1.0 _calc_available_balance）──
# FB balance 在后付费账户里是账单余额/欠款，≠ 还能花多少钱；故可用额度只由
# spend_cap 与 amount_spent 推导，balance 不参与。
_NO_DECIMAL_CURRENCIES = {"JPY", "KRW", "IDR", "VND", "CLP", "COP", "HUF", "PYG", "UGX", "TZS"}
_UNLIMITED_SPEND_CAP_USD = 1_000_000.0


def _money_factor(currency: str) -> int:
    return 1 if (currency or "USD").upper() in _NO_DECIMAL_CURRENCIES else 100


def from_minor_units(value, currency: str):
    """FB API 金额字段（minor units：多数币种为分；JPY/KRW/VND 等零小数位币种为本币整数）→ 本币浮点。"""
    if value is None:
        return None
    try:
        return float(value) / _money_factor(currency)
    except (TypeError, ValueError):
        return None


def calc_available_balance(spend_cap, amount_spent, currency) -> tuple[float | None, str]:
    """账户可用投放额度（USD）。

    返 (avail_usd, kind)：
      - kind='limited'：avail = round((spend_cap - amount_spent) 的 USD, 2)
      - kind='unlimited'：avail=None（无 spend_cap 或 =0）
      - kind='very_high_limit'：avail=None（spend_cap ≥ $1M 视为不限）
    balance 不参与（FB balance 是账单/欠款，≠ 还能花的钱）。2.0 未存 spending_limit，
    故省略 1.0 的 spending_limit 优先分支，直接走 spend_cap。
    """
    cap = from_minor_units(spend_cap, currency)
    spent = from_minor_units(amount_spent, currency)
    if cap is None or cap <= 0:
        return (None, "unlimited")
    if to_usd(cap, currency) >= _UNLIMITED_SPEND_CAP_USD:
        return (None, "very_high_limit")
    avail = max(0.0, cap - (spent or 0))
    return (round(to_usd(avail, currency), 2), "limited")


def run_watchdog():
    """系统级看门狗（06_附录 §四，定时跑）：
    ① inspection_stalled：巡检长时间无成功心跳 → critical（守护挂了=止损失效，最危险）
    ② token_health：debug_token 查即将过期/失效 → warning（提前续期）
    各自 dedup（停滞 1h / token 24h）。advisory lock 防多 worker 重复。
    """
    lock = acquire_run_lock(103)
    if not lock:
        return {"skipped": "lock_busy"}
    db = SuperSessionLocal()
    trace_id = new_trace_id()
    alerts = {"inspection_stalled": 0, "token_expiring": 0}
    try:
        # ── ① 巡检心跳停滞检测（全局，跨所有租户的 scheduler）──
        since = datetime.now(timezone.utc) - timedelta(minutes=INSPECTION_STALL_MIN)
        last_ok = db.query(ActionLog).filter(
            ActionLog.action_type == "inspection_heartbeat",
            ActionLog.result == "success",
        ).order_by(ActionLog.created_at.desc()).first()
        stalled = (last_ok is None) or (last_ok.created_at < since)
        if stalled:
            # dedup 1h
            since_alert = datetime.now(timezone.utc) - timedelta(hours=1)
            already = db.query(ActionLog).filter(
                ActionLog.action_type == "inspection_stalled_alert",
                ActionLog.created_at >= since_alert,
            ).first()
            if not already:
                emit_notification(db, tenant_id=1, level="critical",
                                  event_type="inspection_stalled", trace_id=trace_id,
                                  title="🚨 巡检引擎停滞",
                                  body=(f"超过 {INSPECTION_STALL_MIN} 分钟无成功巡检心跳。\n"
                                        "守护引擎可能挂了——止损/预算告警失效，请立即排查 toveads 服务。"))
                write_log(db, tenant_id=1, trace_id=trace_id, actor_type="system",
                          target_type="scheduler", action_type="inspection_stalled_alert",
                          source="watchdog", result="success",
                          trigger_detail=f"last_ok={last_ok.created_at if last_ok else 'never'}")
                db.commit()
                alerts["inspection_stalled"] = 1

        # ── ② token 主动健康检查（debug_token，快过期/失效预警）──
        creds = db.query(FbCredential).filter(FbCredential.status == "active").all()
        since_day = datetime.now(timezone.utc) - timedelta(hours=24)
        for c in creds:
            # dedup 24h（每 token 每天最多一条 token_health）
            already = db.query(ActionLog).filter(
                ActionLog.target_type == "fb_credential",
                ActionLog.target_id == str(c.id),
                ActionLog.action_type == "token_health_warn",
                ActionLog.created_at >= since_day,
            ).first()
            if already:
                continue
            fb = FbClient(decrypt(c.access_token_enc))
            try:
                dt = fb.debug_token().get("data", {})
            except Exception as e:
                logger.warning(f"[Watchdog] token debug 失败 alias={c.alias}: {e}")
                continue
            if not dt.get("is_valid", True):
                emit_notification(db, tenant_id=c.tenant_id, level="critical",
                                  event_type="token_invalid", trace_id=trace_id,
                                  title="🔴 FB Token 无效",
                                  body=f"Token[{c.alias or c.id}] debug_token 显示无效，请重新绑定。")
                write_log(db, tenant_id=c.tenant_id, trace_id=trace_id, actor_type="system",
                          target_type="fb_credential", target_id=str(c.id),
                          action_type="token_health_warn", source="watchdog", result="fail")
                db.commit()
                alerts["token_expiring"] += 1
                continue
            exp = dt.get("expires_at")
            if exp:
                try:
                    remaining = datetime.fromtimestamp(int(exp), tz=timezone.utc) - datetime.now(timezone.utc)
                    if remaining.days <= TOKEN_EXPIRY_WARN_DAYS:
                        emit_notification(db, tenant_id=c.tenant_id, level="warning",
                                          event_type="token_expiring_soon", trace_id=trace_id,
                                          title="🟡 FB Token 即将过期",
                                          body=f"Token[{c.alias or c.id}] 剩余 {remaining.days} 天，请提前续期。")
                        write_log(db, tenant_id=c.tenant_id, trace_id=trace_id, actor_type="system",
                                  target_type="fb_credential", target_id=str(c.id),
                                  action_type="token_health_warn", source="watchdog", result="success",
                                  trigger_detail=f"days_left={remaining.days}")
                        db.commit()
                        alerts["token_expiring"] += 1
                except Exception:
                    pass
        logger.info(f"[Watchdog] 完成: {alerts}")
        return {"trace_id": trace_id, **alerts}
    except Exception as e:
        logger.error(f"[Watchdog] 异常: {e}", exc_info=True)
        return {"error": str(e)}
    finally:
        db.close()
        release_run_lock(lock, 103)


def run_reassociate():
    """定时孤儿账户重绑（token 换/删后自愈，1.0 教训 2.0 版）。2h 一次（重 FB 调用，不宜太频）。"""
    from ..core.fb_tokens import reassociate_orphan_accounts
    lock = acquire_run_lock(104)
    if not lock:
        return {"skipped": "lock_busy"}
    db = SuperSessionLocal()
    try:
        tenant_ids = db.execute(text(
            "SELECT DISTINCT tenant_id FROM fb_credentials WHERE status = 'active'"
        )).fetchall()
        total = 0
        alerted = 0
        for (tenant_id,) in tenant_ids:
            try:
                res = reassociate_orphan_accounts(db, tenant_id)
                total += res["rebound"]
                # 仍无任何 active cred 覆盖的孤儿 → critical 告警 + TG（每账户 24h dedup）
                if res.get("still_orphan"):
                    from ..core.notify_utils import emit_orphan_account_alerts
                    alerted += emit_orphan_account_alerts(db, tenant_id, res["still_orphan"])
            except Exception as e:
                logger.warning(f"[Reassociate] 租户 {tenant_id} 失败: {e}")
        if total:
            logger.info(f"[Reassociate] 重绑 {total} 个孤儿账户")
        if alerted:
            logger.info(f"[Reassociate] 发出 {alerted} 条孤儿账户告警")
        return {"rebound": total, "orphan_alerts": alerted}
    except Exception as e:
        logger.error(f"[Reassociate] 异常: {e}", exc_info=True)
        return {"error": str(e)}
    finally:
        db.close()
        release_run_lock(lock, 104)


def run_sentinel_patrol():
    """哨兵巡逻（doc 03 §4，1.0 sentinel_patrol 移植）：armed 账户的 ACTIVE 系列→直接全停。

    哨兵是 kill-switch（不走规则评估）：手动 arm 或自动 arm 后，发现 ACTIVE 系列直接停。
    与规则巡检独立。dedup：每 campaign 1h 内不重复停。
    """
    lock = acquire_run_lock(106)
    if not lock:
        return {"skipped": "lock_busy"}
    db = SuperSessionLocal()
    trace_id = new_trace_id()
    total_paused = 0
    try:
        # 所有 armed 账户（手动或自动 arm）；排除已取消纳管的（is_managed=false）
        armed = db.query(Account).filter(
            Account.is_managed.is_(True),
            (Account.sentinel_armed == True) | (Account.sentinel_auto_armed == True)  # noqa: E712
        ).all()
        for acc in armed:
            # 死账户（禁用/封号/支付失败等，account_status!=1）花不了钱，停系列是马后炮→跳过。
            # 恢复正常(status→1)后哨兵自然恢复生效：armed 仍在，account_sync 把状态刷回 1 后下轮就停。
            if acc.account_status is not None and acc.account_status != 1:
                continue
            # 预热中账户跳过哨兵（doc 03 §6）
            if (acc.warmup_state or "none") == "warming":
                continue
            fb = client_for_account(db, acc.tenant_id, acc.act_id, "pause")
            if not fb:
                continue
            try:
                # 拉 ACTIVE 系列（campaign）直接停
                camps = fb.get(f"act_{acc.act_id}/campaigns", {
                    "fields": "id,name,effective_status",
                    "filtering": '[{"field":"effective_status","operator":"IN","value":["ACTIVE"]}]',
                    "limit": 200,
                })
            except FbApiError as e:
                logger.warning(f"[Sentinel] 账户 {acc.act_id} 拉系列失败: {e.friendly}")
                continue
            for camp in (camps.get("data") or []):
                camp_id = camp.get("id")
                if not camp_id:
                    continue
                # dedup：1h 内已停过跳过
                since = datetime.now(timezone.utc) - timedelta(hours=1)
                already = db.query(ActionLog).filter(
                    ActionLog.tenant_id == acc.tenant_id,
                    ActionLog.target_id == camp_id,
                    ActionLog.action_type == "pause",
                    ActionLog.trigger_type == "sentinel",
                    ActionLog.created_at >= since,
                ).first()
                if already:
                    continue
                try:
                    fb.pause_ad(camp_id)  # pause_ad 对 campaign 通用
                    total_paused += 1
                    write_log(db, tenant_id=acc.tenant_id, trace_id=trace_id, actor_type="sentinel",
                              target_type="campaign", target_id=camp_id,
                              action_type="pause", source="sentinel_patrol", result="success",
                              trigger_type="sentinel",
                              trigger_detail=f"sentinel armed, campaign {camp.get('name','')} 直接停")
                    emit_notification(db, tenant_id=acc.tenant_id, level="critical",
                                      event_type="sentinel_pause", trace_id=trace_id,
                                      title=f"哨兵暂停系列",
                                      body=f"账户：{acc.name}（{acc.act_id}）\n系列：{camp.get('name','')}（{camp_id}）\n"
                                           f"哨兵已 arm，ACTIVE 系列直接停。")
                    db.commit()
                except FbApiError as e:
                    logger.warning(f"[Sentinel] 停系列 {camp_id} 失败: {e.friendly}")
        logger.info(f"[Sentinel] 巡逻完成: 停 {total_paused} 个系列 (armed={len(armed)})")
        return {"sentinel_paused": total_paused, "armed_accounts": len(armed)}
    except Exception as e:
        logger.error(f"[Sentinel] 异常: {e}", exc_info=True)
        return {"error": str(e)}
    finally:
        db.close()
        release_run_lock(lock, 106)


def run_subcode_autobind():
    """子码自动绑定（doc 02 §C，P0）：非 Mira 创建的广告，从创意 /a/{slug} 反查 → 绑 ad_id。

    Mira 创建的广告 launch 已绑（这是兜底第二条路径，1.0 _auto_bind_subcode_ad 移植）。
    1h 一次；有未绑子码才拉创意（省 FB 调用）。
    """
    import re
    from ..models.launch import LandingAdLink
    from ..core.fb_tokens import client_for_account, cred_for_account_op, mark_cred_cooldown
    lock = acquire_run_lock(105)
    if not lock:
        return {"skipped": "lock_busy"}
    db = SuperSessionLocal()
    try:
        # 有未绑子码才跑（排除 archived/deleted，避免重绑被清的子码）
        unbound = db.query(LandingAdLink).filter(
            LandingAdLink.ad_id.is_(None), LandingAdLink.status.in_(["reserved", "active"])).count()
        if not unbound:
            return {"skipped": "no_unbound", "unbound": 0}
        slug_re = re.compile(r"/a/([A-Za-z0-9_-]{4,64})")
        # 建未绑子码 set（按租户分组遍历）；排除已取消纳管的账户
        accounts = db.query(Account).filter(
            Account.account_status == 1, Account.is_managed.is_(True)).all()
        tenant_ids = {a.tenant_id for a in accounts}
        bound = 0
        for tid in tenant_ids:
            unbound_links = {l.slug: l for l in db.query(LandingAdLink).filter(
                LandingAdLink.tenant_id == tid, LandingAdLink.ad_id.is_(None),
                LandingAdLink.status.in_(["reserved", "active"])).all()}
            if not unbound_links:
                continue
            for acc in [a for a in accounts if a.tenant_id == tid]:
                fb = client_for_account(db, tid, acc.act_id)
                if not fb:
                    continue
                try:
                    links = fb.get_ad_creative_links(acc.act_id)
                except Exception:
                    continue
                for ad_id, url in links.items():
                    m = slug_re.search(url or "")
                    if not m:
                        continue
                    slug = m.group(1)
                    lc = unbound_links.get(slug)
                    if lc and not lc.ad_id:
                        lc.ad_id = ad_id
                        lc.act_id = acc.act_id
                        lc.status = "active"
                        bound += 1
                        db.commit()
                        logger.info(f"[SubcodeAutoBind] /a/{slug} <- ad {ad_id} (act_{acc.act_id})")
        return {"unbound_before": unbound, "bound": bound}
    except Exception as e:
        logger.error(f"[SubcodeAutoBind] 异常: {e}", exc_info=True)
        return {"error": str(e)}
    finally:
        db.close()
        release_run_lock(lock, 105)


def run_subcode_cleanup():
    """子码闲置清理（每天）：reserved+没绑广告+0访问+超14天 → 归档(archived)；
    archived 超30天 → 硬删(deleted，清自身配置，恢复后回退页级跳转)。
    归档/硬删都保留行可恢复（/subcodes/{sid}/restore）。
    """
    from ..models.launch import LandingAdLink
    from ..models.landing_event import LandingEvent
    from ..core.notify_utils import emit_notification
    lock = acquire_run_lock(108)
    if not lock:
        return {"skipped": "lock_busy"}
    db = SuperSessionLocal()
    now = datetime.now(timezone.utc)
    cutoff_archive = now - timedelta(days=14)
    cutoff_hard = now - timedelta(days=30)
    archived_n = hard_n = 0
    try:
        # 1. 归档候选：reserved + 没绑广告 + 创建超 14 天
        cand = db.query(LandingAdLink).filter(
            LandingAdLink.status == "reserved",
            LandingAdLink.ad_id.is_(None),
            LandingAdLink.created_at < cutoff_archive,
        ).all()
        # 排除有访问记录的（0 访问才算闲置）
        visited = set()
        if cand:
            visited = set(r[0] for r in db.query(LandingEvent.slug).filter(
                LandingEvent.event_type == "visit",
                LandingEvent.slug.in_([c.slug for c in cand]),
            ).distinct().all())
        notify_by_tenant = {}
        for c in cand:
            if c.slug in visited:
                continue
            c.status = "archived"
            c.archived_at = now
            archived_n += 1
            notify_by_tenant.setdefault(c.tenant_id, []).append(c.slug)
        # 2. 硬删：archived 超 30 天 **且从未绑过广告**(ad_id 空) → deleted + 清自身配置。
        #    手动归档但绑过广告的(有历史)保留 archived，不清配置，可完整恢复。
        to_hard = db.query(LandingAdLink).filter(
            LandingAdLink.status == "archived",
            LandingAdLink.ad_id.is_(None),
            LandingAdLink.archived_at < cutoff_hard,
        ).all()
        for c in to_hard:
            c.status = "deleted"
            c.target_urls = None
            c.ad_id = None
            c.act_id = None
            hard_n += 1
            notify_by_tenant.setdefault(c.tenant_id, []).append(c.slug)
        if archived_n or hard_n:
            db.commit()
            logger.info(f"[SubcodeCleanup] 归档 {archived_n}，硬删 {hard_n}")
            write_log(db, tenant_id=1, trace_id=new_trace_id(), actor_type="system",
                      target_type="subcode", target_id="batch",
                      action_type="subcode_cleanup", source="scheduled",
                      result="success", trigger_detail=f"archived={archived_n} hard={hard_n}")
            # 每租户一条 info 通知（站内信，不打 TG）
            for tid, slugs in notify_by_tenant.items():
                try:
                    emit_notification(db, tenant_id=tid, level="info", send_tg=False,
                        event_type="subcode_cleanup",
                        title="闲置子码已清理",
                        body=f"自动归档/硬删 {len(slugs)} 个闲置子码（14天未用→归档，30天→硬删）。回收站可恢复。")
                except Exception:
                    pass
            db.commit()
        return {"archived": archived_n, "hard_deleted": hard_n}
    except Exception as e:
        logger.error(f"[SubcodeCleanup] 异常: {e}", exc_info=True)
        return {"error": str(e)}
    finally:
        db.close()
        release_run_lock(lock, 108)
