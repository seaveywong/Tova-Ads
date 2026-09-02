"""巡检引擎（doc 03 §2）：定时读 FB insights → 匹配规则 → 停广告/扩量 → 记日志+通知。

核心流程：遍历租户 → 取规则 → 取账户 → 读 insights → 评估 → 命中则停/加预算。
动作由 rule.action 控制（observe/pause*/scale）；账户级并行（guard_concurrency，每线程自建 session）。
"""
import json
import logging
import time
import html
from concurrent.futures import ThreadPoolExecutor, as_completed
from types import SimpleNamespace
from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from ..core.database import SuperSessionLocal, acquire_run_lock, release_run_lock
from ..core.encryption import decrypt
from ..core.fb_client import FbClient, FbApiError
from ..core.tt_client import TtApiError
from ..core.log_utils import write_log, new_trace_id
from ..core.notify_utils import emit_notification, emit_token_expired_if_due, dedup_recent
from ..core.i18n import tenant_locale, notify_text
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
from ..models.system import SystemSetting

# 告警/暂停冷却（分钟）—— 同一 ad+rule 在冷却内不重复告警/暂停（防通知 spam）
COOLDOWN_MIN = 60

logger = logging.getLogger("toveads.guard")

# 规则类型 → 客户面类别（doc 03 §2.1，8 类止损规则 + 2 类扩量规则）
RULE_CATEGORY = {
    "bleed_abs": "空耗止损", "click_no_conv": "空耗止损", "reach_no_conv": "空耗止损",
    "low_ctr_no_conv": "空耗止损", "budget_burn_fast": "空耗止损",
    "cpa_exceed": "成本超标", "trend_drop": "效果下滑", "consecutive_bad": "效果下滑",
    "slow_scale": "智能扩量", "roas_scale": "智能扩量",
}

# 扩量规则类型（1.0 _check_scale_rule 移植）：命中 → 走 set_budget 加预算（非暂停链）
SCALE_RULE_TYPES = ("slow_scale", "roas_scale")

# 默认参数（审计项目9：8 规则默认值表 + 扩量 2 类）
# 扩量契约（params JSON，全部可省）：
#   min_conversions   转化数下限（当日 FB 转化 ≥ 此值才考虑扩量）
#   cpa_target        CPA 目标 USD（KPI target_cpa 优先，此值兜底；无目标且非 roas_scale 则不扩）
#   cpa_ratio         "转化好"判定：CPA ≤ 目标×ratio（1.0 语义 0.8=比目标便宜两成以上）
#   roas_threshold    ROAS 阈值（仅 roas_scale；当日 ROAS ≥ 此值）
#   scale_pct         每次加预算步长（百分比，20=+20%/次；1-100）
#   max_daily_budget_usd  日预算上限 USD（到顶不再加；新预算超上限则钳到上限）
#   consecutive_days  连续好天数（1=只看当日；>1 需近 N-1 天历史快照同样达标）
#   cooldown_hours    同一广告组两次扩量最小间隔（默认 24h）
RULE_DEFAULTS = {
    "bleed_abs":        {"spend_threshold": 20},
    "cpa_exceed":       {"cpa_target": 8, "ratio": 1.3},
    "click_no_conv":    {"min_clicks": 50},
    "low_ctr_no_conv":  {"min_spend": 10, "max_ctr": 0.5},   # min_spend=USD, max_ctr=百分比
    "reach_no_conv":    {"reach_threshold": 1000, "min_spend": 10},
    "trend_drop":       {"drop_threshold": 40},               # ROAS 下滑百分比
    "consecutive_bad":  {"param_days": 2, "ratio": 1.3, "cpa_target": 8},
    "budget_burn_fast": {"threshold_abs": 20},                # 两轮巡检间消耗增量 USD
    "slow_scale":       {"min_conversions": 3, "cpa_target": 8, "cpa_ratio": 0.8,
                         "scale_pct": 20, "max_daily_budget_usd": 100,
                         "consecutive_days": 1, "cooldown_hours": 24},
    "roas_scale":       {"min_conversions": 3, "roas_threshold": 3.0, "cpa_ratio": 0.8,
                         "scale_pct": 15, "max_daily_budget_usd": 100,
                         "consecutive_days": 1, "cooldown_hours": 24},
}

# 学习期保护默认（system_settings.guard_learning_hours 可覆盖；0=关）：创建 < N 小时的广告不动
DEFAULT_LEARNING_HOURS = 24.0
# 巡检并发默认（system_settings.guard_concurrency，1-8）
DEFAULT_CONCURRENCY = 4


def _sys_float(db, key: str, default: float) -> float:
    """system_settings 全局数值（value 存 JSON）。缺省/脏值 → default。"""
    try:
        row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if row and row.value not in (None, ""):
            v = float(json.loads(row.value))
            return v
    except Exception:
        pass
    return default


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
                        out[cid] = ((c.get("objective") or "").upper(),
                                    ((c.get("optimization_goal") or c.get("effective_optimization_goal")) or "").upper())
        except Exception:
            # batch 失败 → 逐个 fallback（保可用性）
            for cid in batch:
                if cid in out:
                    continue
                try:
                    c = fb.get(cid, {"fields": "id,objective,optimization_goal"})
                    out[cid] = ((c.get("objective") or "").upper(),
                                ((c.get("optimization_goal") or c.get("effective_optimization_goal")) or "").upper())
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


def _acc_platform(acc) -> str:
    """账户平台归一：'tt' → tt，其余（含空/历史缺省）→ 'fb'。"""
    return "tt" if (getattr(acc, "platform", None) or "fb") == "tt" else "fb"


def _ad_id_of(a: dict) -> str:
    """广告行 id 归一（FB 对象=id / TT 对象=ad_id）。"""
    return str(a.get("ad_id") or a.get("id") or "")


def _ad_is_active(a: dict, platform: str) -> bool:
    """广告行投放状态判定（FB=effective_status ACTIVE / TT=status STATUS_ENABLE）。"""
    s = str(a.get("effective_status") or a.get("status") or "").upper()
    return s == "ACTIVE" if platform == "fb" else s in ("ACTIVE", "STATUS_ENABLE")


def _norm_created(v) -> str:
    """创建时间归一：TT 'YYYY-MM-DD HH:MM:SS'（空格分隔）→ ISO 'T' 分隔（学习期 strptime 按 FB 格式）。"""
    s = str(v) if v is not None else ""
    return s.replace(" ", "T") if s else s


