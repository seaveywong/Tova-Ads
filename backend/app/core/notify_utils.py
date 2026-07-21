"""通知工具：emit_notification（角色订阅 + 用户级 TG，06 通知附录决策①③）。"""
from datetime import datetime, timezone, timedelta
import httpx
import logging
from sqlalchemy.orm import Session
from ..models.notify import Notification, TenantTgBinding, UserTgBinding
from ..models.auth import TenantMembership
from ..models.log import ActionLog
from .encryption import encrypt, decrypt
from html import escape as _esc

logger = logging.getLogger("toveads.notify")


def _roles_for_event(event_type: str) -> list[str]:
    """event_type → 订阅角色（决策①）。超管不看广告级（系统级另加超管平台 TG）。"""
    et = (event_type or "").lower()
    if et.startswith("ticket_"):
        return ["owner", "operator", "finance"]
    if et.startswith("budget_progress") or et in ("rule_pause", "sentinel_arm", "sentinel_disarm"):
        return ["owner", "operator"]  # 广告级
    if et in ("token_expired", "token_invalid", "token_expiring_soon",
              "inspection_stalled", "token_health_warn", "orphan_account"):
        return ["owner"]  # 系统级（+ 超管平台 TG，v2）
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
):
    """发通知：写站内信（带 roles 订阅）+ 按角色路由 TG 到用户级绑定。

    roles：决策①订阅矩阵（空则按 event_type 自动解析 _roles_for_event）。
    TG 路由：查租户内 role∈roles 的用户 → 各自 user_tg_binding 发；
    若租户无任何用户级绑定 → fallback tenant_tg_binding（不断现网）。
    """
    roles = roles or _roles_for_event(event_type)
    notif = Notification(
        tenant_id=tenant_id, user_id=user_id, level=level, event_type=event_type,
        title=title, body=body, trace_id=trace_id,
        target_type=target_type, target_id=target_id,
        roles=",".join(roles),
    )
    db.add(notif)
    db.flush()

    if send_tg and level in ("critical", "warning"):
        try:
            _send_tg_by_role(db, tenant_id, roles, level, title, body, reply_markup)
        except Exception as e:
            logger.warning(f"[TG] 发送失败（站内信已兜底）: {e}")


def _send_tg_by_role(db: Session, tenant_id: int, roles: list[str],
                     level: str, title: str, body: str, reply_markup=None):
    """按角色路由 TG：用户级绑定优先，无则 fallback 租户级。chat_id 去重防重复。"""
    icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(level, "🔵")
    text = f"{icon} <b>{title}</b>\n{body}"[:1000]
    sent_keys: set[tuple] = set()  # (bot_token, chat_id) 去重

    # 用户级：role∈roles 的用户的绑定
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
        _tg_send(decrypt(b.bot_token_enc), b.chat_id, text, reply_markup)
        sent_keys.add(key)

    # fallback：租户内无任何用户级绑定 → 用租户级绑定（不断现网）
    if not ubindings:
        tb = db.query(TenantTgBinding).filter(
            TenantTgBinding.tenant_id == tenant_id,
        ).first()
        if tb:
            _tg_send(decrypt(tb.bot_token_enc), tb.chat_id, text, reply_markup)


def _tg_send(bot_token: str, chat_id: str, text: str, reply_markup=None):
    """实际发 TG（失败不阻断）。reply_markup: inline_keyboard（加白按钮等）。"""
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    resp = httpx.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json=payload,
        timeout=10,
    )
    if resp.status_code != 200:
        logger.warning(f"[TG] API 返 {resp.status_code}: {resp.text[:200]}")


def emit_token_expired_if_due(db: Session, tenant_id: int, alias: str = "",
                              cooldown_min: int = 60) -> bool:
    """FB token 失效时发 critical 告警（系统级，06_附录 §四）。

    dedup：近 cooldown_min 内已发过 token_expired → 不重复（防 spam）。
    返回是否真发了。本次踩坑（token 死了全线 FB 挂却无告警）印证这是最高价值系统告警。
    """
    since = datetime.now(timezone.utc) - timedelta(minutes=cooldown_min)
    recent = db.query(ActionLog).filter(
        ActionLog.tenant_id == tenant_id,
        ActionLog.action_type == "token_expired",
        ActionLog.created_at >= since,
    ).first()
    if recent:
        return False
    trace_id = f"tok-{tenant_id}-{int(datetime.now(timezone.utc).timestamp())}"
    title = "令牌失效"
    body = (f"令牌：<b>{_esc(alias or '未命名')}</b>\n"
            f"状态：已失效，所有 Facebook 操作暂停\n"
            f"处理：请在 Facebook 授权页重新绑定令牌")
    emit_notification(db, tenant_id=tenant_id, level="critical",
                      event_type="token_expired", trace_id=trace_id,
                      title=title, body=body, send_tg=True)
    # action_logs 记录（dedup 用 + 超管系统日志）
    from .log_utils import write_log, new_trace_id
    write_log(db, tenant_id=tenant_id, trace_id=trace_id, actor_type="system",
              target_type="fb_credential", action_type="token_expired",
              source="rule_engine", result="fail",
              trigger_detail=f"alias={alias}")
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
        title = "账户所有令牌失效"
        body = (f"账户：<b>{_esc(acc.get('name') or act_id)}</b>（act_{act_id}）\n"
                f"状态：没有任何可用令牌覆盖，无法读取或操作\n"
                f"处理：请重新绑定令牌，或载入一个能管理该账户的令牌")
        emit_notification(db, tenant_id=tenant_id, level="critical",
                          event_type="orphan_account", trace_id=trace_id,
                          title=title, body=body,
                          target_type="account", target_id=act_id, send_tg=True)
        write_log(db, tenant_id=tenant_id, trace_id=trace_id, actor_type="system",
                  target_type="account", target_id=act_id,
                  action_type="orphan_account_alert", source="watchdog",
                  result="fail", trigger_detail=f"act_id={act_id}")
        sent += 1
    if sent:
        db.commit()
    return sent
