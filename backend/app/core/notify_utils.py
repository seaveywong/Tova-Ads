"""通知工具：emit_notification（角色订阅 + 用户级 TG，06 通知附录决策①③）。"""
from datetime import datetime, timezone, timedelta
import httpx
import logging
import threading
import json as _json
import time as _t
from sqlalchemy.orm import Session
from sqlalchemy import func as _f
from ..models.notify import Notification, TenantTgBinding, UserTgBinding
from ..models.auth import TenantMembership
from ..models.log import ActionLog
from .encryption import encrypt, decrypt
from html import escape as _esc

logger = logging.getLogger("toveads.notify")

# ── 告警风暴上限（dedup_recent 之上的第二道闸）──
# per (tenant_id, event_type) 当日已发 ≥ cap → 跳过（站内信+TG 都不发）+ 计数 + 日志 warning。
# cap 来自 system_settings.notify_storm_cap（默认 30，0=关闭封顶）；日界=UTC。
# 豁免清单：系统级 critical 事件不封顶——它们各自已有 per-source dedup，
# 封顶会掩盖"系统坏了/账户被封"这类最需要全量可见的信号。
NO_CAP_EVENTS = {
    "emergency_pause", "landing_health", "coverage_lost", "inspection_stalled",
    "token_expired", "token_invalid", "orphan_account", "sentinel_pause",
    "account_status_change",
    # budget_progress_98：预算几乎烧完的最后一道 critical——档位越高越不能吞
    "budget_progress_98",
    # rule_pause：止损动作通知（含"暂停失败"）宁可多发不可吞。guard_engine 对
    # 成功/失败/observe 共用同一 event_type（区别只在 body 文案），本层拿不到
    # result 做条件豁免，故整类豁免；该事件另有 60min/广告 dedup 防真 spam。
    "rule_pause",
    # tg_channel_down：通道故障告警自身（per-chat 6h dedup，最多 ~4 条/日/chat，不会真风暴）
    "tg_channel_down",
}
DEFAULT_STORM_CAP = 30

_storm_lock = threading.Lock()
# {(tenant_id, event_type, yyyymmdd): 被抑制条数}——进程内观测计数（跨 worker 各自一份；
# 封顶判定以 DB 行数为准，这里只供日志/排障看"压掉了多少"）
_storm_suppressed: dict = {}
# cap 值 TTL 缓存（避免每条通知都查 system_settings；改配置 60s 内生效）
_storm_cap_cache = {"v": DEFAULT_STORM_CAP, "ts": 0.0}
_STORM_CAP_TTL = 60.0


def _storm_cap_value(db: Session) -> int:
    """读 notify_storm_cap（system_settings，JSON 值），TTL 缓存 60s。"""
    now = _t.time()
    with _storm_lock:
        if _storm_cap_cache["ts"] and now - _storm_cap_cache["ts"] < _STORM_CAP_TTL:
            return _storm_cap_cache["v"]
    v = DEFAULT_STORM_CAP
    try:
        from ..models.system import SystemSetting
        row = db.query(SystemSetting).filter(SystemSetting.key == "notify_storm_cap").first()
        if row and row.value not in (None, ""):
            v = int(float(_json.loads(row.value)))
    except Exception:
        v = DEFAULT_STORM_CAP
    if v < 0:
        v = 0
    with _storm_lock:
        _storm_cap_cache["v"] = v
        _storm_cap_cache["ts"] = now
    return v


def reset_storm_cap_cache():
    """改配置后立即生效用（settings 写入方可调）。"""
    with _storm_lock:
        _storm_cap_cache["ts"] = 0.0


def storm_suppressed_counts() -> dict:
    """被抑制计数快照（排障/监控用）：{(tenant_id, event_type, date): n}。"""
    with _storm_lock:
        return dict(_storm_suppressed)


def _storm_allows(db: Session, tenant_id: int, event_type: str) -> bool:
    """当日该 (tenant_id, event_type) 已发条数 < cap → 允许发。
    cap=0 → 不封顶；豁免清单事件恒允许。同事务内已 flush 的通知行也计入（batch 内封顶即时生效）。"""
    cap = _storm_cap_value(db)
    if cap <= 0 or (event_type or "").lower() in NO_CAP_EVENTS:
        return True
    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    sent = db.query(_f.count(Notification.id)).filter(
        Notification.tenant_id == tenant_id,
        Notification.event_type == event_type,
        Notification.created_at >= day_start,
    ).scalar() or 0
    return int(sent) < cap


