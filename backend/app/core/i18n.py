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
    "low_balance": {
        "title": {"zh": "账户可用额度低 · {name}", "en": "Low Available Balance · {name}"},
        "body": {
            "zh": "账户：<b>{name}</b>（act_{act_id}）\n可用额度：<b>${avail:.2f}</b>（阈值 ${threshold:.0f}）\n口径：花费上限 − 已消耗\n处理：及时充值或上调花费上限，避免广告停投",
            "en": "Account: <b>{name}</b> (act_{act_id})\nAvailable: <b>${avail:.2f}</b> (threshold ${threshold:.0f})\nBasis: spend cap - spent\nAction: top up or raise the spend cap to keep ads delivering",
        },
    },
    "low_balance_prepaid": {
        "title": {"zh": "账户余额低 · {name}", "en": "Low Account Balance · {name}"},
        "body": {
            "zh": "账户：<b>{name}</b>（act_{act_id}）\n预付费余额：<b>${avail:.2f}</b>（阈值 ${threshold:.0f}）\n处理：及时充值，余额耗尽广告将停投",
            "en": "Account: <b>{name}</b> (act_{act_id})\nPrepaid balance: <b>${avail:.2f}</b> (threshold ${threshold:.0f})\nAction: top up soon, ads stop once the balance runs out",
        },
    },
    "sync_stalled": {
        "title": {"zh": "数据同步已停 · 无可用令牌", "en": "Data Sync Stalled · No Usable Token"},
        "body": {
            "zh": "{n} 个纳管账户无可用广告令牌，报表/广告缓存已停止更新。\n⚠️ 止损已失效：巡检读不到广告数据，止损规则/哨兵不会执行，广告将持续消耗。\n请到「令牌管理」重新授权，恢复后数据自动补齐。",
            "en": "{n} managed ad accounts have no usable ad token; reports and ad cache have stopped updating.\n WARNING: stop-loss is inactive — the inspector cannot read ad data, so stop-loss rules/sentinel will not run and ads will keep spending.\nPlease re-authorize in Token Management. Data will resume automatically afterwards.",
        },
    },
    "account_permission_error": {
        "title": {"zh": "权限不足 · {name}", "en": "Permission Denied · {name}"},
        "body": {
            "zh": "账户：{name}（<code>{act_id}</code>）\n令牌：{alias}\n读取失败：<b>{friendly}</b>\n该令牌可能缺少广告读取权限，请重新授权。",
            "en": "Account: {name} (<code>{act_id}</code>)\nToken: {alias}\nRead failed: <b>{friendly}</b>\nThe token may lack ad-read permission, please re-authorize.",
        },
    },
    "unsupported_currency": {
        "title": {"zh": "🔴 未知币种，金额类止损已跳过", "en": "🔴 Unknown Currency, Money Rules Skipped"},
        "body": {
            "zh": "账户：{name}（<code>{act_id}</code>）\n币种：<b>{currency}</b> 在汇率表与兜底字典中均无汇率。\n影响：金额类止损/扩量规则已对该账户跳过（避免按错误汇率误停/误扩），非金额规则照常。\n处理：请为该币种补充汇率后再恢复全额守护。",
            "en": "Account: {name} (<code>{act_id}</code>)\nCurrency <b>{currency}</b> has no rate in the FX table or the fallback dictionary.\nImpact: money-based stop-loss/scale rules are skipped for this account (to avoid wrong-rate pauses/scaling); non-money rules still run.\nAction: add a rate for this currency to restore full protection.",
        },
    },
    "inspection_stalled": {
        "title": {"zh": "🚨 巡检引擎停滞", "en": "🚨 Inspection Engine Stalled"},
        "body": {
            "zh": "超过 {minutes} 分钟无成功巡检心跳。\n守护引擎可能挂了——止损/预算告警失效，请立即排查 toveads 服务。",
            "en": "No successful inspection heartbeat for over {minutes} minutes.\nThe guard engine may be down — stop-loss/budget alerts are inactive, please investigate the toveads service immediately.",
        },
    },
    # 单账户巡检停滞（watchdog per-account 检测：全局心跳正常≠每个账户都被巡到）
    "inspection_stale_accounts": {
        "title": {"zh": "🔴 {n} 个账户超过30分钟未被巡检", "en": "🔴 {n} Accounts Not Inspected for 30+ Minutes"},
        "body": {
            "zh": "以下账户超过 30 分钟无成功巡检记录（无令牌/insights 拉取失败/引擎异常），止损对其可能失效。名单：",
            "en": "The accounts below have no successful inspection for over 30 minutes (no token / insights fetch failure / engine error); stop-loss may be inactive for them. List:",
        },
    },
    # 哨兵权限退避（写令牌 permissions=永久错误：BM 角色被收/账户被收回，重试必然再失败）
    "sentinel_perm_denied": {
        "title": {"zh": "🔴 账户写权限丢失，哨兵已暂停防护 · {name}", "en": "🔴 Write Permission Lost, Sentinel Paused · {name}"},
        "body": {
            "zh": "账户：{name}（<code>{act_id}</code>）\n停广告被 FB 拒绝（权限不足）——通常为 BM 广告账户角色被降/收回，或账户已被供应商停用回收。\n哨兵已暂停该账户的停广告尝试 24 小时（避免无效重试刷屏）；权限恢复后下一轮自动恢复防护。\n处理：若账户已不用 → 取消纳管/解除哨兵；若还要用 → 在 BM 里恢复该用户的广告投放权限。",
            "en": "Account: {name} (<code>{act_id}</code>)\nPausing ads was rejected by Facebook (insufficient permission) — usually the BM ad-account role was revoked/downgraded, or the account was reclaimed by the vendor.\nThe sentinel has paused stop attempts for this account for 24 hours (no futile retries); protection resumes automatically once permission is restored.\nActions: if the account is no longer used, unmanage it / disarm the sentinel; otherwise restore the user's advertiser access in Business Manager.",
        },
    },
    # KPI/评估口径异常（静默降级必须发声：resolver 异常→conv=0 有误杀面；objectives 缺口→口径漂移）
    "kpi_resolve_error": {
        "title": {"zh": "🟡 转化数据口径异常 {n} 处（相关广告已跳过评估防误杀）", "en": "🟡 Conversion-Data Irregularities: {n} (affected ads skipped to avoid false kills)"},
        "body": {
            "zh": "本轮巡检发现 {n} 处 KPI 解析/评估异常（转化口径未知）。\n相关广告本轮已跳过规则评估（宁纵勿枉，防误杀有转化的广告）、快照照写。\n常见原因：KPI 映射配置损坏、campaign objective 拉取失败。\n排查：设置 → 转化映射检查该租户配置；日志中心过滤 kpi_resolve_error 看明细。",
            "en": "This inspection round found {n} KPI parsing/evaluation irregularities (conversion basis unknown).\nRule evaluation was skipped for affected ads (better lenient than wrongly paused); snapshots still written.\nCommon causes: broken KPI mapping config, campaign-objective fetch failures.\nTroubleshoot: Settings → Conversion Mapping; filter kpi_resolve_error in the Log Center for details.",
        },
    },
    # ── 止损 / 哨兵 ──
    "rule_pause": {
        "title": {"zh": "止损【{category}】· {name}", "en": "Stop-Loss [{category}] · {name}"},
        "body": {
            "zh": "账户：{name}（<code>{act_id}</code>）\n广告：{ad_name}（<code>{ad_id}</code>）\n广告组：<code>{adset_id}</code>\n系列：<code>{campaign_id}</code>\n规则：{rule_name}\n触发：<b>{detail}</b>\n动作：<b>{action}</b>\n消耗：<b>{spend}</b> ｜ 转化：<b>{conv}</b>\nKPI：{kpi_label}（{source_label}）",
            "en": "Account: {name} (<code>{act_id}</code>)\nAd: {ad_name} (<code>{ad_id}</code>)\nAd set: <code>{adset_id}</code>\nCampaign: <code>{campaign_id}</code>\nRule: {rule_name}\nTrigger: <b>{detail}</b>\nAction: <b>{action}</b>\nSpend: <b>{spend}</b> | Conversions: <b>{conv}</b>\nKPI: {kpi_label} ({source_label})",
        },
    },
    "spend_spike": {
        "title": {"zh": "花费骤变：{name}", "en": "Spend Spike: {name}"},
        "body": {
            "zh": "账户：{name}（{act_id}）\n今日已花费：<b>{today}</b>\n近7天日均：{avg}（阈值 = max(3×日均, $50)）\n今日消耗已达日均 {ratio} 倍——请检查是否爆量/预算设置错误。",
            "en": "Account: {name} ({act_id})\nToday spend: <b>{today}</b>\n7-day daily avg: {avg} (threshold = max(3x avg, $50))\nToday is {ratio}x of average — check for runaway spend / budget misconfig.",
        },
    },
    "unmanage_active_ads": {
        "title": {"zh": "取消纳管时有广告在投 · {name}", "en": "Ads Still Active on Unmanage · {name}"},
        "body": {
            "zh": "账户：<b>{name}</b>（act_{act_id}）\n取消纳管时有 <b>{n}</b> 条广告仍在投放。\n注意：广告不会自动停止，止损/哨兵已不再覆盖该账户。\n如需停投，请到平台广告管理后台手动暂停。",
            "en": "Account: <b>{name}</b> (act_{act_id})\n<b>{n}</b> ads were still delivering when the account was unmanaged.\nNote: ads will NOT stop automatically; stop-loss/sentinel no longer cover this account.\nPause them manually in the Ads Manager if needed.",
        },
    },
    "tg_channel_down": {
        "title": {"zh": "TG 通道连续发送失败", "en": "TG Channel Delivery Failure"},
        "body": {
            "zh": "Telegram 通道连续 {streak} 次发送失败（chat {chat_id}），告警可能未送达，请检查 bot/网络。\n处理：确认 bot token 有效、服务器能访问 api.telegram.org、用户未停用 bot",
            "en": "Telegram delivery has failed {streak} times in a row (chat {chat_id}); alerts may not have been delivered. Check the bot/network.\nAction: verify the bot token, that the server can reach api.telegram.org, and that the user has not blocked the bot",
        },
    },
    "storm_suppressed": {
        "title": {"zh": "告警被上限压制", "en": "Alerts Suppressed by Daily Cap"},
        "body": {
            "zh": "今日已有 {n} 条告警被风暴上限压制（最近被压事件：{event_type}）。若需全量可见，可在系统设置调大 notify_storm_cap 或设 0（不封顶）",
            "en": "{n} alerts were suppressed by the daily storm cap today (latest suppressed: {event_type}). Raise notify_storm_cap or set it to 0 (no cap) in system settings if full visibility is needed",
        },
    },
    "emergency_done": {
        "title": {"zh": "全局紧急暂停完成", "en": "Global Emergency Pause Done"},
        "body": {
            "zh": "覆盖 {total} 个账户\n已停 <b>{camps}</b> 个系列（含其下 {ads} 条广告）\n【终验】全量扫描后仍有 <b>{final_active}</b> 个系列在投放\n核验失败：{failed}\n{errs}",
            "en": "Covered {total} accounts\nPaused <b>{camps}</b> campaigns ({ads} ads under them)\n[FINAL AUDIT] {final_active} campaigns STILL ACTIVE after full scan\nVerify failed: {failed}\n{errs}",
        },
    },
    "sentinel_pause_batch": {
        "title": {"zh": "哨兵暂停 {n} 个系列", "en": "Sentinel Paused {n} Campaigns"},
        "body": {
            "zh": "{detail}\n\n哨兵已 arm，ACTIVE 系列直接停。明细见守护页「暂停记录」。",
            "en": "{detail}\n\nSentinel armed, ACTIVE campaigns paused directly. Details in Guard → Pause Log.",
        },
    },
    "sentinel_pause": {
        "title": {"zh": "哨兵暂停系列", "en": "Sentinel Paused Campaign"},
        "body": {
            "zh": "账户：{name}（{act_id}）\n系列：{camp_name}（{camp_id}）\n哨兵已 arm，ACTIVE 系列直接停。",
            "en": "Account: {name} ({act_id})\nCampaign: {camp_name} ({camp_id})\nSentinel armed, ACTIVE campaigns paused directly.",
        },
    },
    # 哨兵 TT 分支（ad 级 DISABLE；campaign 级批量形状 sandbox 验证前先逐条停广告）
    "sentinel_pause_ad": {
        "title": {"zh": "哨兵暂停广告", "en": "Sentinel Paused Ad"},
        "body": {
            "zh": "账户：{name}（TikTok {act_id}）\n广告：{ad_name}（{ad_id}）\n哨兵已 arm，投放中广告直接停。",
            "en": "Account: {name} (TikTok {act_id})\nAd: {ad_name} ({ad_id})\nSentinel armed, active ads paused directly.",
        },
    },
    # 哨兵执行失败（无令牌/拉取失败/停失败——曾全部静默；哨兵会每轮重试，此处告知人工介入）
    "sentinel_failure": {
        "title": {"zh": "🔴 哨兵未能停止 {n} 项", "en": "🔴 Sentinel Failed to Stop {n} Item(s)"},
        "body": {
            "zh": "哨兵已 arm，但以下目标本轮未能停止（哨兵会持续重试，请尽快人工处理）：\n{detail}",
            "en": "Sentinel is armed, but the following could NOT be stopped this round (sentinel keeps retrying; please intervene):\n{detail}",
        },
    },
    "rule_scale": {
        "title": {"zh": "扩量【{category}】· {name}", "en": "Scale-Up [{category}] · {name}"},
        "body": {
            "zh": "账户：{name}（<code>{act_id}</code>）\n广告：{ad_name}（<code>{ad_id}</code>）\n广告组：<code>{adset_id}</code>\n规则：{rule_name}\n触发：<b>{detail}</b>\n动作：<b>{action}</b>\n预算：<b>{budget}</b>",
            "en": "Account: {name} (<code>{act_id}</code>)\nAd: {ad_name} (<code>{ad_id}</code>)\nAd set: <code>{adset_id}</code>\nRule: {rule_name}\nTrigger: <b>{detail}</b>\nAction: <b>{action}</b>\nBudget: <b>{budget}</b>",
        },
    },
    "coverage_lost": {
        "title": {"zh": "巡检覆盖丢失：{n} 条有消耗广告未被评估", "en": "Inspection Coverage Lost: {n} ads with spend not evaluated"},
        "body": {
            "zh": "本轮有 {n} 条今日有消耗的广告被排除在巡检外（active_ids 拉取失败/ads_cache 为空），止损规则对它们失效，请检查令牌/同步。",
            "en": "This round {n} ads with today's spend were excluded from inspection (active_ids fetch failed / ads_cache empty), stop-loss rules are inactive for them, please check token/sync.",
        },
    },
    # 每轮整账户跳过聚合（无令牌/insights 失败的账户——止损对其失效但曾只留服务日志）
    "inspection_skipped": {
        "title": {"zh": "🟡 本轮 {n} 个账户未被巡检", "en": "🟡 {n} Accounts Skipped This Round"},
        "body": {
            "zh": "本轮巡检跳过了以下账户（无令牌/insights 拉取失败），止损对其失效，请检查令牌与授权。名单：",
            "en": "This inspection round skipped the following accounts (no token / insights fetch failure); stop-loss is inactive for them. Please check tokens and authorization. List:",
        },
    },
    # live /ads 拉取连续降级（连续多轮 cache 兜底——巡检覆盖降级为 15min 缓存口径）
    "live_fetch_degraded": {
        "title": {"zh": "🟡 live 广告拉取连续 {streak} 轮降级", "en": "🟡 Live Ad Fetch Degraded for {streak} Rounds"},
        "body": {
            "zh": "连续 {streak} 轮 live /ads 拉取失败或为空（本轮 {n} 个账户用 ads_cache 兜底），巡检覆盖降级为 15 分钟缓存口径，请检查令牌/限流。",
            "en": "Live /ads fetch has failed or returned empty for {streak} consecutive rounds ({n} accounts fell back to the ads_cache this round); inspection coverage is degraded to the 15-minute cache scope. Please check tokens and rate limits.",
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


def req_locale(request) -> str:
    """从请求 X-Locale 头取语言（en/zh，默认 zh）。"""
    try:
        loc = (request.headers.get("x-locale") or "").lower()
    except Exception:
        loc = ""
    return "en" if loc.startswith("en") else "zh"


# 数据字段译表：code -> {zh, en}。值用 {param} 占位（str.format）。
DATA = {
    # ── ads.py ──
    "ads.fbTokenUnavailable": {
        "zh": "该账户的令牌不可用（过期/限流/未绑定），无法读取 FB 实时数据。诊断基于缓存+落地数据。",
        "en": "This account's token is unavailable (expired/throttled/unbound); cannot read live FB data. Diagnosis is based on cache + landing data.",
    },
    # ── fb.py ──
    "fb.checkOk": {
        "zh": "正常 · 权限: {scopes}",
        "en": "OK · scopes: {scopes}",
    },
    "fb.checkInvalid": {
        "zh": "FB 标记无效",
        "en": "FB marked invalid",
    },
    # ── landing.py：worker 部署异常 ──
    "landing.workerError": {
        "zh": "落地页 worker 异常 · {project}",
        "en": "Landing worker error · {project}",
    },
    # ── landing.py：自检 checks[].label ──
    "landing.scStatus": {"zh": "发布状态", "en": "Publish status"},
    "landing.scUrl": {"zh": "公开链接", "en": "Public URL"},
    "landing.scDomain": {"zh": "域名+SSL", "en": "Domain + SSL"},
    "landing.scWorker": {"zh": "Worker存活", "en": "Worker alive"},
    "landing.scPixel": {"zh": "像素配置", "en": "Pixel config"},
    "landing.scTarget": {"zh": "跳转目标", "en": "Redirect target"},
    "landing.scProtection": {"zh": "防护规则", "en": "Protection rules"},
    "landing.scFbBan": {"zh": "FB域名封禁", "en": "FB domain ban"},
    "landing.scFbSubcode": {"zh": "子码FB封禁", "en": "Subcode FB ban"},
    "landing.scPreview": {"zh": "预览模式", "en": "Preview mode"},
    # ── landing.py：防护测试画像 label ──
    "landing.protSampleDesktop": {"zh": "桌面浏览器（美国）", "en": "Desktop browser (US)"},
    "landing.protSampleMobile": {"zh": "移动端（美国）", "en": "Mobile (US)"},
    "landing.protSampleGooglebot": {"zh": "Googlebot 爬虫", "en": "Googlebot crawler"},
    "landing.protSampleBlockedCountry": {"zh": "非允许国（中国）", "en": "Non-allowed country (China)"},
    "landing.protSampleDebugQuery": {"zh": "带调试参数", "en": "With debug param"},
    "landing.protSampleDebugReferer": {"zh": "调试来源 Referer", "en": "Debug source Referer"},
}


def L(locale: str, code: str, **params) -> str:
    """数据字段按 locale 渲染。未知 code 回退原 code。"""
    e = DATA.get(code)
    if not e:
        return code
    s = e.get(locale) or e.get("zh") or code
    try:
        return s.format(**params) if params else s
    except Exception:
        return s
