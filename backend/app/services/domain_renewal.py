# -*- coding: utf-8 -*-
"""域名生命周期 cron（批2，2026-09-27 拍板：自动续费默认开+双通道续费）。

每日一次（main.py 注册 05:17；advisory lock 120）：
① 同步：拉注册商域名列表对齐本地 expires_at（用户可能直连注册商续过费；账户暂无
   Dynadot 域名时响应形状未证——defensive 解析多组键名，永不炸 cron）
② 提醒：30/14/7/3/1 天五档 + 过期档（0），owner 通知（last_notice_tier 去重；续费后重置）
③ 自动续费：到期前 14/3 天，auto_renew 开 + 余额够 → 扣款+renew+通知；余额不足只提醒
   绝不垫付（用户钱包的钱不自动透支）。
"""
import logging
from datetime import datetime, timezone, date as _date, timedelta as _td

from ..core.database import SuperSessionLocal, acquire_run_lock, release_run_lock

logger = logging.getLogger("toveads.domain_renewal")

_TIERS = [30, 14, 7, 3, 1]   # 提醒档（天）


def _registrar_creds():
    """当前注册商客户端（dynadot 优先；未配置返 None）。"""
    from ..core.config import settings, env_val
    key = env_val("DYNADOT_API_KEY") or settings.dynadot_api_key
    if key:
        from ..core.dynadot_client import DynadotClient
        secret = env_val("DYNADOT_API_SECRET") or settings.dynadot_api_secret
        return "dynadot", DynadotClient(key, secret)
    if settings.porkbun_api_key:
        from ..core.porkbun_client import PorkbunClient
        return "porkbun", PorkbunClient(settings.porkbun_api_key, settings.porkbun_secret_key)
    return "", None


def _sync_expiry(db) -> None:
    """注册商域名列表 → 对齐本地 expires_at（只认本地已登记域名；未登记的留给 CF 对账面板）。"""
    from ..models.landing_lib import LandingDomain
    reg, client = _registrar_creds()
    if not client:
        return
    rows = []
    try:
        if reg == "dynadot":
            data = client._call("GET", "/restful/v2/domains/domain_list", signed=True)
            # 响应形状未实证（账户暂无域名）——defensive 多键名
            rows = (data.get("domain_list") or data.get("domains") or data.get("items")
                    or data.get("data") or [])
        else:
            r = client.list_domains() if hasattr(client, "list_domains") else []
            rows = r if isinstance(r, list) else (r.get("domains") or [])
    except Exception as e:
        logger.warning(f"[renewal] 注册商域名列表拉取失败（跳过同步）: {e}")
        return
    by_name = {d.domain.lower(): d for d in db.query(LandingDomain).all()}
    touched = 0
    for it in rows:
        if not isinstance(it, dict):
            continue
        name = str(it.get("domain") or it.get("name") or it.get("domain_name") or "").lower().strip()
        if not name or name not in by_name:
            continue
        exp = _parse_exp(it.get("expiration_date") or it.get("expires_on")
                         or it.get("expiry") or it.get("expires"))
        if exp:
            row = by_name[name]
            row.registrar = row.registrar or reg
            if not row.expires_at or abs((row.expires_at - exp).total_seconds()) > 86400:
                row.expires_at = exp
                touched += 1
    if touched:
        db.commit()
        logger.info(f"[renewal] 同步到期日 {touched} 个域名")


def _parse_exp(v):
    """到期值解析：毫秒/秒时间戳或 ISO 字符串 → datetime(UTC)；失败返 None。"""
    if v in (None, "", 0, "0"):
        return None
    try:
        if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):
            ms = int(v)
            if ms > 1e12:
                ms /= 1000.0
            return datetime.fromtimestamp(ms, tz=timezone.utc)
        s = str(v).replace("Z", "+00:00").replace(" ", "T", 1) if " " in str(v) and "T" not in str(v) else str(v)
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _do_renew(db, row, years: int, actor_id=None, note: str = "") -> dict:
    """执行续费：注册商 renew + 本地 expires_at 顺延 + 履历。异常上抛由调用方处理。"""
    reg, client = _registrar_creds()
    if not client or not row.registrar or row.registrar == "external":
        raise RuntimeError("该域名无可续费的注册商（自有域名请在注册商侧续费）")
    r = client.renew(row.domain, years)
    base = row.expires_at if (row.expires_at and row.expires_at > datetime.now(timezone.utc)) \
        else datetime.now(timezone.utc)
    exp = _parse_exp((r or {}).get("expiration_date"))
    row.expires_at = exp or (base + _td(days=365 * years))
    row.last_renewed_at = datetime.now(timezone.utc)
    row.last_notice_tier = None   # 续费成功重置提醒档
    db.commit()
    return {"registrar": reg, "expires_at": row.expires_at,
            "response_exp": bool(exp)}