def _record_storm_suppression(tenant_id: int, event_type: str) -> int:
    """记一条压制（进程内计数）→ 返回该 (tenant, event_type) 当日累计被压制条数。
    调用方用返回值==1 判定"当日首条被压制"。"""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    with _storm_lock:
        # 防 dict 无界增长：超 4096 键时清掉非当日的
        if len(_storm_suppressed) > 4096:
            for k in [k for k in _storm_suppressed if k[2] != today]:
                _storm_suppressed.pop(k, None)
        key = (tenant_id, event_type, today)
        _storm_suppressed[key] = _storm_suppressed.get(key, 0) + 1
        n = _storm_suppressed[key]
    logger.warning(f"[Notify] 风暴上限：租户{tenant_id} 事件[{event_type}] 当日已满，"
                   f"累计抑制 {n} 条（notify_storm_cap 可调，0=不封顶）")
    return n


def _emit_storm_suppressed(db: Session, tenant_id: int, event_type: str) -> None:
    """压制可见性：发一条站内 warning——「今日已有 N 条告警被上限压制」。

    只在"当日首次压制"时被调用；再叠一层 per-tenant 24h dedup
    （action_logs.action_type=storm_suppressed_alert）防多事件类型连环 summary。
    N = 该租户当日累计被压制条数（_storm_suppressed 计数器，进程内口径）。
    只进站内不发 TG：TG 本身正在风暴里，别火上浇油。"""
    if dedup_recent(db, tenant_id, "storm_suppressed_alert", cooldown_min=24 * 60):
        return
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    with _storm_lock:
        n = sum(v for (tid, _et, d), v in _storm_suppressed.items()
                if tid == tenant_id and d == today)
    from .i18n import tenant_locale, notify_text
    _loc = tenant_locale(db, tenant_id)
    _title, _body = notify_text(_loc, "storm_suppressed", n=n, event_type=event_type)
    emit_notification(db, tenant_id=tenant_id, level="warning",
                      event_type="storm_suppressed", title=_title, body=_body,
                      target_type="notification", target_id=event_type,
                      send_tg=False)
    from .log_utils import write_log, new_trace_id
    write_log(db, tenant_id=tenant_id, trace_id=new_trace_id(), actor_type="system",
              target_type="notification", target_id=event_type,
              action_type="storm_suppressed_alert", source="notify",
              result="success",
              trigger_detail=f"event_type={event_type} suppressed_today={n}")
    db.commit()


def _roles_for_event(event_type: str) -> list[str]:
    """event_type → 订阅角色（决策①）。超管不看广告级（系统级另加超管平台 TG）。"""
    et = (event_type or "").lower()
    if et.startswith("ticket_"):
        return ["owner", "operator", "finance"]
    if et.startswith("budget_progress") or et in ("rule_pause", "sentinel_arm", "sentinel_disarm"):
        return ["owner", "operator"]  # 广告级
    if et in ("token_expired", "token_invalid", "token_expiring_soon",
              "inspection_stalled", "token_health_warn", "orphan_account"):
        # 系统级（+ 超管平台 TG，v2）。roles 只管站内信订阅；TG 路由见 _send_tg_by_role——
        # critical 级放宽为发该租户全部已绑 TG 用户（owner+operator 都能收到）。
        # TODO v2：inspection_stalled 由 guard_engine 发出时硬编码 tenant 1，
        # 多租户下应按各租户实际巡检状态发送——属 guard_engine 行为，本文件不动。
        return ["owner"]
    return ["owner", "operator"]  # 默认


def dedup_recent(db: Session, tenant_id: int, action_type: str,
                 target_id: str | None = None, cooldown_min: int = 60) -> bool:
    """近 cooldown_min 内是否已记过该告警（action_logs 去重）。True=已发过，应跳过。

    巡检类高频告警（权限不足/限流）必须先查它，否则每 5min × N 账户 = 海量 spam。
    """
    since = datetime.now(timezone.utc) - timedelta(minutes=cooldown_min)
    q = db.query(ActionLog).filter(
        ActionLog.tenant_id == tenant_id,
        ActionLog.action_type == action_type,
        ActionLog.created_at >= since,
    )
    if target_id:
        q = q.filter(ActionLog.target_id == str(target_id))
    return q.first() is not None


