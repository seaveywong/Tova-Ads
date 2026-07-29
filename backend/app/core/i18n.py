"""后端国际化：通知消息按租户 owner 的 locale 渲染（异步生成、站内信+TG）。"""
from sqlalchemy.orm import Session


def tenant_locale(db: Session, tenant_id: int) -> str:
    """租户 owner 的 locale（通知用其语言渲染）。默认 'zh'。"""
    try:
        from ..models.auth import User, TenantMembership
        m = db.query(TenantMembership).filter(
            TenantMembership.tenant_id == tenant_id, TenantMembership.role == "owner"
        ).first()
        if m:
            u = db.query(User).filter(User.id == m.user_id).first()
            if u and getattr(u, "locale", None) in ("zh", "en"):
                return u.locale
    except Exception:
        pass
    return "zh"


# 通知消息译表：code -> {title: {zh,en}, body: {zh,en}}。body 用 {param} 占位。
# HTML 标签（<b> / <code>）与 emoji 必须保留——TG parse_mode=HTML。
NOTIFY = {
    # ── 令牌级 ──
    "token_expired": {
        "title": {"zh": "令牌失效", "en": "Token Expired"},
        "body": {
            "zh": "令牌：<b>{alias}</b>\n状态：已失效，所有 Facebook 操作暂停\n处理：请在 Facebook 授权页重新绑定令牌",
            "en": "Token: <b>{alias}</b>\nStatus: expired, all Facebook operations suspended\nAction: please re-bind the token on the Facebook authorization page",
        },
    },
    "token_invalid": {
        "title": {"zh": "🔴 FB Token 无效", "en": "🔴 FB Token Invalid"},
        "body": {
            "zh": "Token[{alias}] debug_token 显示无效，请重新绑定。",
            "en": "Token[{alias}] debug_token reports invalid, please re-bind.",
        },
    },
    "token_expiring_soon": {
        "title": {"zh": "🟡 FB Token 即将过期", "en": "🟡 FB Token Expiring Soon"},
        "body": {
            "zh": "Token[{alias}] 剩余 {days} 天，请提前续期。",
            "en": "Token[{alias}] has {days} days left, please renew in advance.",
        },
    },
    "token_rate_limited": {
        "title": {"zh": "令牌限流 · {alias}", "en": "Token Rate-Limited · {alias}"},
        "body": {
            "zh": "令牌：<b>{alias}</b>\n读取被限流，30 分钟后自动恢复，或换其他令牌\n影响账户：{affected}",
            "en": "Token: <b>{alias}</b>\nRead requests throttled, auto-recovers in 30 minutes, or switch to another token\nAffected accounts: {affected}",
        },
    },
    # ── 账户级 ──
    "orphan_account": {
        "title": {"zh": "账户所有令牌失效", "en": "Account Has No Valid Token"},
        "body": {
            "zh": "账户：<b>{name}</b>（act_{act_id}）\n状态：没有任何可用令牌覆盖，无法读取或操作\n处理：请重新绑定令牌，或载入一个能管理该账户的令牌",
            "en": "Account: <b>{name}</b> (act_{act_id})\nStatus: no valid token covers it, cannot read or operate\nAction: please re-bind a token, or load a token that manages this account",
        },
    },
    "account_permission_error": {
        "title": {"zh": "权限不足 · {name}", "en": "Permission Denied · {name}"},
        "body": {
            "zh": "账户：{name}（<code>{act_id}</code>）\n令牌：{alias}\n读取失败：<b>{friendly}</b>\n该令牌可能缺少广告读取权限，请重新授权。",
            "en": "Account: {name} (<code>{act_id}</code>)\nToken: {alias}\nRead failed: <b>{friendly}</b>\nThe token may lack ad-read permission, please re-authorize.",
        },
    },
    "inspection_stalled": {
        "title": {"zh": "🚨 巡检引擎停滞", "en": "🚨 Inspection Engine Stalled"},
        "body": {
            "zh": "超过 {minutes} 分钟无成功巡检心跳。\n守护引擎可能挂了——止损/预算告警失效，请立即排查 toveads 服务。",
            "en": "No successful inspection heartbeat for over {minutes} minutes.\nThe guard engine may be down — stop-loss/budget alerts are inactive, please investigate the toveads service immediately.",
        },
    },
    # ── 止损 / 哨兵 ──
    "rule_pause": {
        "title": {"zh": "止损【{category}】· {name}", "en": "Stop-Loss [{category}] · {name}"},
        "body": {
            "zh": "账户：{name}（<code>{act_id}</code>）\n广告：{ad_name}（<code>{ad_id}</code>）\n广告组：<code>{adset_id}</code>\n系列：<code>{campaign_id}</code>\n规则：{rule_name}\n触发：<b>{detail}</b>\n消耗：<b>{spend}</b> ｜ 转化：<b>{conv}</b>\nKPI：{kpi_label}（{source_label}）",
            "en": "Account: {name} (<code>{act_id}</code>)\nAd: {ad_name} (<code>{ad_id}</code>)\nAd set: <code>{adset_id}</code>\nCampaign: <code>{campaign_id}</code>\nRule: {rule_name}\nTrigger: <b>{detail}</b>\nSpend: <b>{spend}</b> | Conversions: <b>{conv}</b>\nKPI: {kpi_label} ({source_label})",
        },
    },
    "sentinel_pause": {
        "title": {"zh": "哨兵暂停系列", "en": "Sentinel Paused Campaign"},
        "body": {
            "zh": "账户：{name}（{act_id}）\n系列：{camp_name}（{camp_id}）\n哨兵已 arm，ACTIVE 系列直接停。",
            "en": "Account: {name} ({act_id})\nCampaign: {camp_name} ({camp_id})\nSentinel armed, ACTIVE campaigns paused directly.",
        },
    },
    "coverage_lost": {
        "title": {"zh": "巡检覆盖丢失：{n} 条有消耗广告未被评估", "en": "Inspection Coverage Lost: {n} ads with spend not evaluated"},
        "body": {
            "zh": "本轮有 {n} 条今日有消耗的广告被排除在巡检外（active_ids 拉取失败/ads_cache 为空），止损规则对它们失效，请检查令牌/同步。",
            "en": "This round {n} ads with today's spend were excluded from inspection (active_ids fetch failed / ads_cache empty), stop-loss rules are inactive for them, please check token/sync.",
        },
    },
    # ── 预算进度 ──
    "budget_progress": {
        "title": {"zh": "预算进度 {progress:.0f}%（{tier}% 档）", "en": "Budget Progress {progress:.0f}% ({tier}% tier)"},
        "body": {
            "zh": "广告组[{adset_name}]\n账户：{acc_name}\n日预算 {budget:.0f} {currency} / 已消耗 {spend:.0f} ({progress:.0f}%)\n剩余 {remaining:.0f} {currency}",
            "en": "Ad set [{adset_name}]\nAccount: {acc_name}\nDaily budget {budget:.0f} {currency} / spent {spend:.0f} ({progress:.0f}%)\nRemaining {remaining:.0f} {currency}",
        },
    },
    # ── 子码清理 ──
    "subcode_cleanup": {
        "title": {"zh": "闲置子码已清理", "en": "Idle Subcodes Cleaned"},
        "body": {
            "zh": "自动归档/硬删 {n} 个闲置子码（14天未用→归档，30天→硬删）。回收站可恢复。",
            "en": "Auto-archived/hard-deleted {n} idle subcodes (unused 14 days → archived, 30 days → hard-deleted). Restorable from recycle bin.",
        },
    },
}


def notify_text(locale: str, code: str, **params) -> tuple[str, str]:
    """返回 (title, body)，按 locale 渲染；body 的 {param} 用 params 填。未知 code 回退中文/原样。"""
    entry = NOTIFY.get(code)
    if not entry:
        return (code, code)
    lang = locale if locale in ("zh", "en") else "zh"
    title = entry["title"].get(lang) or entry["title"]["zh"]
    body = entry["body"].get(lang) or entry["body"]["zh"]
    try:
        body = body.format(**params) if params else body
        title = title.format(**params) if params else title
    except Exception:
        pass
    return (title, body)