def _notify(db, tenant_id, level, title, body):
    from ..core.notify_utils import emit_notification
    from ..core.log_utils import new_trace_id
    emit_notification(db, tenant_id=tenant_id, level=level,
                      event_type="domain_renewal", trace_id=new_trace_id(),
                      title=title, body=body)
    db.commit()


def run_domain_renewal():
    _lock = acquire_run_lock(120)
    if not _lock:
        return
    db = SuperSessionLocal()
    try:
        _sync_expiry(db)
        from ..models.landing_lib import LandingDomain
        from ..core.wallet import wallet_balance, wallet_apply, InsufficientBalance
        from .domain_shop import _pricing, _registrar_client, _fee_for
        today = _date.today()
        rows = db.query(LandingDomain).filter(
            LandingDomain.status == "active", LandingDomain.expires_at.isnot(None)).all()
        client = None
        for row in rows:
            days = (row.expires_at.date() - today).days
            name = row.domain
            # ── 提醒档（30/14/7/3/1；过期=0 档一次）──
            tier = next((t for t in _TIERS if days == t), None)
            if days < 0:
                tier = 0 if (row.last_notice_tier or 99) != 0 else None
            if tier is not None and row.last_notice_tier != tier:
                row.last_notice_tier = tier
                db.commit()
                if days < 0:
                    _notify(db, row.tenant_id, "warning", f"域名 {name} 已过期",
                            f"到期日 {row.expires_at.date()}。宽限期内仍可原价续费；超过宽限期进入赎回（费用高）。"
                            f"请到 投放链接 → 域名 续费或充值开启自动续费。")
                else:
                    _notify(db, row.tenant_id, "warning" if days <= 7 else "info",
                            f"域名 {name} {days} 天后到期",
                            f"到期日 {row.expires_at.date()}。"
                            f"{'自动续费已关闭，' if not row.auto_renew else ''}请确保钱包余额充足或手动续费。")
            if days > 31:
                continue
            # ── 自动续费（T-14 / T-3；auto_renew 开 + 有注册商 + 可续费域名）──
            if days in (14, 3) and row.auto_renew and row.registrar and row.registrar != "external":
                try:
                    if client is None:
                        client = _registrar_client(db)
                    pricing = _pricing(client, db)
                    tld = name.rsplit(".", 1)[-1]
                    unit = (pricing.get(tld) or {}).get("renewal")
                    if unit is None:
                        _notify(db, row.tenant_id, "warning", f"域名 {name} 无法自动续费",
                                f".{tld} 续费价缺失（价目表无此 TLD），请手动处理。")
                        continue
                    total = round(unit + _fee_for(db, unit), 2)
                    if wallet_balance(db, row.tenant_id) < total - 0.005:
                        _notify(db, row.tenant_id, "warning", f"域名 {name} 余额不足，无法自动续费",
                                f"自动续费需 ${total:.2f}（1 年），当前余额不足。请充值——"
                                f"{days} 天后到期（{row.expires_at.date()}）。")
                        continue
                    # 幂等键分档（T-14/T-3 各一次）：同 ref_type+ref_id+type 唯一——
                    # 若共用一个 ref，T-3 的扣款会被幂等快查吞掉（返回旧流水不扣钱）却照常续费
                    rt = f"domain_renew_t{days}"
                    wallet_apply(db, row.tenant_id, "charge", -total,
                                 ref_type=rt, ref_id=row.id, note=f"{name} 自动续费 1y")
                    try:
                        _do_renew(db, row, 1, note="auto")
                        _notify(db, row.tenant_id, "info", f"域名 {name} 已自动续费 1 年",
                                f"扣款 ${total:.2f}，新到期日 {row.expires_at.date()}。")
                    except Exception as re_:
                        wallet_apply(db, row.tenant_id, "refund", total,
                                     ref_type=rt + "_refund", ref_id=row.id,
                                     note=f"{name} 自动续费失败退回")
                        _notify(db, row.tenant_id, "warning", f"域名 {name} 自动续费失败（已退款）",
                                f"扣款已退回余额。原因：{str(re_)[:150]}。请手动续费或联系平台。")
                except InsufficientBalance:
                    pass
                except Exception as e:
                    logger.warning(f"[renewal] {name} 自动续费异常: {e}")
    except Exception as e:
        logger.warning(f"[renewal] 域名生命周期 cron 异常: {e}")
    finally:
        db.close()
        release_run_lock(_lock, 120)