# ── 用户 TG 通知偏好（FBInsider ④通知白名单矩阵）──
# prefs = 绑定行上的 JSON 字符串：{"levels": {"warning": true, "info": true}}。
# 缺省(NULL)/空/解析失败 = 全 true——fail-open：偏好是降噪手段不是可靠性手段，宁可多推不可漏推。
# critical 恒推由调用处强制（不存 prefs、不出现在开关里）：重大资金/系统风险不能被用户关掉。
# 未来扩展位：levels 之外可加按 event_type / 账户过滤的键，本期只实现 levels。


def parse_tg_levels(prefs_json: str | None) -> dict:
    """prefs JSON → {"warning": bool, "info": bool}；任何缺失/异常 → 全 True（fail-open）。"""
    try:
        d = _json.loads(prefs_json) if prefs_json else {}
        lv = (d or {}).get("levels") or {}
        # 只有显式 false 才算关：缺键/None/非布尔值都按开（容错老数据/手改库）
        return {"warning": lv.get("warning") is not False,
                "info": lv.get("info") is not False}
    except Exception:
        return {"warning": True, "info": True}


def tg_prefs_allow(prefs_json: str | None, level: str) -> bool:
    """该用户是否允许此级别的通知推 TG（critical 调用方已豁免，不走这里）。"""
    return parse_tg_levels(prefs_json).get((level or "").lower(), True)


def emit_notification(
    db: Session,
    *,
    tenant_id: int,
    level: str,  # critical/warning/info
    event_type: str,
    title: str,
    body: str = "",
    user_id: int | None = None,
    trace_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    roles: list[str] | None = None,
    send_tg: bool = True,
    reply_markup=None,
    force_tg: bool = False,
    platform: str = "fb",  # fb/tt——告警按平台隔离展示（看板切平台时只看该平台告警）
    act_id: str | None = None,  # 预留账户维度过滤（guard_engine 集成接线用）：notifications
                                # 表暂无 act_id 列，本期只挂参不落库不迁移；确需账户级
                                # 关联时调用方直接传 target_type="account", target_id=act_id
) -> bool:
    """发通知：写站内信（带 roles 订阅）+ 按角色路由 TG 到用户级绑定。

    roles：决策①订阅矩阵（空则按 event_type 自动解析 _roles_for_event）。
    TG 路由：查租户内 role∈roles 的用户 → 各自 user_tg_binding 发；
    若租户无任何用户级绑定 → fallback tenant_tg_binding（不断现网）。
    TG 偏好：warning/info 受用户 prefs（user_tg_bindings.prefs）门控，critical 恒推
    （④白名单矩阵，只挡 TG 分发层——站内信不受影响，见 _send_tg_by_role）。
    force_tg：info 级也发 TG（默认 info 只进站内信；扩量通知等需要即时可见的用）。
    返回：True=已发；False=被每日风暴上限抑制（见 _storm_allows）。
    """
    roles = roles or _roles_for_event(event_type)
    # act_id 账户维度关联：映射进已有 target_type/target_id 列（零迁移）——
    # 前端 notiActId 从 body 正则提取是脆弱路径，落库后可直接按列过滤
    if act_id and not target_type and not target_id:
        target_type, target_id = "account", act_id
    if not _storm_allows(db, tenant_id, event_type):
        n = _record_storm_suppression(tenant_id, event_type)
        # 当日该事件首条被压制 → 补一条站内 summary（per-tenant 24h dedup），
        # 让"有告警被吞"可见。豁免 summary 自身防理论递归。
        if n == 1 and (event_type or "").lower() != "storm_suppressed":
            try:
                _emit_storm_suppressed(db, tenant_id, event_type)
            except Exception as e:
                logger.warning(f"[Notify] 压制 summary 发送失败: {e}")
        return False
    notif = Notification(
        tenant_id=tenant_id, user_id=user_id, level=level, event_type=event_type,
        title=title, body=body, trace_id=trace_id,
        target_type=target_type, target_id=target_id,
        roles=",".join(roles), platform=platform,
    )
    db.add(notif)
    db.flush()

    if send_tg and (force_tg or level in ("critical", "warning")):
        try:
            _send_tg_by_role(db, tenant_id, roles, level, title, body, reply_markup)
        except Exception as e:
            logger.warning(f"[TG] 发送失败（站内信已兜底）: {e}")
    return True