def _max_history_days(rules: list) -> int:
    """需要拉多少天历史快照（consecutive_bad 的 param_days / 扩量 consecutive_days 最大值）。"""
    n = 0
    for r in rules:
        if r.rule_type == "consecutive_bad":
            try:
                n = max(n, int((json.loads(r.params) or {}).get("param_days", 2)))
            except Exception:
                n = max(n, 2)
        elif r.rule_type in SCALE_RULE_TYPES:
            try:
                n = max(n, int((json.loads(r.params) or {}).get("consecutive_days", 1)))
            except Exception:
                pass
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
    conversion_source（rule）：fb/landing/either。CPA 类规则（cpa_exceed/consecutive_bad）
        恒用 FB conversions，不受 either/landing 稀释（虚增转化会拉低 CPA → 超标漏停）。
    landing_metric（rule params）：pass（通过量，默认）/ visit（访问量）。
    """
    # 转化归因：按规则 conversion_source + landing_metric 取 effective conversions
    cs = (getattr(rule, "conversion_source", None) or "either").lower()
    raw_params = json.loads(rule.params) if rule.params else {}
    landing_metric = (raw_params.pop("landing_metric", None) or "pass").lower()
    # landing 侧取哪个指标：pass=通过量(click+redirect) / visit=访问量(visit+redirect)
    landing_val = landing_clicks if landing_metric == "pass" else landing_visits
    # CPA 类规则（cpa_exceed/consecutive_bad）强制用 FB 转化数：落地点击/访问≠转化，
    #   either 取 max 或 landing 顶替都会虚增转化 → CPA 被拉低 → 超标漏停。
    #   cs=landing 且 FB insights 无 actions（算不出真实 CPA）时规则不适用，不用落地数顶替。
    # 扩量规则同样强制 FB 转化（加预算花真钱，落地通过量当转化会误扩）。
    # 空耗类规则（bleed_abs/click_no_conv 等）保持 either/landing 兜底（落地有通过量
    #   说明不是纯空耗，防误杀）。
    if rule.rule_type in ("cpa_exceed", "consecutive_bad", "slow_scale", "roas_scale"):
        if cs == "landing" and not (ad_insights.get("actions") or []):
            return False, ""  # CPA 规则不适用：无 FB actions，宁可漏告不拿落地数顶替 CPA
    elif cs == "landing":
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

    if rt in SCALE_RULE_TYPES:
        return _evaluate_scale_rule(rt, p, ad_insights, conversions, target_cpa, currency, history)

    # 未知规则类型
    return False, ""


def _evaluate_scale_rule(rt: str, p: dict, ad_insights: dict, conversions: float,
                         target_cpa: float | None, currency: str,
                         history: list | None) -> tuple[bool, str]:
    """扩量命中判定（1.0 _check_scale_rule 移植）：转化达标 + 成本优秀（+ROAS 达标）。
    只判"该不该扩"；执行（24h 冷却/上限保护/set_budget）在巡检命中分支。"""
    spend = float(ad_insights.get("spend", 0) or 0)
    spend_usd = to_usd(spend, currency)
    min_conv = max(0, int(float(p.get("min_conversions", 3) or 0)))
    if float(conversions or 0) < min_conv:
        return False, ""
    # CPA 优秀判定：KPI target_cpa 优先，params.cpa_target 兜底（都无 → roas_scale 可只看 ROAS）
    target = float(target_cpa) if target_cpa else float(p.get("cpa_target", 0) or 0)
    ratio = max(0.1, min(float(p.get("cpa_ratio", 0.8) or 0.8), 2.0))
    roas_threshold = float(p.get("roas_threshold", 3.0) or 3.0) if rt == "roas_scale" else None
    parts = [f"转化 {int(conversions)}≥{min_conv}"]
    if target > 0:
        if conversions <= 0 or spend_usd <= 0:
            return False, ""
        cpa_usd = spend_usd / conversions
        if cpa_usd > target * ratio:
            return False, ""
        parts.append(f"CPA ≈${cpa_usd:.2f}≤${target * ratio:.2f}")
    elif not roas_threshold:
        return False, ""  # 无 CPA 目标也无 ROAS 阈值 → 无扩量依据（1.0 同语义）
    if roas_threshold:
        roas_raw = ad_insights.get("purchase_roas")
        if roas_raw is None or float(roas_raw) < roas_threshold:
            return False, ""
        parts.append(f"ROAS {float(roas_raw):.2f}≥{roas_threshold:.2f}")
    days = max(1, int(float(p.get("consecutive_days", 1) or 1)))
    if days > 1:
        # 连续好天数：今日命中 + 近 days-1 天历史快照同样达标（PerfSnapshot：cpa=USD、conversions/roas）
        good = 0
        for r in (history or []):
            r_conv = int(r.conversions or 0)
            if r_conv < min_conv:
                continue
            if target > 0 and (not r.cpa or r.cpa > target * ratio):
                continue
            if roas_threshold and (not r.roas or float(r.roas) < roas_threshold):
                continue
            good += 1
        if good < days - 1:
            return False, ""
        parts.append(f"连续{days}天达标")
    return True, " / ".join(parts)


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


def _rule_ctx(r) -> SimpleNamespace:
    """ORM 规则 → 线程安全纯数据上下文（SimpleNamespace；跨线程只读，不挂任何 session）。"""
    return SimpleNamespace(
        id=getattr(r, "id", None),
        name=(getattr(r, "name", "") or ""),
        rule_type=r.rule_type,
        params=(r.params or "{}"),
        conversion_source=(getattr(r, "conversion_source", None) or "either"),
        action=(getattr(r, "action", None) or "default"),
        scope_act_id=getattr(r, "scope_act_id", None),
    )


_DEFAULT_BLEED_RULE_CTX = _rule_ctx(_DEFAULT_BLEED_ABS_RULE)


def _max_workers(db, count: int) -> int:
    """巡检并发度：system_settings.guard_concurrency（1-8，默认 4；1.0 同款钳制），不超过任务数。"""
    try:
        configured = int(_sys_float(db, "guard_concurrency", DEFAULT_CONCURRENCY))
    except Exception:
        configured = DEFAULT_CONCURRENCY
    configured = max(1, min(configured, 8))
    return max(1, min(configured, int(count or 1)))


def _scale_cooldown_ok(db, tenant_id, rule, ad_id, adset_id, scaled_targets, now_utc,
                       platform: str | None = None) -> bool:
    """扩量防重复（1.0 语义）：同目标 cooldown_hours（默认 24h）内已扩过/已跳过（到顶/lifetime）
    → 不再扩；刚失败 5min 内不 hammer（与暂停失败重试同节奏）；本轮内同组已扩过（内存 set）也不再。
    冷却只挡扩量——同广告的止损规则仍照常评估（该停还得停）。
    platform：None=不加过滤（FB 路径，查询零改动）；'tt'=按 platform 列过滤——TT 的
    adset_id 是每广告主小整数（≠FB 全局唯一），不过滤会与 FB 行（或另一 TT 广告主）撞 target。"""
    tgt = adset_id or ad_id
    if tgt in scaled_targets:
        return False
    try:
        _p = {**RULE_DEFAULTS.get(rule.rule_type, {}),
              **{k: v for k, v in (json.loads(rule.params) or {}).items()
                 if v not in (None, "", [])}}
        cd_hours = max(1, int(float(_p.get("cooldown_hours", 24) or 24)))
    except Exception:
        cd_hours = 24
    _pf = [ActionLog.platform == platform] if platform else []
    recent = db.query(ActionLog).filter(
        ActionLog.tenant_id == tenant_id,
        ActionLog.target_id == tgt,
        *_pf,
        ActionLog.action_type.in_(["increase_budget", "increase_budget_skipped"]),
        ActionLog.result == "success",
        ActionLog.created_at >= now_utc - timedelta(hours=cd_hours),
    ).first()
    if recent:
        return False
    fail_recent = db.query(ActionLog).filter(
        ActionLog.tenant_id == tenant_id,
        ActionLog.target_id == tgt,
        *_pf,
        ActionLog.action_type == "increase_budget",
        ActionLog.result == "fail",
        ActionLog.created_at >= now_utc - timedelta(minutes=RETRY_COOLDOWN_MIN),
    ).first()
    return fail_recent is None


def _apply_scale(db, fb, tenant_id, acc, trace_id, rule, detail, ad_id, adset_id,
                 campaign_id, ad_name, events, res, scaled_targets) -> None:
    """扩量执行（1.0 _check_scale_rule 执行段移植）：
    读当前日预算 → 按步长上浮（钳日预算上限）→ ad_ops.set_budget（含 per-node 锁/本币换算/回读核验/缓存 patch）。
    预算载体：adset 日预算；adset 无日预算（CBO）→ campaign 日预算；lifetime 总预算语义不同，不动。
    observe 规则只告警不动预算（日志记 observe_alert，不进 24h 扩量冷却）。
    所有日志/通知走 events 队列（主线程回放）。异常由调用方兜底。"""
    try:
        _rp = {k: v for k, v in (json.loads(rule.params) or {}).items()
               if v not in (None, "", [])}
    except Exception:
        _rp = {}
    _p = {**RULE_DEFAULTS.get(rule.rule_type, {}), **_rp}
    pct = max(1.0, min(float(_p.get("scale_pct", 20) or 20), 100.0)) / 100.0
    cap_usd = float(_p.get("max_daily_budget_usd", 0) or 0)
    ra = (rule.action or "default").lower()
    loc = tenant_locale(db, tenant_id)
    category = "Smart Scale-Up" if loc == "en" else "智能扩量"

    def _log_evt(action_type, result, trigger_detail, friendly=None,
                 target_id=None, target_type="ad", metadata=None):
        events.append({"kind": "log", "kwargs": dict(
            tenant_id=tenant_id, trace_id=trace_id, actor_type="system",
            target_type=target_type, target_id=target_id or ad_id,
            action_type=action_type, source="rule_engine", result=result,
            trigger_type=rule.rule_type, trigger_detail=trigger_detail,
            friendly_error=friendly, metadata=metadata)})

    def _notify_evt(level, action_disp, budget_disp, force_tg):
        # 通知去重 60min/目标（持续达标的广告不每 5min 重发；action_log 标记供 dedup_recent）
        if dedup_recent(db, tenant_id, "rule_scale_notified", (adset_id or ad_id), 60):
            return
        _t, _b = notify_text(loc, "rule_scale",
                             category=category, name=_esc(acc.name), act_id=acc.act_id,
                             ad_name=_esc(ad_name), ad_id=ad_id,
                             adset_id=(adset_id or '-'),
                             rule_name=_esc(rule.name), detail=_esc(detail),
                             action=_esc(action_disp), budget=_esc(budget_disp))
        if ra == "observe":
            _t = ("[Observe] " if loc == "en" else "[观察] ") + _t
        events.append({"kind": "notify", "kwargs": dict(
            tenant_id=tenant_id, level=level, event_type="rule_scale",
            trace_id=trace_id, title=_t, body=_b,
            target_type="adset", target_id=(adset_id or ad_id),
            force_tg=force_tg, platform="fb")})
        _log_evt("rule_scale_notified", "success", f"target={adset_id or ad_id}",
                 target_id=(adset_id or ad_id), target_type="adset")

    # ── 定位预算载体 ──
    if not adset_id:
        _log_evt("increase_budget_skipped", "success", f"{detail} | 无 adset_id，跳过")
        return
    scale_level, tgt_id = "adset", adset_id
    try:
        _node = fb.get_node(adset_id, "id,daily_budget,lifetime_budget") or {}
    except Exception as e:
        _log_evt("increase_budget", "fail", f"{detail} | 读 adset 预算失败",
                 friendly=str(e)[:150], target_id=adset_id, target_type="adset")
        return
    cur_minor = _node.get("daily_budget")
    if not cur_minor:
        if _node.get("lifetime_budget"):
            _log_evt("increase_budget_skipped", "success",
                     f"{detail} | adset 为 lifetime 总预算（语义不同），不动",
                     target_id=adset_id, target_type="adset")
            return
        # adset 无自己的预算（CBO）→ 预算在 campaign
        if not campaign_id:
            _log_evt("increase_budget_skipped", "success", f"{detail} | 无日预算可加",
                     target_id=adset_id, target_type="adset")
            return
        try:
            _cnode = fb.get_node(campaign_id, "id,daily_budget,lifetime_budget") or {}
        except Exception as e:
            _log_evt("increase_budget", "fail", f"{detail} | 读 campaign 预算失败",
                     friendly=str(e)[:150], target_id=campaign_id, target_type="campaign")
            return
        if not _cnode.get("daily_budget"):
            _log_evt("increase_budget_skipped", "success",
                     f"{detail} | campaign 无日预算（lifetime/其他），不动",
                     target_id=adset_id, target_type="adset")
            return
        scale_level, tgt_id, cur_minor = "campaign", campaign_id, _cnode.get("daily_budget")

    cur_native = from_minor_units(cur_minor, acc.currency) or 0.0
    cur_usd = to_usd(cur_native, acc.currency)
    new_usd = cur_usd * (1.0 + pct)
    capped = False
    if cap_usd > 0:
        if cur_usd >= cap_usd:
            _log_evt("increase_budget_skipped", "success",
                     f"{detail} | 日预算已达上限 ${cur_usd:.2f}/日（cap ${cap_usd:.0f}）",
                     target_id=tgt_id, target_type=scale_level)
            _notify_evt("info",
                        ("Daily budget cap reached, not raised" if loc == "en" else "已达日预算上限，不再加"),
                        (f"${cur_usd:.2f}/day (cap ${cap_usd:.0f})" if loc == "en"
                         else f"${cur_usd:.2f}/日（上限 ${cap_usd:.0f}）"), True)
            return
        if new_usd > cap_usd:
            new_usd = cap_usd
            capped = True
    if new_usd <= cur_usd + 0.01:
        _log_evt("increase_budget_skipped", "success",
                 f"{detail} | 目标预算≤当前（${cur_usd:.2f}）",
                 target_id=tgt_id, target_type=scale_level)
        return
    _one = to_usd(1.0, acc.currency) or 1.0   # 1 本币 = _one USD → 新本币 = new_usd / _one
    new_native = round(new_usd / _one, 2)
    budget_disp = (f"${cur_usd:.2f} → ${new_usd:.2f}/day" if loc == "en" else f"${cur_usd:.2f} → ${new_usd:.2f}/日")
    if capped:
        budget_disp += (f" (cap ${cap_usd:.0f})" if loc == "en" else f"（上限 ${cap_usd:.0f}）")

    if ra == "observe":
        _log_evt("observe_alert", "success",
                 f"{detail} | 仅告警（观察） 拟 {budget_disp} act={acc.act_id} level={scale_level}",
                 target_id=ad_id)
        _notify_evt("info",
                    ("⚠ Alert only (observe mode, budget NOT changed)" if loc == "en"
                     else "⚠ 仅告警（观察模式，未动预算）"),
                    ("planned: " if loc == "en" else "拟 ") + budget_disp, True)
        return

    # 真扩量（ad_ops.set_budget：per-node advisory lock + 本币→minor units + 回读核验 + 缓存 patch + 审计）
    from ..services.ad_ops import set_budget as _set_budget
    _sr = _set_budget(db, tenant_id, acc.act_id, tgt_id, scale_level,
                      daily_budget=new_native, currency=(acc.currency or "USD"), operator="guard")
    if _sr.get("success"):
        scaled_targets.add(adset_id or ad_id)
        res["scaled"] += 1
        res["scale_details"].append({"act_id": acc.act_id, "ad_id": ad_id, "ad_name": ad_name,
                                     "level": scale_level, "target": tgt_id,
                                     "old_usd": round(cur_usd, 2), "new_usd": round(new_usd, 2)})
        _log_evt("increase_budget", "success",
                 f"{detail} | 日预算 ${cur_usd:.2f}→${new_usd:.2f} (+{pct*100:.0f}%) "
                 f"act={acc.act_id} level={scale_level} verified={_sr.get('verified')}",
                 target_id=tgt_id, target_type=scale_level,
                 metadata={"ad_id": ad_id, "act_id": acc.act_id, "level": scale_level,
                           "old_usd": round(cur_usd, 2), "new_usd": round(new_usd, 2),
                           "pct": round(pct * 100, 1), "cap_usd": cap_usd})
        _notify_evt("info",
                    (f"daily budget +{pct*100:.0f}%" if loc == "en" else f"日预算 +{pct*100:.0f}%"),
                    budget_disp, True)
    else:
        _log_evt("increase_budget", "fail",
                 f"{detail} | 加预算失败 {_sr.get('error', '')}",
                 friendly=str(_sr.get("error", ""))[:200],
                 target_id=tgt_id, target_type=scale_level)
        _notify_evt("warning",
                    ("Scale-up failed" if loc == "en" else "加预算失败"),
                    str(_sr.get("fb_error") or _sr.get("error", ""))[:300], False)


def _apply_scale_tt(db, tt, tenant_id, acc, trace_id, rule, detail, ad_id, adset_id,
                    ad_name, events, res, scaled_targets) -> None:
    """TT 扩量执行（照 _apply_scale 语义；预算载体恒为 adgroup 日预算，本币整数无 minor units）：
    读 adgroup budget → USD 口径按步长上浮（钳 max_daily_budget_usd 上限，与 FB 共用逻辑）→
    usd_to_tt_amount（tt_ad_builder 同款换算）转本币整数 → 契约函数
    tt_set_budget_daily(tt, advertiser_id, adgroup_id, daily_amount_int)（B 组 ad_ops TT 预算通道）。
    B 未合入 → ImportError 兜底=observe（只告警不动预算，不进扩量冷却——同 FB observe 语义）。
    TT CBO（adgroup 无日预算/预算在 campaign）与 BUDGET_MODE_TOTAL（总预算）不动——
    campaign 级预算 API 形状未验证（sandbox 实测后另批），跳过记日志。
    24h 冷却已在调用前 _scale_cooldown_ok 判（platform='tt' 防与 FB 行撞 target）。"""
    try:
        _rp = {k: v for k, v in (json.loads(rule.params) or {}).items()
               if v not in (None, "", [])}
    except Exception:
        _rp = {}
    _p = {**RULE_DEFAULTS.get(rule.rule_type, {}), **_rp}
    pct = max(1.0, min(float(_p.get("scale_pct", 20) or 20), 100.0)) / 100.0
    cap_usd = float(_p.get("max_daily_budget_usd", 0) or 0)
    ra = (rule.action or "default").lower()
    loc = tenant_locale(db, tenant_id)
    category = "Smart Scale-Up" if loc == "en" else "智能扩量"
    cur_code = (acc.currency or "USD").upper()

    def _log_evt(action_type, result, trigger_detail, friendly=None,
                 target_id=None, target_type="ad", metadata=None):
        events.append({"kind": "log", "kwargs": dict(
            tenant_id=tenant_id, trace_id=trace_id, actor_type="system",
            target_type=target_type, target_id=target_id or ad_id,
            action_type=action_type, source="rule_engine", result=result,
            trigger_type=rule.rule_type, trigger_detail=trigger_detail,
            friendly_error=friendly, metadata=metadata, platform="tt")})

    def _notify_evt(level, action_disp, budget_disp, force_tg):
        # 通知去重 60min/目标（同 FB _apply_scale；action_log 标记供 dedup_recent）
        if dedup_recent(db, tenant_id, "rule_scale_notified", (adset_id or ad_id), 60):
            return
        _t, _b = notify_text(loc, "rule_scale",
                             category=category, name=_esc(acc.name), act_id=acc.act_id,
                             ad_name=_esc(ad_name), ad_id=ad_id,
                             adset_id=(adset_id or '-'),
                             rule_name=_esc(rule.name), detail=_esc(detail),
                             action=_esc(action_disp), budget=_esc(budget_disp))
        if ra == "observe":
            _t = ("[Observe] " if loc == "en" else "[观察] ") + _t
        events.append({"kind": "notify", "kwargs": dict(
            tenant_id=tenant_id, level=level, event_type="rule_scale",
            trace_id=trace_id, title=_t, body=_b,
            target_type="adset", target_id=(adset_id or ad_id),
            force_tg=force_tg, platform="tt")})
        _log_evt("rule_scale_notified", "success", f"target={adset_id or ad_id}",
                 target_id=(adset_id or ad_id), target_type="adset")

    if not adset_id:
        _log_evt("increase_budget_skipped", "success", f"{detail} | 无 adset_id，跳过")
        return

    # 契约函数延迟 import（B 组并行在 ad_ops 写；services 优先、core 兜底）。
    # 未合入 → observe-only 兜底（同 P0 波次占位模式：不动预算，不进扩量冷却）
    _set_daily = None
    try:
        from ..services.ad_ops import tt_set_budget_daily as _set_daily
    except ImportError:
        try:
            from ..core.ad_ops import tt_set_budget_daily as _set_daily
        except ImportError:
            _set_daily = None
    if _set_daily is None:
        _log_evt("observe_alert", "success",
                 f"{detail} | TT 扩量预算通道未就绪，仅观察（未动预算） "
                 f"act={acc.act_id} ad={ad_id} rule={rule.name}")
        _notify_evt("info",
                    ("⚠ Alert only (observe mode, budget NOT changed)" if loc == "en"
                     else "⚠ 仅告警（观察模式，未动预算）"),
                    "-", True)
        return

    try:
        _node = tt.get_node(adset_id, "adgroup", acc.act_id,
                            ["adgroup_id", "budget", "budget_mode"]) or {}
    except Exception as e:
        _log_evt("increase_budget", "fail", f"{detail} | 读 adgroup 预算失败",
                 friendly=str(e)[:150], target_id=adset_id, target_type="adset")
        return
    try:
        cur_amount = int(float(_node.get("budget") or 0))
    except (TypeError, ValueError):
        cur_amount = 0
    _mode = str(_node.get("budget_mode") or "").upper()
    if cur_amount <= 0 or _mode in ("BUDGET_MODE_TOTAL", "BUDGET_MODE_INFINITE"):
        # BUDGET_MODE_TOTAL=总预算（语义不同不动）；INFINITE/无 budget=CBO（预算在 campaign，未验证不动）
        _log_evt("increase_budget_skipped", "success",
                 f"{detail} | adgroup 无日预算（CBO/总预算），不动",
                 target_id=adset_id, target_type="adset")
        return

    cur_usd = to_usd(float(cur_amount), cur_code)
    new_usd = cur_usd * (1.0 + pct)
    capped = False
    if cap_usd > 0:
        if cur_usd >= cap_usd:
            _log_evt("increase_budget_skipped", "success",
                     f"{detail} | 日预算已达上限 ${cur_usd:.2f}/日（cap ${cap_usd:.0f}）",
                     target_id=adset_id, target_type="adset")
            _notify_evt("info",
                        ("Daily budget cap reached, not raised" if loc == "en" else "已达日预算上限，不再加"),
                        (f"${cur_usd:.2f}/day (cap ${cap_usd:.0f})" if loc == "en"
                         else f"${cur_usd:.2f}/日（上限 ${cap_usd:.0f}）"), True)
            return
        if new_usd > cap_usd:
            new_usd = cap_usd
            capped = True
    if new_usd <= cur_usd + 0.01:
        _log_evt("increase_budget_skipped", "success",
                 f"{detail} | 目标预算≤当前（${cur_usd:.2f}）",
                 target_id=adset_id, target_type="adset")
        return
    # USD → TT 本币整数（对称逆换算：与 to_usd 用同一来源/兜底——to_usd 有硬编码
    # 字典兜底而 1.0 兜底会算出远小于当前的数 → 被下方守卫拦下静默哑火一整天）
    _usd_rate = to_usd(1.0, cur_code) or 1.0
    new_amount = max(1, int(round(new_usd / _usd_rate)))
    if new_amount <= cur_amount:
        _log_evt("increase_budget_skipped", "success",
                 f"{detail} | 目标预算≤当前（本币整数 {cur_amount}）",
                 target_id=adset_id, target_type="adset")
        return
    budget_disp = (f"${cur_usd:.2f} → ${new_usd:.2f}/day" if loc == "en" else f"${cur_usd:.2f} → ${new_usd:.2f}/日")
    if capped:
        budget_disp += (f" (cap ${cap_usd:.0f})" if loc == "en" else f"（上限 ${cap_usd:.0f}）")

    if ra == "observe":
        _log_evt("observe_alert", "success",
                 f"{detail} | 仅告警（观察） 拟 {budget_disp} act={acc.act_id} adgroup={adset_id}",
                 target_id=ad_id)
        _notify_evt("info",
                    ("⚠ Alert only (observe mode, budget NOT changed)" if loc == "en"
                     else "⚠ 仅告警（观察模式，未动预算）"),
                    ("planned: " if loc == "en" else "拟 ") + budget_disp, True)
        return

    # 真扩量：契约函数（B 组）——写+核验+审计在其内部，此处只按 bool 结果记账
    try:
        _ok = bool(_set_daily(tt, acc.act_id, adset_id, new_amount))
    except Exception as e:
        _log_evt("increase_budget", "fail", f"{detail} | 加预算异常",
                 friendly=str(e)[:200], target_id=adset_id, target_type="adset")
        _notify_evt("warning", ("Scale-up failed" if loc == "en" else "加预算失败"),
                    str(e)[:300], False)
        return
    if _ok:
        scaled_targets.add(adset_id or ad_id)
        res["scaled"] += 1
        res["scale_details"].append({"act_id": acc.act_id, "ad_id": ad_id, "ad_name": ad_name,
                                     "level": "adset", "target": adset_id, "platform": "tt",
                                     "old_usd": round(cur_usd, 2), "new_usd": round(new_usd, 2)})
        _log_evt("increase_budget", "success",
                 f"{detail} | 日预算 ${cur_usd:.2f}→${new_usd:.2f} (+{pct*100:.0f}%) "
                 f"act={acc.act_id} adgroup={adset_id} tt_amount={cur_amount}→{new_amount}",
                 target_id=adset_id, target_type="adset",
                 metadata={"ad_id": ad_id, "act_id": acc.act_id, "level": "adset",
                           "old_usd": round(cur_usd, 2), "new_usd": round(new_usd, 2),
                           "old_amount": cur_amount, "new_amount": new_amount,
                           "pct": round(pct * 100, 1), "cap_usd": cap_usd})
        _notify_evt("info",
                    (f"daily budget +{pct*100:.0f}%" if loc == "en" else f"日预算 +{pct*100:.0f}%"),
                    budget_disp, True)
    else:
        _log_evt("increase_budget", "fail",
                 f"{detail} | 加预算失败（TT 写未生效/核验未过）",
                 target_id=adset_id, target_type="adset")
        _notify_evt("warning", ("Scale-up failed" if loc == "en" else "加预算失败"),
                    "TT budget update not verified", False)


def _safe_inspect_account(ctx: dict) -> dict:
    """线程池任务包装：单账户异常不炸整轮（其余账户照常，异常回传 error 字段）。"""
    try:
        return _inspect_account_worker(ctx)
    except Exception as e:
        logger.error(f"[Guard] 账户 {ctx['acc'].act_id} 巡检异常: {e}", exc_info=True)
        return {"tenant_id": ctx["tenant_id"], "act_id": ctx["acc"].act_id,
                "evaluated": 0, "hits": 0, "paused": 0, "scaled": 0,
                "skipped_spend": 0, "learning_skipped": 0,
                "paused_details": [], "scale_details": [], "events": [],
                "error": str(e)}


def _inspect_account_worker(ctx: dict) -> dict:
    """单账户巡检任务（线程池内跑，自建 SuperSessionLocal——SQLAlchemy session 非线程安全，
    每线程私有，绝不与主线程/其他任务共享）。

    写回边界：快照/tick/令牌冷却等数据层写入用线程私有 session（ad 级数据按账户天然分区，
    无跨线程同行竞争）；write_log / emit_notification 不在本线程执行——收集为 events 队列，
    由主线程 join 后统一回放入库/发 TG（多线程不共写同一 session，通知集中过风暴上限）。
    FB 调用（FbClient）无状态线程安全；ad_ops.set_budget 自带 per-node advisory lock。
    """
    tenant_id = ctx["tenant_id"]
    acc = ctx["acc"]               # SimpleNamespace: act_id/name/currency/timezone_name
    all_rules = ctx["all_rules"]   # list[SimpleNamespace]（线程安全纯数据）
    trace_id = ctx["trace_id"]
    force = ctx["force"]
    learning_hours = ctx["learning_hours"]
    res = {"tenant_id": tenant_id, "act_id": acc.act_id, "evaluated": 0, "hits": 0,
           "paused": 0, "scaled": 0, "skipped_spend": 0, "learning_skipped": 0,
           "paused_details": [], "scale_details": [], "events": [], "error": None}
    events = res["events"]
    db = SuperSessionLocal()
    scaled_targets: set = set()  # 本账户本轮已扩量目标（同组多广告防重复；跨账户无交集）
    try:
        # 按账户选 token（查 cooldown + op_kind=read + RR 兜底）；全灭 → 跳过。
        # 平台分发：platform='tt' → tt_credentials 池选主令牌（TtClient 方法面与 FbClient duck-type）
        platform = _acc_platform(acc)
        if platform == "tt":
            from ..core.fb_tokens import tt_client_for_account
            fb, cred = tt_client_for_account(db, tenant_id, acc.act_id, "read")
            if not fb:
                return res
        else:
            cred = cred_for_account_op(db, tenant_id, acc.act_id, "read")
            if not cred:
                return res
            fb = FbClient(decrypt(cred.access_token_enc))
        _rid = str(cred.id)   # 巡检成功路径也需记录令牌身份（pause write_log 用）
        _alias = cred.alias or ""
        acc_today = _account_local_today(acc)  # 账户本地日（time_range 拉 insights + 写 snapshot_date，统一账户本地基准，避免跨时区累积）
        # 拿 ACTIVE 广告 ID 集 + 创建时间（学习期保护用）；含学习中的——学习中但 ACTIVE = 在花钱
        active_ids = None
        created_map: dict = {}
        try:
            active_ads = fb.get_active_ads(acc.act_id)
            if platform == "tt":
                # TT ad/get 字段：ad_id / create_time（FB 是 id / created_time），归一成 FB 形状
                active_ids = {_ad_id_of(a) for a in active_ads}
                created_map = {_ad_id_of(a): _norm_created(a.get("create_time"))
                               for a in active_ads}
            else:
                active_ids = {a.get("id") for a in active_ads}
                created_map = {a.get("id"): a.get("created_time") for a in active_ads}
        except Exception:
            active_ids = None  # 平台 API 拉失败，下面用 ads_cache 兜底
        # ads_cache 兜底：平台 API 失败 或 补充过滤——只评估投放中的广告
        # 避免"已停广告还有今日消耗 → 重复告警"的幽灵告警
        if active_ids is None or len(active_ids) == 0:
            try:
                _cache_row = db.query(AdsCache).filter(
                    AdsCache.tenant_id == tenant_id, AdsCache.act_id == acc.act_id,
                    AdsCache.platform == platform).first()
                if _cache_row:
                    _cache_ads = json.loads(_cache_row.ads_json or "[]")
                    _cache_ids = {_ad_id_of(_a) for _a in _cache_ads
                                  if _ad_is_active(_a, platform)}
                    created_map.update({_ad_id_of(_a):
                                        _norm_created(_a.get("created_time") or _a.get("create_time"))
                                        for _a in _cache_ads})
                    if _cache_ids:
                        active_ids = _cache_ids
                        logger.info(f"[Guard] 账户 {acc.act_id} 用 ads_cache 兜底: {len(_cache_ids)} ACTIVE")
            except Exception:
                pass
        try:
            if platform == "tt":
                # TT get_ad_insights 参数序与 FB 不同（advertiser_id, date_preset, since, until, ...）——
                # 统一走 kwargs，行已摊平（dimensions.ad_id + metrics.* 提到顶层）
                ads = fb.get_ad_insights(acc.act_id, since=acc_today, until=acc_today, limit=50)
            else:
                ads = fb.get_ad_insights(acc.act_id, "today", 50, only_active=False, since=acc_today, until=acc_today)
        except (FbApiError, TtApiError) as e:
            logger.warning(f"[Guard] 账户 {acc.act_id} 读 insights 失败: {e.friendly}")
            _cred = cred
            _alias = (_cred.alias if _cred else "") or ""
            if e.category == "token_expired":
                if _cred:
                    _cred.status = "expired"
                emit_token_expired_if_due(db, tenant_id, _alias,
                                      cred_id=(_cred.id if _cred else None))
            elif e.category in ("permissions", "permission"):
                # 权限不足告警（交接包 §6.2：分级告警）。dedup 6h/账户。此分支自带 dedup+commit，
                # 在线程私有 session 上自洽（低频、按账户去重），不经 events 队列
                if not dedup_recent(db, tenant_id, "account_permission_error", acc.act_id, 360):
                    _loc = tenant_locale(db, tenant_id)
                    _title, _body = notify_text(_loc, "account_permission_error",
                        name=_esc(acc.name), act_id=acc.act_id,
                        alias=_esc(_alias or '未命名'), friendly=_esc(e.friendly))
                    emit_notification(db, tenant_id=tenant_id, level="critical",
                        event_type="account_permission_error",
                        title=_title, body=_body, platform=platform)
                    write_log(db, tenant_id=tenant_id, trace_id=trace_id, actor_type="system",
                        target_type="account", target_id=acc.act_id,
                        action_type="account_permission_error", source="guard",
                        result="fail", trigger_detail=f"act_id={acc.act_id} alias={_alias}")
                    db.commit()
            elif e.category == "rate_limited":
                # 限流：FB 写冷却（下轮 client_for_account 跳过该 token）+ 告警；
                # TT 无 cooldown 列（TtClient 进程内自计数限流已退避封路），只告警
                if _cred and platform == "fb":
                    mark_cred_cooldown(db, _cred.id, minutes=30, status="rate_limited")
                _rid = str(_cred.id) if _cred else acc.act_id
                if not dedup_recent(db, tenant_id, "token_rate_limited", _rid, 60):
                    if platform == "tt":
                        _affected = [a.name for a in db.query(Account).filter(
                            Account.tt_credential_id == cred.id).all()] if cred else []
                    else:
                        _affected = [a.name for a in db.query(Account).filter(
                            Account.fb_credential_id == cred.id).all()] if cred else []
                    _loc = tenant_locale(db, tenant_id)
                    _t_rl, _b_rl = notify_text(_loc, "token_rate_limited",
                        alias=_esc(_alias or acc.act_id),
                        affected=_esc('、'.join(_affected[:10]) or '无'))
                    emit_notification(db, tenant_id=tenant_id, level="warning",
                        event_type="token_rate_limited",
                        title=_t_rl, body=_b_rl, platform=platform)
                    write_log(db, tenant_id=tenant_id, trace_id=trace_id, actor_type="system",
                        target_type=("tt_credential" if platform == "tt" else "fb_credential"),
                        target_id=_rid,
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
            return res
        # 建 ads_cache 投放中广告集（覆盖丢失告警用：区分"真盲区"vs"已停广告有历史消耗"）
        _cache_active_set = None
        try:
            _cr = db.query(AdsCache).filter(
                AdsCache.tenant_id == tenant_id, AdsCache.act_id == acc.act_id,
                AdsCache.platform == platform).first()
            if _cr and _cr.ads_json:
                _cache_active_set = {_ad_id_of(_a) for _a in json.loads(_cr.ads_json)
                                     if _ad_is_active(_a, platform)}
        except Exception:
            pass
        # 昨日 insights（trend_drop 用；无 trend_drop 规则可跳过省 API 调用）
        yesterday_map: dict[str, dict] = {}
        if any(r.rule_type == "trend_drop" for r in all_rules):
            try:
                yest = (datetime.strptime(acc_today, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
                if platform == "tt":
                    _y_ads = fb.get_ad_insights(acc.act_id, since=yest, until=yest, limit=50)
                else:
                    _y_ads = fb.get_ad_insights(acc.act_id, "yesterday", 50, since=yest, until=yest)
                for yad in _y_ads:
                    yesterday_map[yad.get("ad_id", "")] = yad
            except (FbApiError, TtApiError):
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
            acc_rules = [ctx["default_rule"]]

        # 趋势 tick 累计：本账户本次巡检所有 ACTIVE 广告的 spend/conv 总和（ad 循环后写一条聚合 tick）
        acc_tick_spend = 0.0
        acc_tick_conv = 0

        for ad in ads:
            ad_id = ad.get("ad_id", "")
            # tick spend + conv 累计所有广告（含已暂停——累计值不因暂停下降）
            try:
                acc_tick_spend += to_usd(float(ad.get("spend", 0)), acc.currency)
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
                            res["skipped_spend"] += 1  # ACTIVE 但被漏掉 = 真盲区
                except Exception:
                    pass
                continue  # 已停/被拒/删除的广告跳过（用户：准备中/学习中 ACTIVE 就纳入）
            # 保活广告永不停（巡检跳过 [Tova-保活] 系列）
            if "[Tova-保活]" in (ad.get("campaign_name") or ""):
                continue
            ad_objective, ad_opt_goal = obj_map.get(ad.get("campaign_id", ""), ("", ""))
            ad_name = ad.get("ad_name", ad_id)[:50]
            res["evaluated"] += 1
            spend = float(ad.get("spend", 0))
            # KPI resolver：目标感知转化数 + target_cpa（审计项目10/11）
            try:
                kpi = resolve_kpi(db, tenant_id, ad.get("campaign_id", ""),
                                  ad_objective, ad_opt_goal, ad.get("actions", []))
                conv = kpi["conversions"]
                target_cpa = kpi["target_cpa"]
                if platform == "tt" and ad.get("conversions"):
                    # TT 报表行自带 goal conversions（TT 侧已按 campaign 目标聚合）。resolver 无
                    # actions 可解析时以其兜底——防 KPI 映射缺位把有转化的 TT 广告当空耗误杀
                    try:
                        _tt_conv = int(float(ad.get("conversions") or 0))
                        if _tt_conv > conv:
                            conv = _tt_conv
                    except (TypeError, ValueError):
                        pass
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
                    # tenant 过滤：SuperSession 绕 RLS，同 ad_id 双租户导入时不能互串归因
                    landing_clicks = db.query(_f.count(_f.distinct(LandingEvent.ip_hash))).filter(
                        LandingEvent.tenant_id == tenant_id,
                        LandingEvent.ad_id == ad_id,
                        LandingEvent.event_type.in_(["click", "redirect"]),
                        LandingEvent.ip_hash.isnot(None),
                        _local_date_expr == acc_today,
                    ).scalar() or 0
                    # 访问量（visit + redirect）—— 同样按 ip_hash 去重（爬虫/同人刷新
                    # 会刷高访问量 → 空耗规则被虚假"转化"豁免）；ip_hash 为空的行不丢：
                    # COALESCE 成逐行唯一值各自计 1（worker 正常事件都带 ip_hash）
                    landing_visits = db.query(_f.count(_f.distinct(_f.coalesce(
                        LandingEvent.ip_hash, _f.concat("row:", LandingEvent.id))))).filter(
                        LandingEvent.tenant_id == tenant_id,
                        LandingEvent.ad_id == ad_id,
                        LandingEvent.event_type.in_(["visit", "redirect"]),
                        _local_date_expr == acc_today,
                    ).scalar() or 0
                except Exception:
                    pass

            # 查加白（账户本地当日跳过，和 snapshot_date / FB insights today 对齐）
            whitelisted = db.query(GuardAllowance).filter(
                GuardAllowance.tenant_id == tenant_id,   # SuperSession 绕 RLS——显式租户过滤
                GuardAllowance.act_id == acc.act_id,
                GuardAllowance.ad_id == ad_id,
                GuardAllowance.allowance_date == acc_today,
                GuardAllowance.status == "active",
            ).first()
            if whitelisted:
                continue

            # 历史快照：上一轮的今日累计 spend（budget_burn_fast）+ 近 N 天（consecutive_bad/扩量）
            prev_spend = None
            history = None
            if ctx["hist_days"] or any(r.rule_type == "budget_burn_fast" for r in all_rules):
                prev_snap = db.query(PerfSnapshot).filter(
                    PerfSnapshot.tenant_id == tenant_id,
                    PerfSnapshot.ad_id == ad_id,
                    PerfSnapshot.platform == platform,
                    PerfSnapshot.snapshot_date == biz_today,
                ).first()
                if prev_snap:
                    prev_spend = prev_snap.spend
                if ctx["hist_days"]:
                    since_date = (datetime.strptime(biz_today, "%Y-%m-%d") - timedelta(days=ctx["hist_days"])).strftime("%Y-%m-%d")
                    history = db.query(PerfSnapshot).filter(
                        PerfSnapshot.tenant_id == tenant_id,
                        PerfSnapshot.ad_id == ad_id,
                        PerfSnapshot.platform == platform,
                        PerfSnapshot.snapshot_date >= since_date,
                        PerfSnapshot.snapshot_date < biz_today,
                    ).order_by(PerfSnapshot.snapshot_date.desc()).all()

            # 学习期保护：创建 < N 小时的广告不做任何动作（FB 学习期动广告/预算会重置学习）。
            # 静默跳过规则评估（不算命中），快照照写（consecutive 历史不断档）；
            # 无创建时间（FB 拉失败且 cache 未含该字段）则不保护（fail-open，同 1.0）。
            learning_skip = False
            if learning_hours > 0 and created_map.get(ad_id):
                try:
                    _ct = datetime.strptime(str(created_map[ad_id])[:19], "%Y-%m-%dT%H:%M:%S")
                    if datetime.now(timezone.utc).replace(tzinfo=None) - _ct < timedelta(hours=learning_hours):
                        learning_skip = True
                        res["learning_skipped"] += 1
                except Exception:
                    pass

            # 评估每条规则（全局 + 本账户级，并存）；学习期广告跳过动作但仍写快照
            if not learning_skip:
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
                    # force=True（手动触发）跳过成功冷却
                    now_utc = datetime.now(timezone.utc)
                    if rule.rule_type in SCALE_RULE_TYPES:
                        # 扩量冷却：同目标 cooldown_hours 内扩过/跳过过 → 不重复（不计 hits，
                        # 防持续达标广告每 5min 刷计数/日志）。TT 传 platform='tt'（小整数
                        # adset_id 防撞 FB 行），FB 不传 → 查询与原逻辑零差异
                        if not _scale_cooldown_ok(db, tenant_id, rule, ad_id,
                                                  ad.get("adset_id", ""), scaled_targets, now_utc,
                                                  platform=("tt" if platform == "tt" else None)):
                            continue
                    else:
                        succ = None
                        # 平台隔离（照 _scale_cooldown_ok 模式）：TT 小整数 ad_id 与 FB
                        # 撞号时互相吞停；FB 存量日志全回填 'fb'，过滤对 FB 零差异
                        _pf = [ActionLog.platform == platform] if platform == "tt" else []
                        if not force:
                            succ_cd = now_utc - timedelta(minutes=COOLDOWN_MIN)
                            succ = db.query(ActionLog).filter(
                                ActionLog.tenant_id == tenant_id,
                                ActionLog.target_id == ad_id,
                                ActionLog.trigger_type == rule.rule_type,
                                # observe 规则记 observe_alert（不再是"pause"）——冷却同样认它，
                                # 否则 observe 每 5min 巡检都重写一条日志（通知侧另有 60min dedup）
                                ActionLog.action_type.in_(["pause", "observe_alert"]),
                                ActionLog.result == "success",
                                *_pf,
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
                            *_pf,
                            ActionLog.created_at >= fail_cd,
                        ).first()
                        if fail_recent:
                            continue  # 近 5min 暂停失败过，等下轮重试（不每轮 hammer）

                    res["hits"] += 1
                    category = RULE_CATEGORY.get(rule.rule_type, "止损")
                    campaign_id = ad.get("campaign_id", "")
                    adset_id = ad.get("adset_id", "")
                    logger.info(f"[Guard] 命中！租户{tenant_id} 账户{acc.act_id} "
                                f"广告[{ad_name}] 规则[{rule.name}] {detail}")

                    # ── 扩量规则：加预算（observe=只告警），不走暂停链 ──
                    if rule.rule_type in SCALE_RULE_TYPES:
                        if platform == "tt":
                            # TT 扩量（P1-7）：_apply_scale_tt——契约函数 tt_set_budget_daily
                            # （B 组 ad_ops）可用即真扩量；未合入 ImportError 兜底=observe（函数内处理）。
                            # 上限钳制/observe 语义与 FB _apply_scale 对齐
                            try:
                                _apply_scale_tt(db, fb, tenant_id, acc, trace_id, rule, detail,
                                                ad_id, adset_id, ad_name,
                                                events, res, scaled_targets)
                            except Exception as _se:
                                logger.warning(f"[Guard] TT 扩量执行异常 ad={ad_id}: {_se}",
                                               exc_info=True)
                                events.append({"kind": "log", "kwargs": dict(
                                    tenant_id=tenant_id, trace_id=trace_id, actor_type="system",
                                    target_type="adset", target_id=(adset_id or ad_id),
                                    action_type="increase_budget", source="rule_engine",
                                    result="fail", trigger_type=rule.rule_type,
                                    trigger_detail=f"{detail} | TT 扩量执行异常",
                                    friendly_error=str(_se)[:200], platform="tt")})
                            db.commit()
                            break  # 一条广告命中一条规则即止
                        try:
                            _apply_scale(db, fb, tenant_id, acc, trace_id, rule, detail,
                                         ad_id, adset_id, campaign_id, ad_name,
                                         events, res, scaled_targets)
                        except Exception as _se:
                            logger.warning(f"[Guard] 扩量执行异常 ad={ad_id}: {_se}", exc_info=True)
                            events.append({"kind": "log", "kwargs": dict(
                                tenant_id=tenant_id, trace_id=trace_id, actor_type="system",
                                target_type="adset", target_id=(adset_id or ad_id),
                                action_type="increase_budget", source="rule_engine",
                                result="fail", trigger_type=rule.rule_type,
                                trigger_detail=f"{detail} | 扩量执行异常",
                                friendly_error=str(_se)[:200])})
                        db.commit()
                        break  # 一条广告命中一条规则即止

                    # ── 止损规则：observe=只告警；其余=动态升级暂停 ──
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
                                if platform == "tt":
                                    fb.pause_ad(acc.act_id, pid)  # TT pause_ad(advertiser_id, ad_id)=opt_status DISABLE
                                else:
                                    fb.pause_ad(pid)  # pause_ad 对 ad/adset/campaign 通用
                                # A2 核验（ad 级）：停后单查状态，仍投放中=假停→升级下一级
                                # 单查比 get_active_ads(拉全账户+缓存) 快且准；sleep 2.5s 等平台写延迟
                                if pid == ad_id:
                                    time.sleep(2.5)
                                    try:
                                        if platform == "tt":
                                            _node = fb.get_node(pid, "ad", acc.act_id) or {}
                                            _still = str(_node.get("opt_status")
                                                         or _node.get("status") or "").upper()
                                            if _still in ("ENABLE", "STATUS_ENABLE"):
                                                continue  # 假停，升级下一级
                                        else:
                                            _node = fb.get_node(pid, "effective_status")
                                            if str(_node.get("effective_status", "")).upper() == "ACTIVE":
                                                continue  # 假停，升级下一级
                                    except Exception:
                                        pass  # 核验查询失败，信任平台（视为成功，不升级）——宁可少停不误停整组
                                res["paused"] += 1
                                res["paused_details"].append({"act_id": acc.act_id, "ad_id": ad_id,
                                                              "ad_name": ad_name, "level": label,
                                                              "target": pid, "reason": detail})
                                action_text = f"已暂停{label} PAUSED" + ("（已核验）" if pid == ad_id else "")
                                paused_ok = True
                                break
                            except (FbApiError, TtApiError) as _pause_err:
                                # 记录平台 code/错误原文供排障（交接包 pitfall#7：不丢弃错误码）
                                logger.warning(f"[Guard] 暂停{label}失败 ad={ad_id} pid={pid} code={getattr(_pause_err,'category','')} raw={str(getattr(_pause_err,'raw',''))[:100]}")
                                continue  # 该级暂停失败，升级下一级
                        if not paused_ok:
                            action_text = "暂停失败（ad→组→系列均未生效）"
                            pause_result = "fail"

                    # 记日志（账户/系列/组/广告 ID + 本币花销 + 动作 + trace_id）——events 队列，主线程回放
                    # observe 分支记 observe_alert（日志中心 action 筛选是自由文本，
                    # 不与 pause 混淆——用户能区分"真停了"vs"只告警"）
                    events.append({"kind": "log", "kwargs": dict(
                        tenant_id=tenant_id, trace_id=trace_id,
                        actor_type="system", target_type="ad", target_id=ad_id,
                        action_type="observe_alert" if ra == "observe" else "pause",
                        source="rule_engine", result=pause_result,
                        platform=platform,
                        trigger_type=rule.rule_type,
                        trigger_detail=f"{detail} | act={acc.act_id}({acc.currency}) "
                                       f"camp={campaign_id} adset={adset_id} ad={ad_id} "
                                       f"spend={fmt_spend(spend, acc.currency)} "
                                       f"conv={conv} action={action_text}",
                        metadata={"campaign_id": campaign_id, "adset_id": adset_id,
                                  "ad_id": ad_id, "act_id": acc.act_id,
                                  "currency": acc.currency, "rule_action": ra,
                                  "action": action_text,
                                  "cred_id": _rid, "cred_alias": _alias})})

                    # 通知（去重 60min/广告：已停广告每轮重复命中不应重复 notify）
                    if not dedup_recent(db, tenant_id, "rule_pause_notified", ad_id, 60):
                        _loc = tenant_locale(db, tenant_id)
                        # 动作位：observe 必须显式说"未暂停"（消息与真暂停区分，防用户误读）
                        if ra == "observe":
                            _action_disp = ("⚠ Alert only (observe mode, NOT paused)"
                                            if _loc == "en" else "⚠ 仅告警（观察模式，未暂停）")
                        else:
                            _action_disp = action_text  # 已暂停广告/组/系列 PAUSED… / 暂停失败…
                        _t_rp, _b_rp = notify_text(_loc, "rule_pause",
                            category=_esc(category), name=_esc(acc.name),
                            act_id=acc.act_id, ad_name=_esc(ad_name), ad_id=ad_id,
                            adset_id=(adset_id or '-'), campaign_id=(campaign_id or '-'),
                            rule_name=_esc(rule.name), detail=_esc(detail),
                            action=_action_disp,
                            spend=fmt_spend(spend, acc.currency), conv=conv,
                            kpi_label=_esc(kpi.get('kpi_label') or '-'),
                            source_label=_esc(SOURCE_LABELS.get(kpi.get('source'), kpi.get('source') or '-')))
                        if ra == "observe":
                            _t_rp = ("[Observe] " if _loc == "en" else "[观察] ") + _t_rp
                        events.append({"kind": "notify", "kwargs": dict(
                            tenant_id=tenant_id, level="warning",
                            event_type="rule_pause", trace_id=trace_id,
                            title=_t_rp, body=_b_rp,
                            target_type="ad", target_id=ad_id,
                            platform=platform,
                            reply_markup={"inline_keyboard": [[
                                {"text": "🛲 加白今日", "callback_data": f"allow|{tenant_id}|{acc.act_id}|{ad_id}"}
                            ]]})})
                        events.append({"kind": "log", "kwargs": dict(
                            tenant_id=tenant_id, trace_id=trace_id,
                            actor_type="system", target_type="ad", target_id=ad_id,
                            action_type="rule_pause_notified", source="rule_engine",
                            result="success", trigger_detail=f"ad={ad_id}")})

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
                    PerfSnapshot.tenant_id == tenant_id,
                    PerfSnapshot.ad_id == ad_id,
                    PerfSnapshot.platform == platform,
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
                        platform=platform,
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
        return res
    except Exception as e:
        logger.error(f"[Guard] 账户 {acc.act_id} 巡检任务异常: {e}", exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        res["error"] = str(e)
        return res
    finally:
        db.close()


def run_inspection(force: bool = False):
    """巡检主函数（并发版）。遍历所有租户，评估规则，命中按 rule.action 动作。

    动作由 rule.action 唯一控制（observe=只告警 / pause*=止损暂停链 / scale=扩量加预算）
    ——无全局 dry_run（2026-07-07 用户决策）。
    规则作用域：全局(scope_act_id NULL=名下所有账户) + 账户级(scope_act_id=指定账户)，并存各评估。
    并发（1.0 移植）：账户级 ThreadPoolExecutor，guard_concurrency（1-8，默认 4）；
        每任务线程自建 SuperSessionLocal（session 非线程安全）；日志/通知收口主线程回放（events）。
    学习期保护：guard_learning_hours（默认 24h，0=关）——创建 < N 小时的广告静默跳过（心跳计数）。
    多 worker 进程：advisory lock 101 保证每轮只有一个 worker 真跑（防 TG spam）。
    force=True 跳过成功冷却（手动触发用；替代旧"改全局 COOLDOWN_MIN"的竞态写法）。
    """
    lock = acquire_run_lock(101)
    if not lock:
        return {"skipped": "lock_busy"}
    db = SuperSessionLocal()
    trace_id = new_trace_id()
    total_evaluated = 0
    total_hits = 0
    total_paused = 0
    total_scaled = 0
    total_learning = 0
    total_skipped_spend = 0  # 有消耗但被 active_ids 过滤掉的广告数（覆盖丢失，止损盲区）
    _tenant_skipped: dict = {}  # 按租户分桶（coverage_lost 告警要发给正确的租户）
    paused_details = []  # [{act_id, ad_id, ad_name, level, target, reason}]
    scale_details = []   # [{act_id, ad_id, ad_name, level, target, old_usd, new_usd}]

    try:
        learning_hours = _sys_float(db, "guard_learning_hours", DEFAULT_LEARNING_HOURS)
        # 取所有有 active FB 凭证的租户（不只 guard_rules——租户无规则也巡检，注入保底止血线，防裸奔），
        # 并上「有 managed TT 账户」的租户——纯 TT 租户（无任何 FB 凭证）不再被整个跳过。
        # FB 租户集合不变（有 FB 账户必有 FB 凭证），遍历顺序 FB 在前 → FB 行为不变
        _fb_tids = [tid for (tid,) in db.query(FbCredential.tenant_id).filter(
            FbCredential.status == "active"
        ).distinct().all()]
        _tt_tids = {tid for (tid,) in db.query(Account.tenant_id).filter(
            Account.platform == "tt",
            Account.is_managed.is_(True),
        ).distinct().all()}
        _seen_tids = set(_fb_tids)
        tenant_ids = [(t,) for t in _fb_tids] + [(t,) for t in sorted(_tt_tids - _seen_tids)]

        tasks = []
        for (tenant_id,) in tenant_ids:
            all_rules = db.query(GuardRule).filter(
                GuardRule.tenant_id == tenant_id,
                GuardRule.enabled == True,
            ).all()
            if not all_rules:
                # 规则兜底：租户无规则时注入默认空耗止血线（保底防裸奔，用户可建规则覆盖）
                all_rules = [_DEFAULT_BLEED_ABS_RULE]
            # 本租户无 active FB 凭证且无 managed TT 账户 → 没有 token 可读，跳过（worker 内还会按账户再选 token）
            cred_n = db.query(FbCredential).filter(
                FbCredential.tenant_id == tenant_id,
                FbCredential.status == "active",
            ).count()
            if not cred_n and tenant_id not in _tt_tids:
                logger.info(f"[Guard] 租户 {tenant_id} 无 FB 凭证且无 TT 账户，跳过")
                continue
            # 取已纳管账户（is_managed=true 且 ACTIVE=1，跳过被 FB 禁用/宽限/违规的，省 Token 配额；
            # 也跳过已取消纳管的软删账户——它们保留历史但不再巡检）
            accounts = db.query(Account).filter(
                Account.tenant_id == tenant_id,
                Account.account_status == 1,
                Account.is_managed.is_(True),
            ).all()

            hist_days = _max_history_days(all_rules)  # consecutive_bad/扩量 需要的历史天数
            rule_ctxs = [_rule_ctx(r) for r in all_rules]

            for acc in accounts:
                acc.last_inspected_at = datetime.now(timezone.utc)
                # 哨兵 armed → 巡检跳过（哨兵全停，巡检再跑多余 → 省 FB API）
                if acc.sentinel_armed or acc.sentinel_auto_armed:
                    continue
                tasks.append({
                    "tenant_id": tenant_id, "trace_id": trace_id, "force": force,
                    "learning_hours": learning_hours, "hist_days": hist_days,
                    "all_rules": rule_ctxs, "default_rule": _DEFAULT_BLEED_RULE_CTX,
                    "acc": SimpleNamespace(act_id=acc.act_id, name=acc.name,
                                           currency=acc.currency, timezone_name=acc.timezone_name,
                                           platform=_acc_platform(acc)),
                })

        workers = _max_workers(db, len(tasks))
        logger.info(f"[Guard] 巡检 {len(tasks)} 个账户，并发 {workers}")
        results = []
        if workers <= 1 or len(tasks) <= 1:
            for t in tasks:
                results.append(_safe_inspect_account(t))
        else:
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="guard") as executor:
                futs = [executor.submit(_safe_inspect_account, t) for t in tasks]
                for fut in as_completed(futs):
                    results.append(fut.result())

        # ── 主线程汇总 + 事件回放（日志/通知统一过主 session：多线程不共写；风暴上限集中生效）──
        for _res in results:
            total_evaluated += _res.get("evaluated", 0)
            total_hits += _res.get("hits", 0)
            total_paused += _res.get("paused", 0)
            total_scaled += _res.get("scaled", 0)
            total_learning += _res.get("learning_skipped", 0)
            total_skipped_spend += _res.get("skipped_spend", 0)
            paused_details.extend(_res.get("paused_details") or [])
            scale_details.extend(_res.get("scale_details") or [])
            _sk = _res.get("skipped_spend", 0)
            if _sk > 0:
                _tenant_skipped[_res["tenant_id"]] = _tenant_skipped.get(_res["tenant_id"], 0) + _sk
            for _e in (_res.get("events") or []):
                try:
                    if _e.get("kind") == "log":
                        write_log(db, **_e["kwargs"])
                    elif _e.get("kind") == "notify":
                        emit_notification(db, **_e["kwargs"])
                except Exception as _ex:
                    logger.warning(f"[Guard] 事件回放失败 kind={_e.get('kind')}: {_ex}")
            try:
                db.commit()
            except Exception:
                db.rollback()

        logger.info(f"[Guard] 巡检完成: 评估 {total_evaluated} 条广告, "
                    f"命中 {total_hits}, 停止 {total_paused}, 扩量 {total_scaled}, "
                    f"学习期跳过 {total_learning} (LIVE，按 rule.action)")
        # 巡检心跳（watchdog 用：长时间无成功心跳 = 巡检停滞）
        write_log(db, tenant_id=1, trace_id=trace_id, actor_type="system",
                  target_type="scheduler", action_type="inspection_heartbeat",
                  source="scheduled", result="success",
                  trigger_detail=f"评估{total_evaluated}条广告 · 命中{total_hits}条 · 停{total_paused} · "
                                 f"扩量{total_scaled} · 学习期跳过{total_learning} · "
                                 f"跳过{total_skipped_spend}条有消耗广告")
        # 覆盖丢失告警：按租户分桶（原实现用循环残留 tenant_id → 发错租户+压制真盲区租户的告警）
        for _tid, _skipped in _tenant_skipped.items():
            if _skipped <= 0:
                continue
            if dedup_recent(db, _tid, "coverage_lost", "*", 360):
                continue
            # 写 action_log 让 dedup_recent 下轮命中（6h 内不再重复发）
            write_log(db, tenant_id=_tid, trace_id=trace_id,
                      actor_type="system", target_type="ad", target_id="*",
                      action_type="coverage_lost", source="guard", result="success",
                      trigger_detail=f"skipped={_skipped}")
            _loc = tenant_locale(db, _tid)
            _t_cl, _b_cl = notify_text(_loc, "coverage_lost", n=_skipped)
            emit_notification(
                db, tenant_id=_tid, level="warning",
                event_type="coverage_lost", trace_id=trace_id,
                title=_t_cl, body=_b_cl, platform="fb",
            )
        db.commit()
        return {"evaluated": total_evaluated, "hits": total_hits, "paused": total_paused,
                "scaled": total_scaled, "learning_skipped": total_learning,
                "skipped_spend": total_skipped_spend, "details": paused_details,
                "scale_details": scale_details}

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
                _loc = tenant_locale(db, 1)
                _t_is, _b_is = notify_text(_loc, "inspection_stalled", minutes=INSPECTION_STALL_MIN)
                emit_notification(db, tenant_id=1, level="critical",
                                  event_type="inspection_stalled", trace_id=trace_id,
                                  title=_t_is, body=_b_is, platform="fb")
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
                _loc = tenant_locale(db, c.tenant_id)
                _t_ti, _b_ti = notify_text(_loc, "token_invalid", alias=(c.alias or c.id))
                emit_notification(db, tenant_id=c.tenant_id, level="critical",
                                  event_type="token_invalid", trace_id=trace_id,
                                  title=_t_ti, body=_b_ti, platform="fb")
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
                        _loc = tenant_locale(db, c.tenant_id)
                        _t_te, _b_te = notify_text(_loc, "token_expiring_soon",
                                                   alias=(c.alias or c.id), days=remaining.days)
                        emit_notification(db, tenant_id=c.tenant_id, level="warning",
                                          event_type="token_expiring_soon", trace_id=trace_id,
                                          title=_t_te, body=_b_te, platform="fb")
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


def run_landing_block_scan():
    """定时 FB 屏蔽探测（每 1h）：对所有 published 落地页跑完整自检（含 FB Graph scrape），
    持久化 last_fb_status + last_health_*，屏蔽则 emit critical 告警。
    复用 _run_self_check 保持与手动 /health 完全一致；first_client 取令牌（多令牌场景由 first_client 兜底）。
    不做自动切换（切换需改 FB 广告 URL，风险高）——只告知，人工处理。
    """
    from datetime import datetime as _dt, timezone as _tz
    from ..models.launch import LandingPage
    from ..routers.landing import _run_self_check, _emit_health_alert
    lock = acquire_run_lock(107)
    if not lock:
        return {"skipped": "lock_busy"}
    db = SuperSessionLocal()
    try:
        pages = db.query(LandingPage).filter(
            LandingPage.status == "published",
            LandingPage.custom_domain.isnot(None),
        ).all()
        scanned = blocked = 0
        for p in pages:
            try:
                res = _run_self_check(db, p, include_fb=True, live_probe=True)
                # FB 屏蔽态：fb_ban + fb_subcode 取最差（fail>warn>pass；无 FB 检查项=令牌不可用→null）
                fb_checks = [c for c in (res.get("checks") or []) if c.get("key") in ("fb_ban", "fb_subcode")]
                if not fb_checks:
                    fb_status = None
                elif any(c.get("status") == "fail" for c in fb_checks):
                    fb_status = "fail"
                elif any(c.get("status") == "warn" for c in fb_checks):
                    fb_status = "warn"
                else:
                    fb_status = "pass"
                now = _dt.now(_tz.utc)
                p.last_health_status = res.get("overall")
                p.last_health_summary = res.get("summary")
                p.last_health_checked_at = now
                p.last_fb_status = fb_status
                p.last_fb_checked_at = now
                db.commit()
                scanned += 1
                if fb_status == "fail":
                    blocked += 1
                _emit_health_alert(db, p, res)  # fb 屏蔽→critical；6h dedup per page
            except Exception as e:
                logger.warning(f"[LandingBlockScan] page {getattr(p,'id','?')} 失败: {e}")
                db.rollback()
        if blocked:
            logger.info(f"[LandingBlockScan] 扫描 {scanned} 页，{blocked} 个疑似被 FB 屏蔽")
        return {"scanned": scanned, "blocked": blocked}
    except Exception as e:
        logger.error(f"[LandingBlockScan] 异常: {e}", exc_info=True)
        return {"error": str(e)}
    finally:
        db.close()
        release_run_lock(lock, 107)


def _sentinel_pause_tt(db, tt, acc, trace_id: str) -> int:
    """哨兵 TT 分支：投放中广告逐条 ad 级 DISABLE（kill-switch，同义 FB 的 campaign 全停——
    get_active_ads 只返投放中，全停等价）。
    级别选择：campaign/status/update 的批量形状未在 sandbox 验证，先 ad 级（验证后可升 campaign 级）。
    dedup：每广告 1h 内已停过跳过（ActionLog platform='tt'——TT ad_id 每广告主小整数，
    不过滤会与 FB 行/另一广告主撞 target）。返回停掉的条数。"""
    paused = 0
    try:
        active_ads = tt.get_active_ads(acc.act_id)
    except Exception as e:
        logger.warning(f"[Sentinel][TT] 账户 {acc.act_id} 拉广告失败: {getattr(e, 'friendly', e)}")
        return 0
    for a in active_ads:
        ad_id = str(a.get("ad_id") or a.get("id") or "")
        ad_name = (a.get("ad_name") or "")[:60]
        if not ad_id:
            continue
        # 保活广告永不停（哨兵跳过 [Tova-保活]，同 FB）
        if "[Tova-保活]" in ad_name:
            continue
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        already = db.query(ActionLog).filter(
            ActionLog.tenant_id == acc.tenant_id,
            ActionLog.target_id == ad_id,
            ActionLog.action_type == "pause",
            ActionLog.trigger_type == "sentinel",
            ActionLog.platform == "tt",
            ActionLog.created_at >= since,
        ).first()
        if already:
            continue
        try:
            tt.update_status(ad_id, "PAUSED", "ad", acc.act_id)  # opt_status=DISABLE
            paused += 1
            write_log(db, tenant_id=acc.tenant_id, trace_id=trace_id, actor_type="sentinel",
                      target_type="ad", target_id=ad_id,
                      action_type="pause", source="sentinel_patrol", result="success",
                      trigger_type="sentinel", platform="tt",
                      trigger_detail=f"[TT] sentinel armed, ad {ad_name} 直接停")
            _loc = tenant_locale(db, acc.tenant_id)
            _t_sp, _b_sp = notify_text(_loc, "sentinel_pause_ad",
                                       name=acc.name, act_id=acc.act_id,
                                       ad_name=ad_name or ad_id, ad_id=ad_id)
            emit_notification(db, tenant_id=acc.tenant_id, level="critical",
                              event_type="sentinel_pause", trace_id=trace_id,
                              title=_t_sp, body=_b_sp, platform="tt")
            db.commit()
        except Exception as e:
            logger.warning(f"[Sentinel][TT] 停广告 {ad_id} 失败: {getattr(e, 'friendly', e)}")
    return paused


def run_sentinel_patrol():
    """哨兵巡逻（doc 03 §4，1.0 sentinel_patrol 移植）：armed 账户的 ACTIVE 系列→直接全停。

    哨兵是 kill-switch（不走规则评估）：手动 arm 或自动 arm 后，发现 ACTIVE 系列直接停。
    FB 走 campaign 级全停；TT（P4）走 ad 级 DISABLE（_sentinel_pause_tt）。
    与规则巡检独立。dedup：每 campaign（FB）/每广告（TT）1h 内不重复停。
    """
    lock = acquire_run_lock(106)
    if not lock:
        return {"skipped": "lock_busy"}
    db = SuperSessionLocal()
    trace_id = new_trace_id()
    total_paused = 0
    try:
        # 所有 armed 账户（手动或自动 arm，含 TT）；排除已取消纳管的（is_managed=false）
        armed = db.query(Account).filter(
            Account.is_managed.is_(True),
            (Account.sentinel_armed == True) | (Account.sentinel_auto_armed == True)  # noqa: E712
        ).all()
        for acc in armed:
            # 死账户（禁用/封号/支付失败等，account_status!=1）花不了钱，停系列是马后炮→跳过。
            # 恢复正常(status→1)后哨兵自然恢复生效：armed 仍在，account_sync 把状态刷回 1 后下轮就停。
            if acc.account_status is not None and acc.account_status != 1:
                continue
            # 预热账户哨兵也跑（只跳过保活系列）
            if (acc.platform or "fb") == "tt":
                from ..core.fb_tokens import tt_client_for_account
                tt, _cred = tt_client_for_account(db, acc.tenant_id, acc.act_id, "pause")
                if not tt:
                    continue
                total_paused += _sentinel_pause_tt(db, tt, acc, trace_id)
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
                # 保活系列永不停（哨兵跳过 [Tova-保活]）
                if "[Tova-保活]" in (camp.get("name") or ""):
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
                    _loc = tenant_locale(db, acc.tenant_id)
                    _t_sp, _b_sp = notify_text(_loc, "sentinel_pause",
                        name=acc.name, act_id=acc.act_id,
                        camp_name=camp.get('name',''), camp_id=camp_id)
                    emit_notification(db, tenant_id=acc.tenant_id, level="critical",
                                      event_type="sentinel_pause", trace_id=trace_id,
                                      title=_t_sp, body=_b_sp, platform="fb")
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
        # 建未绑子码 set（按租户分组遍历）；排除已取消纳管的账户。
        # 子码绑定走 FB /adcreatives 反查，TT 账户明确排除
        accounts = db.query(Account).filter(
            Account.account_status == 1, Account.is_managed.is_(True),
            Account.platform == "fb").all()
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
                    _loc = tenant_locale(db, tid)
                    _t_sc, _b_sc = notify_text(_loc, "subcode_cleanup", n=len(slugs))
                    emit_notification(db, tenant_id=tid, level="info", send_tg=False,
                        event_type="subcode_cleanup",
                        title=_t_sc, body=_b_sc, platform="fb")
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


def _ka_rollback(fb, ids):
    """建保活任一步失败时回滚已建的 campaign/adset/creative，避免 orphan 系列卡住去重（下次跳过）。"""
    for oid in reversed(ids):
        try:
            fb._request("DELETE", oid)
        except Exception:
            pass


def _ka_res(acc, result, category, reason=""):
    """保活每账户结果条目（result=success/skip/fail + category 供前端 i18n 翻译原因）。"""
    return {"act_id": acc.act_id, "name": acc.name or acc.act_id,
            "result": result, "category": category, "reason": reason}


def run_keepalive():
    """每日保活扫描：warming 账户连续 idle_days 天无消耗 → 建 $5 lifetime Page Like。
    保活广告 campaign_name 含 [Tova-保活] → 巡检/哨兵跳过不停。花完 $5 自动停（FB lifetime_budget）。
    """
    import os, random
    from ..core.keepalive_config import get_keepalive_config, DEFAULT_KEEPALIVE
    from ..core.fb_tokens import client_for_account
    from ..core.ad_ops import ensure_image_hash_for_account
    from ..models.launch import Asset
    from ..models.perf import PerfSnapshot
    from sqlalchemy import func as _f

    lock = acquire_run_lock(109)
    if not lock:
        return {"skipped": "lock_busy"}
    db = SuperSessionLocal()
    try:
        # 按租户读配置（各团队自己管保活参数）
        from collections import defaultdict
        tenant_cfgs = {}
        for row in db.query(SystemSetting).filter(SystemSetting.key.like("keepalive:%")).all():
            try: tenant_cfgs[int(row.key.split(":")[1])] = json.loads(row.value)
            except: pass
        asset_dir = os.environ.get("ASSET_DIR", "/opt/toveads/assets")

        # 汇总所有需保活的账户：租户 enabled=true → 该租户全部 managed 账户；否则 → 仅 warming。
        # 保活建的是 FB Page Like（object_story_spec 链路），TT 账户明确排除
        from sqlalchemy import or_
        warming_q = db.query(Account).filter(
            Account.is_managed == True,  # noqa: E712
            Account.account_status == 1,
            Account.platform == "fb",
        )
        enabled_tenants = {tid for tid, c in tenant_cfgs.items() if c.get("enabled")}
        if enabled_tenants:
            warming_q = warming_q.filter(or_(
                Account.warmup_state == "warming",
                Account.tenant_id.in_(enabled_tenants),
            ))
        else:
            warming_q = warming_q.filter(Account.warmup_state == "warming")
        warming = warming_q.all()

        created = skipped = failed = 0
        results = []  # 每账户结果（success/skip/fail + category），供前端结果弹窗
        for acc in warming:
            built = []
            fb = None
            try:
                # 该账户所属租户的保活配置（没配的用默认值）
                cfg = tenant_cfgs.get(acc.tenant_id) or dict(DEFAULT_KEEPALIVE)
                for dk, dv in DEFAULT_KEEPALIVE.items():
                    cfg.setdefault(dk, dv)
                prefix = cfg["campaign_prefix"]
                idle_days = cfg["idle_days"]
                budget = int(float(cfg["budget_usd"]) * 100)
                asset_prefix = cfg["asset_prefix"]
                cutoff = (datetime.now(timezone.utc) - timedelta(days=idle_days)).strftime("%Y-%m-%d")

                # 1. 近 idle_days 天消耗（platform='fb'：防跨平台 act_id 撞号把 TT 消耗算进来）
                spend = db.query(_f.sum(PerfSnapshot.spend)).filter(
                    PerfSnapshot.tenant_id == acc.tenant_id,
                    PerfSnapshot.act_id == acc.act_id,
                    PerfSnapshot.platform == "fb",
                    PerfSnapshot.snapshot_date >= cutoff,
                ).scalar() or 0
                if float(spend) > 0:
                    results.append(_ka_res(acc, "skip", "has_spend", "近期有消耗，无需保活")); skipped += 1
                    continue

                # 2. 写令牌
                fb = client_for_account(db, acc.tenant_id, acc.act_id, "write")
                if not fb:
                    results.append(_ka_res(acc, "skip", "no_write_token", "无写令牌")); skipped += 1
                    continue

                # 3. 已有保活系列？(ACTIVE/PAUSED/PENDING 都算=建过了)
                camps = fb.get(f"act_{acc.act_id}/campaigns", {
                    "fields": "id,name,effective_status", "limit": 200,
                })
                has_keepalive = any(
                    prefix in (c.get("name") or "")
                    and (c.get("effective_status") in ("ACTIVE", "PAUSED", "PENDING_REVIEW", "IN_PROCESS", "WITH_ISSUES"))
                    for c in (camps.get("data") or [])
                )
                if has_keepalive:
                    skipped += 1; results.append(_ka_res(acc, "skip", "has_keepalive", "已有保活广告"))
                    continue

                # 4. 获取主页
                pages = fb.get_pages()
                if not pages:
                    failed += 1; results.append(_ka_res(acc, "fail", "no_page", "无可用主页"))
                    continue
                page_id = pages[0].get("id")

                # 5. 选素材（租户内 YR 前缀随机——BYPASSRLS 必须显式 tenant 过滤）
                assets_q = db.query(Asset).filter(
                    Asset.name.like(f"{asset_prefix}%"), Asset.type == "image",
                    Asset.tenant_id == acc.tenant_id,
                ).all()
                if not assets_q:
                    failed += 1; results.append(_ka_res(acc, "fail", "no_asset", f"无 {asset_prefix} 保活素材"))
                    continue
                asset = random.choice(assets_q)
                filepath = os.path.join(asset_dir, asset.storage_key)
                if not os.path.exists(filepath):
                    failed += 1; results.append(_ka_res(acc, "fail", "asset_missing", "素材文件丢失"))
                    continue
                # 素材 image_hash + 随机 AI 文案+标题（object_story_spec 模式，完整内容+CTA）
                from ..core.ad_ops import ensure_image_hash_for_account, pick_random_copy
                image_hash = ensure_image_hash_for_account(fb, db, asset, acc.act_id, filepath)
                db.commit()
                _rh, _rb = pick_random_copy(asset)
                _ka_msg = _rb or "Welcome!"
                _ka_name = _rh or "Like our page"

                # 6. 建 Page Like（campaign→adset→creative→ad；任一步失败 _ka_rollback 回滚已建对象，避免 orphan 卡去重）
                camp = fb.post(f"act_{acc.act_id}/campaigns", {
                    "name": f"{prefix} Page Like", "objective": "OUTCOME_ENGAGEMENT",
                    "status": "ACTIVE", "buying_type": "AUCTION", "special_ad_categories": [],
                    "is_adset_budget_sharing_enabled": False,
                })
                camp_id = camp.get("id")
                if not camp_id:
                    raise Exception(f"FB 未返回 campaign_id: {str(camp)[:200]}")
                built.append(camp_id)
                adset = fb.post(f"act_{acc.act_id}/adsets", {
                    "name": f"{prefix} AdSet", "campaign_id": camp_id, "status": "ACTIVE",
                    "optimization_goal": "PAGE_LIKES", "billing_event": "IMPRESSIONS",
                    "bid_strategy": "LOWEST_COST_WITHOUT_CAP", "destination_type": "ON_PAGE",
                    "promoted_object": json.dumps({"page_id": page_id}),
                    "targeting": json.dumps({"geo_locations": {"countries": ["US"]}, "age_min": 18, "age_max": 65}),
                    # lifetime=总预算花完自动停（配置语义；原误用 daily_budget=$5/天无上限烧钱）
                    "lifetime_budget": str(budget),
                })
                adset_id = adset.get("id")
                if not adset_id:
                    raise Exception(f"FB 未返回 adset_id: {str(adset)[:200]}")
                built.append(adset_id)
                creative = fb.post(f"act_{acc.act_id}/adcreatives", {
                    "name": f"{prefix} Creative",
                    "object_story_spec": json.dumps({
                        "page_id": page_id,
                        "link_data": {
                            "image_hash": image_hash,
                            "message": _ka_msg,
                            "name": _ka_name,
                            "link": f"https://www.facebook.com/{page_id}",
                            "call_to_action": {"type": "LIKE_PAGE"}
                        }
                    })
                })
                creative_id = creative.get("id")
                if not creative_id:
                    raise Exception(f"FB 未返回 creative_id: {str(creative)[:200]}")
                built.append(creative_id)
                ad = fb.post(f"act_{acc.act_id}/ads", {
                    "name": f"{prefix} Ad", "adset_id": adset_id,
                    "creative": json.dumps({"creative_id": creative_id}), "status": "ACTIVE",
                })
                ad_id = ad.get("id") or ""
                created += 1
                results.append(_ka_res(acc, "success", "ok"))
                write_log(db, tenant_id=acc.tenant_id, trace_id=new_trace_id(),
                          actor_type="system", target_type="ad", target_id=str(ad_id),
                          action_type="keepalive", source="keepalive", result="success",
                          metadata={"act_id": acc.act_id, "campaign_id": camp_id,
                                    "budget_cents": budget, "page_id": page_id})
                db.commit()
                logger.info(f"[Keepalive] 账户 {acc.act_id} 建保活 {camp_id}/{ad_id}")
            except FbApiError as e:
                failed += 1; results.append(_ka_res(acc, "fail", e.category, e.friendly))
                logger.warning(f"[Keepalive] 账户 {acc.act_id} 失败: {e.friendly}")
                write_log(db, tenant_id=acc.tenant_id, trace_id=new_trace_id(),
                          actor_type="system", action_type="keepalive", source="keepalive",
                          result="fail", friendly_error=e.friendly[:200],
                          metadata={"act_id": acc.act_id})
                db.commit()
                _ka_rollback(fb, built)
            except Exception as e:
                failed += 1; results.append(_ka_res(acc, "fail", "error", str(e)[:120]))
                logger.warning(f"[Keepalive] 账户 {acc.act_id} 异常: {e}")
                _ka_rollback(fb, built)
        if created:
            logger.info(f"[Keepalive] 检查 {len(warming)} 个 warming 账户，建 {created} 条保活，跳过 {skipped}，失败 {failed}")
        return {"checked": len(warming), "created": created, "skipped": skipped, "failed": failed, "results": results}
    except Exception as e:
        logger.error(f"[Keepalive] 异常: {e}", exc_info=True)
        return {"error": str(e)}
    finally:
        db.close()
        release_run_lock(lock, 109)