def _send_tg_by_role(db: Session, tenant_id: int, roles: list[str],
                     level: str, title: str, body: str, reply_markup=None):
    """按角色路由 TG：用户级绑定优先，无则 fallback 租户级。chat_id 去重防重复。
    critical 放宽（统一规则）：level=="critical" → 发给该租户所有已绑 TG 的用户
    （operator 也能收到 token_expired/orphan_account 等系统级 critical）；
    非 critical 维持 roles 分工（广告级 owner+operator / 系统级 owner）。
    通知偏好（④白名单矩阵）：warning/info 被用户显式关 → 跳过该用户的 TG；
    critical 恒推不受限。只挡本 TG 分发层——站内信在 emit_notification 已落库，不受影响。"""
    icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(level, "🔵")
    text = f"{icon} <b>{title}</b>\n{body}"[:1000]
    sent_keys: set[tuple] = set()  # (bot_token, chat_id) 去重

    # 用户级：critical → 全租户在职成员中已绑用户；其余 → role∈roles 的用户。
    # 在职判定 join TenantMembership（复审B P1）：remove_member 只删 membership 不删 TG 绑定，
    # 不过滤则离职成员的残留绑定会持续收到含账户名/金额的 critical 告警。
    if level == "critical":
        active_uids = [m.user_id for m in db.query(TenantMembership).filter(
            TenantMembership.tenant_id == tenant_id,
        ).all()]
        ubindings = db.query(UserTgBinding).filter(
            UserTgBinding.tenant_id == tenant_id,
            UserTgBinding.user_id.in_(active_uids),
        ).all() if active_uids else []
    else:
        user_ids = [m.user_id for m in db.query(TenantMembership).filter(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.role.in_(roles),
        ).all()] if roles else []
        ubindings = db.query(UserTgBinding).filter(
            UserTgBinding.tenant_id == tenant_id,
            UserTgBinding.user_id.in_(user_ids),
        ).all() if user_ids else []
    for b in ubindings:
        key = (b.bot_token_enc, b.chat_id)
        if key in sent_keys:
            continue
        # 通知偏好（④白名单矩阵）：critical 恒推；warning/info 被用户显式关 → 跳过
        # （prefs 是用户级语义，PUT 时写该用户全部绑定行，任一行读出一致）
        if level != "critical" and not tg_prefs_allow(b.prefs, level):
            continue
        _tg_send_tracked(db, tenant_id, decrypt(b.bot_token_enc), b.chat_id,
                         text, reply_markup)
        sent_keys.add(key)

    # fallback：租户内无任何用户级绑定 → 用租户级绑定（不断现网）
    if not ubindings:
        tb = db.query(TenantTgBinding).filter(
            TenantTgBinding.tenant_id == tenant_id,
        ).first()
        if tb:
            _tg_send_tracked(db, tenant_id, decrypt(tb.bot_token_enc), tb.chat_id,
                             text, reply_markup)


# ── TG 发送可靠性：重试 + 通道健康追踪 ──
TG_SEND_ATTEMPTS = 3           # 1 次首发 + 2 次重试
TG_RETRY_DELAYS = (1.0, 3.0)   # 重试退避（秒），仅对网络异常/5xx
TG_FAIL_ALERT_THRESHOLD = 3    # 同 chat 连续失败 N 次 → 通道故障告警
_tg_fail_lock = threading.Lock()
# {(bot_token, chat_id): 连续失败次数}（进程内计数，成功即清零；跨 worker 各自一份，
# 任一 worker 撞满阈值即告警——通道故障是全局性的，误报代价低于漏报。
# 键含 bot_token：同一 chat 绑在多租户（bot 各异）时，A 租户 bot 挂不该被 B 租户的成功清零（复审B P2））
_tg_fail_streak: dict[tuple, int] = {}


def _tg_send(bot_token: str, chat_id: str, text: str, reply_markup=None,
             track_key: tuple | None = None) -> bool:
    """实际发 TG（失败不阻断）。reply_markup: inline_keyboard（加白按钮等）。
    track_key: (bot_token, chat_id)——成功时清零该键的失败计数（None 则只按 chat_id 清，
    兼容手动测试等无 bot 维度调用点）。
    重试：网络异常（连接/超时）与 5xx 重试 2 次（退避 1s/3s）；
    4xx 是确定性失败（chat 不存在/token 被拒/被拉黑）重试无意义，直接放弃。
    返回 True=送达（HTTP 200）；False=最终失败。"""
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    last_err = "unknown"
    for attempt in range(TG_SEND_ATTEMPTS):
        if attempt:
            _t.sleep(TG_RETRY_DELAYS[min(attempt, len(TG_RETRY_DELAYS)) - 1])
        try:
            resp = httpx.post(url, json=payload, timeout=10)
        except httpx.HTTPError as e:  # 网络层（DNS/连接/超时）→ 大概率瞬时，可重试
            last_err = f"network: {e}"
            continue
        if resp.status_code == 200:
            if track_key is not None:
                with _tg_fail_lock:
                    _tg_fail_streak.pop(track_key, None)
            return True
        last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
        if resp.status_code >= 500:  # TG 侧临时故障 → 可重试
            continue
        break  # 4xx 确定性失败 → 不重试
    logger.warning(f"[TG] 发送失败 chat={chat_id}: {last_err}")
    return False


def _tg_send_tracked(db: Session, tenant_id: int, bot_token: str, chat_id: str,
                     text: str, reply_markup=None) -> bool:
    """_tg_send + 通道健康追踪：成功清零该 (bot, chat) 连续失败计数；
    失败 +1，撞满 TG_FAIL_ALERT_THRESHOLD → 站内 critical（tg_channel_down）。"""
    key = (bot_token, chat_id)
    if _tg_send(bot_token, chat_id, text, reply_markup, track_key=key):
        return True
    _emit_tg_channel_down_if_due(db, tenant_id, chat_id, fail_key=key)
    return False


def _emit_tg_channel_down_if_due(db: Session, tenant_id: int, chat_id: str,
                                 fail_key: tuple | None = None) -> None:
    """同 (bot, chat) 连续 TG_FAIL_ALERT_THRESHOLD 次发送失败 → 站内 critical
    「TG 通道连续发送失败」（emit 到 owner 角色，send_tg=False——通道本身在故障）。
    dedup 6h：action_logs(action_type=tg_channel_down_alert, target_id=chat_id)，
    窗口过后若仍失败会再告（持续故障持续可见）。"""
    _k = fail_key or chat_id
    with _tg_fail_lock:
        _tg_fail_streak[_k] = _tg_fail_streak.get(_k, 0) + 1
        n = _tg_fail_streak[_k]
    if n < TG_FAIL_ALERT_THRESHOLD:
        return
    if dedup_recent(db, tenant_id, "tg_channel_down_alert", target_id=chat_id,
                    cooldown_min=6 * 60):
        return
    from .i18n import tenant_locale, notify_text
    _loc = tenant_locale(db, tenant_id)
    _title, _body = notify_text(_loc, "tg_channel_down",
                                chat_id=_esc(chat_id), streak=n)
    emit_notification(db, tenant_id=tenant_id, level="critical",
                      event_type="tg_channel_down", title=_title, body=_body,
                      roles=["owner"], send_tg=False,
                      target_type="tg_chat", target_id=chat_id)
    from .log_utils import write_log, new_trace_id
    write_log(db, tenant_id=tenant_id, trace_id=new_trace_id(), actor_type="system",
              target_type="tg_chat", target_id=chat_id,
              action_type="tg_channel_down_alert", source="notify",
              result="fail", trigger_detail=f"chat_id={chat_id} streak={n}")
    db.commit()


def emit_token_expired_if_due(db: Session, tenant_id: int, alias: str = "",
                              cooldown_min: int = 60,
                              cred_id: int | str | None = None) -> bool:
    """FB token 失效时发 critical 告警（系统级，06_附录 §四）。

    dedup：近 cooldown_min 内已发过该凭证的 token_expired → 不重复（防 spam）。
    去重维度 = 凭证（cred_id 优先，调用方拿不到就退 alias）：多令牌租户同晚多 token
    全灭时每个凭证各告一条，不再被第一条压制。
    返回是否真发了。本次踩坑（token 死了全线 FB 挂却无告警）印证这是最高价值系统告警。
    """
    dedup_key = str(cred_id) if cred_id not in (None, "") else (alias or "unknown")
    since = datetime.now(timezone.utc) - timedelta(minutes=cooldown_min)
    recent = db.query(ActionLog).filter(
        ActionLog.tenant_id == tenant_id,
        ActionLog.action_type == "token_expired",
        ActionLog.target_id == dedup_key,
        ActionLog.created_at >= since,
    ).first()
    if recent:
        return False
    from .i18n import tenant_locale, notify_text
    trace_id = f"tok-{tenant_id}-{int(datetime.now(timezone.utc).timestamp())}"
    _loc = tenant_locale(db, tenant_id)
    _title, _body = notify_text(_loc, "token_expired",
                                alias=_esc(alias or '未命名'))
    emit_notification(db, tenant_id=tenant_id, level="critical",
                      event_type="token_expired", trace_id=trace_id,
                      title=_title, body=_body, send_tg=True,
                      target_type="fb_credential", target_id=dedup_key)
    # action_logs 记录（dedup 用 + 超管系统日志）—— target_id 带凭证标识（dedup 按凭证分键）
    from .log_utils import write_log, new_trace_id
    write_log(db, tenant_id=tenant_id, trace_id=trace_id, actor_type="system",
              target_type="fb_credential", target_id=dedup_key,
              action_type="token_expired",
              source="rule_engine", result="fail",
              trigger_detail=f"alias={alias} cred={dedup_key}")
    db.commit()
    return True


def emit_orphan_account_alerts(db: Session, tenant_id: int,
                                orphan_accounts: list[dict],
                                cooldown_hours: int = 24) -> int:
    """孤儿账户（没有任何可用令牌覆盖）发 critical 告警 + TG。

    每账户按 action_logs(target_id=act_id) 做 cooldown 去重（默认 24h，每天最多一条）。
    orphan_accounts: [{act_id, name}, ...]。返回实际发送条数。
    """
    if not orphan_accounts:
        return 0
    from .log_utils import write_log, new_trace_id
    since = datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)
    sent = 0
    for acc in orphan_accounts:
        act_id = acc.get("act_id")
        if not act_id:
            continue
        recent = db.query(ActionLog).filter(
            ActionLog.tenant_id == tenant_id,
            ActionLog.action_type == "orphan_account_alert",
            ActionLog.target_id == act_id,
            ActionLog.created_at >= since,
        ).first()
        if recent:
            continue
        trace_id = new_trace_id()
        from .i18n import tenant_locale, notify_text
        _loc = tenant_locale(db, tenant_id)
        _title, _body = notify_text(_loc, "orphan_account",
                                    name=_esc(acc.get('name') or act_id), act_id=act_id)
        emit_notification(db, tenant_id=tenant_id, level="critical",
                          event_type="orphan_account", trace_id=trace_id,
                          title=_title, body=_body,
                          target_type="account", target_id=act_id, send_tg=True)
        write_log(db, tenant_id=tenant_id, trace_id=trace_id, actor_type="system",
                  target_type="account", target_id=act_id,
                  action_type="orphan_account_alert", source="watchdog",
                  result="fail", trigger_detail=f"act_id={act_id}")
        sent += 1
    if sent:
        db.commit()
    return sent


def emit_low_balance_alert_if_due(db: Session, tenant_id: int, *, act_id: str,
                                  name: str, avail_usd: float, threshold_usd: float,
                                  basis: str = "spend_cap", cooldown_hours: int = 6) -> bool:
    """账户可用额度低于阈值 → warning 告警 + TG（余额告警打通通知模块）。

    口径由调用方算好传入（与看板一致）：
    - basis="spend_cap"：可用 = spend_cap − amount_spent（USD）
    - basis="prepaid_balance"：无花费上限的预付费账户退回 FB balance（>0 才判；
      后付费账户 balance 是账单/欠款，不作告警依据）
    dedup：action_logs(action_type=low_balance_alert, target_id=act_id) 近 cooldown_hours（默认 6h）。
    返回是否真发了。
    """
    if avail_usd is None or threshold_usd is None or float(threshold_usd) <= 0:
        return False
    if dedup_recent(db, tenant_id, "low_balance_alert", target_id=act_id,
                    cooldown_min=cooldown_hours * 60):
        return False
    from .log_utils import write_log, new_trace_id
    trace_id = new_trace_id()
    from .i18n import tenant_locale, notify_text
    _loc = tenant_locale(db, tenant_id)
    _key = "low_balance_prepaid" if basis == "prepaid_balance" else "low_balance"
    _title, _body = notify_text(_loc, _key,
                                name=_esc(name or act_id), act_id=act_id,
                                avail=float(avail_usd), threshold=float(threshold_usd))
    emit_notification(db, tenant_id=tenant_id, level="warning",
                      event_type="low_balance", trace_id=trace_id,
                      title=_title, body=_body,
                      target_type="account", target_id=act_id, send_tg=True)
    write_log(db, tenant_id=tenant_id, trace_id=trace_id, actor_type="system",
              target_type="account", target_id=act_id,
              action_type="low_balance_alert", source="account_sync",
              result="alerted",
              trigger_detail=f"avail_usd={float(avail_usd):.2f} threshold={float(threshold_usd):.0f} basis={basis}")
    db.commit()
    return True
