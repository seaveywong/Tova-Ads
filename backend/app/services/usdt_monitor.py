"""USDT-TRC20 到账监听（域名商店收款确认，2026-09-24 批；2026-09-26 全自动化）。

链上公开数据直读（TronGrid = Tron 官方免费 API，无第三方支付网关、零抽成）：
轮询收款地址的 TRC20 USDT 入账 → 按「应付金额 = 总价 + 订单号尾两位美分」精确对号
（TRC20 无 memo，同额订单靠唯一尾数区分）→ 金额校验通过即**自动确认+自动注册**
（用户拍板：充值/直付都全自动，人工只兜异常）——注册链失败才置 failed + 告警
超管人工重试（订单页「确认收款」对 failed 可重入）。钱包充值入账复用本监听。
调度：main.py 每 2 分钟；advisory lock 121。
"""
import logging
import httpx
from datetime import datetime, timezone, timedelta

from ..core.database import SuperSessionLocal, acquire_run_lock, release_run_lock

logger = logging.getLogger("toveads.usdt")

_TRONGRID = "https://api.trongrid.io"
_USDT_TRC20 = "TR7NHqjeKQxGTCi8qMZYkYKsqLWNKq9iC1"   # USDT (TRC20) 官方合约


def pay_amount_cents(total_usd: float, order_id: int) -> int:
    """应付金额（整数美分）= 总价美分 + 订单号尾两位。整数运算，杜绝浮点误差（复审 P1）。"""
    return int(round(float(total_usd) * 100)) + (order_id % 100)


def pay_amount_for(total_usd: float, order_id: int) -> float:
    """应付金额 = 总价 + 订单号尾两位（美分，美元展示用）——唯一化防同额串单（TRC20 无 memo）。"""
    return round(pay_amount_cents(total_usd, order_id) / 100.0, 2)


def _fetch_incoming(addr: str, tg_key: str = "") -> list:
    """拉近 50 笔 USDT-TRC20 入账（TronGrid 免费无 key；失败返 []）。"""
    try:
        headers = {"accept": "application/json"}
        if tg_key:
            headers["TRON-PRO-API-KEY"] = tg_key
        r = httpx.get(f"{_TRONGRID}/v1/accounts/{addr}/transactions/trc20",
                      params={"limit": 50, "only_to": "true",
                              "contract_address": _USDT_TRC20},
                      timeout=20, headers=headers)
        return (r.json() or {}).get("data") or []
    except Exception as e:
        logger.warning(f"[USDT] TronGrid 拉取失败: {e}")
        return []


def _auto_fulfill(db, o) -> str:
    """收款已核实后的自动注册链（复用 domain_shop._fulfill）。成功返 None；失败返原因
    （订单已由 _fulfill 置 failed 留 error，超管可从订单页重入 approve 重试）。"""
    try:
        from ..models.auth import User
        from ..routers.domain_shop import _reg_ready, _fulfill
        su = db.query(User).filter(User.is_superadmin.is_(True)).order_by(User.id).first()
        if not su:
            return "无超管账号可挂自动确认人"
        if not _reg_ready(db):
            o.status = "approved"   # 注册商未配置：留待配置后人工/下轮重试
            o.approved_by, o.approved_at = su.id, datetime.now(timezone.utc)
            db.commit()
            return "注册商凭据未配置（订单已置 approved，配置后点确认收款续链）"
        o.status = "registering"
        o.approved_by, o.approved_at = su.id, datetime.now(timezone.utc)
        db.commit()
        _fulfill(o, su, db)
        return ""
    except Exception as e:
        db.rollback()
        return str(getattr(e, "detail", None) or e)[:200]


def run_usdt_monitor():
    _lock = acquire_run_lock(121)
    if not _lock:
        return
    db = SuperSessionLocal()
    try:
        import json
        from ..models.system import SystemSetting
        from ..models.domain_shop import DomainOrder
        row = db.query(SystemSetting).filter(SystemSetting.key == "payment_usdt").first()
        addr, chain, tg_key, pool = "", "", "", []
        if row and row.value:
            try:
                j = json.loads(row.value)
                addr, chain = str(j.get("address") or ""), str(j.get("chain") or "").upper()
                tg_key = str(j.get("trongrid_api_key") or "")
                if isinstance(j.get("addresses"), list):
                    pool = [str(a).strip() for a in j["addresses"] if str(a).strip()]
            except Exception:
                addr = ""
        if not tg_key:
            from ..core.config import env_val
            tg_key = env_val("TRONGRID_API_KEY")   # 免 key 可用（限流更低），有 key 更稳
        # 收款地址池（2026-09-26 用户拍板）：订单按 id 轮询分池地址；兼容旧单/单地址
        # 模式（payment_address 为空 → 绑池首地址）
        addrs = list(dict.fromkeys([a for a in ([addr] + pool) if len(a) >= 20]))
        if not addrs:
            return
        if chain and "TRC" not in chain:
            return   # 自动监听暂只支持 TRC20（ERC20 留后续）
        pend = db.query(DomainOrder).filter(
            DomainOrder.status == "pending_payment",
        ).order_by(DomainOrder.id.asc()).limit(50).all()   # 复审：旧单优先——同总额且 id%100 相同的两单尾号相同，asc 让入账先对上更早创建的那单（付款人意图通常为先下的单）
        if not pend:
            return
        # 审计 P0 修复（跨轮重复消费）：used_txids 曾仅单轮内存——一笔链上入账在被挤出近 50 笔
        # 前每轮都能再匹配另一张 pending 单（一笔款双倍入账/既交付域名又进余额）。
        # 现每轮先从库里拉全量已消费 txid（订单+充值，量级极小），加上 0109 的 txid 唯一索引双保险
        from ..models.wallet import WalletTopup
        db_used = {x[0] for x in db.query(DomainOrder.payment_txid).filter(
            DomainOrder.payment_txid.isnot(None)).all()}
        db_used |= {x[0] for x in db.query(WalletTopup.txid).filter(
            WalletTopup.txid.isnot(None)).all()}
        tx_cache: dict = {}   # 地址 → 入账列表（多地址各自拉一次，同地址只拉一次）
        hits = 0
        used_txids: set = db_used   # 轮内 + 跨轮（DB）合并去重
        for o in pend:
            target = (o.payment_address or "").strip() or addrs[0]
            if target not in addrs:
                # 审计 P1：地址池被改后旧 pending 单静默失配——用户照页面地址转了款却永不变更。
                # 一次性告警平台（6h dedup）
                from ..core.notify_utils import emit_notification
                from ..core.log_utils import new_trace_id
                emit_notification(db, tenant_id=1, level="warning",
                                  event_type="payment_addr_mismatch", trace_id=new_trace_id(),
                                  title=f"订单 #{o.id} 的收款地址已不在地址池",
                                  body=f"{o.domain} 分配地址 {target[:16]}… 已被移出收款池——"
                                       f"用户按旧地址付款将无法自动确认。请核对链上到账后人工处理，"
                                       f"或把该地址加回池中。", dedup_recent=21600)
                db.commit()
                continue
            if target not in tx_cache:
                tx_cache[target] = _fetch_incoming(target, tg_key)
            txs = tx_cache[target]
            want_cents = pay_amount_cents(o.total_usd, o.id)
            created_ts = (o.created_at or datetime.now(timezone.utc)).timestamp()
            for t in txs:
                try:
                    _txid = str(t.get("transaction_id") or "")
                    if _txid in used_txids:
                        continue
                    if (t.get("to") or "") != target:
                        continue
                    amt_cents = int(round(int(t.get("value", "0")) / 1e4))   # 微单位→美分，整数比较（复审 P1）
                    ts = int(t.get("block_timestamp", 0)) / 1000.0
                except Exception:
                    continue
                if amt_cents != want_cents or ts + 600 < created_ts:
                    continue
                amt = round(amt_cents / 100.0, 2)
                used_txids.add(_txid)
                o.status = "payment_detected"
                o.payment_txid = str(t.get("transaction_id") or "")
                o.paid_amount = amt
                hits += 1
                # 全自动（2026-09-26 用户拍板）：金额精确匹配+TXID 未用过 = 收款确认，
                # 直接进注册链；失败才人工（failed 状态可从订单页重试）
                db.commit()   # 先落 detected——注册链失败时证据（TXID/实收额）不丢
                auto_err = _auto_fulfill(db, o)
                from ..core.notify_utils import emit_notification
                from ..core.log_utils import new_trace_id
                if auto_err:
                    emit_notification(db, tenant_id=o.tenant_id, level="warning",
                                      event_type="domain_auto_fulfill_failed", trace_id=new_trace_id(),
                                      title=f"域名订单 #{o.id} 到账 ${amt}，但自动注册失败",
                                      body=f"{o.domain} TXID {o.payment_txid}\n"
                                           f"原因：{auto_err[:200]}\n"
                                           f"平台已收到告警，将尽快处理；您可在订单页查看进度。")
                else:
                    emit_notification(db, tenant_id=o.tenant_id, level="info",
                                      event_type="domain_delivered", trace_id=new_trace_id(),
                                      title=f"域名 {o.domain} 已自动交付",
                                      body=f"付款已确认，域名已交付，现在可以在投放链接中使用该域名。"
                                           f"（订单 #{o.id}）")
                break
        if hits:
            db.commit()
            logger.info(f"[USDT] 本轮匹配 {hits} 笔待付款订单")
        # ── 钱包充值单匹配（批1：同款地址池+尾号对账，到账即自动入账+通知）──
        from ..models.wallet import WalletTopup
        from ..core.wallet import wallet_apply
        ptup = (db.query(WalletTopup).filter(WalletTopup.status == "pending")
                .order_by(WalletTopup.id.asc()).limit(50).all())
        for tp in ptup:
            t_target = (tp.payment_address or "").strip() or addrs[0]
            if t_target not in addrs:
                from ..core.notify_utils import emit_notification
                from ..core.log_utils import new_trace_id
                emit_notification(db, tenant_id=1, level="warning",
                                  event_type="payment_addr_mismatch", trace_id=new_trace_id(),
                                  title=f"充值单 #{tp.id} 的收款地址已不在地址池",
                                  body=f"充值 ${tp.amount_usd} 分配地址 {t_target[:16]}… 已被移出收款池——"
                                       f"用户按旧地址付款将无法自动入账。请核对链上到账后人工处理。",
                                  dedup_recent=21600)
                db.commit()
                continue
            if t_target not in tx_cache:
                tx_cache[t_target] = _fetch_incoming(t_target, tg_key)
            t_created = (tp.created_at or datetime.now(timezone.utc)).timestamp()
            for t in tx_cache[t_target]:
                try:
                    _txid = str(t.get("transaction_id") or "")
                    if _txid in used_txids or (t.get("to") or "") != t_target:
                        continue
                    amt_cents = int(round(int(t.get("value", "0")) / 1e4))
                    ts = int(t.get("block_timestamp", 0)) / 1000.0
                except Exception:
                    continue
                want_c = int(round(tp.pay_amount * 100))
                if amt_cents != want_c or ts + 600 < t_created:
                    continue
                used_txids.add(_txid)
                tp.status, tp.txid = "paid", _txid
                tp.paid_at = datetime.now(timezone.utc)
                db.commit()
                try:
                    txn = wallet_apply(db, tp.tenant_id, "deposit", tp.amount_usd,
                                       ref_type="topup", ref_id=tp.id, txid=_txid,
                                       user_id=tp.created_by, idempotency=f"topup-{tp.id}")
                    bal = txn.balance_after
                except Exception as we:
                    from ..core.notify_utils import emit_notification
                    from ..core.log_utils import new_trace_id
                    emit_notification(db, tenant_id=tp.tenant_id, level="warning",
                                      event_type="wallet_topup_ingest_failed", trace_id=new_trace_id(),
                                      title=f"充值 #{tp.id} 到账 ${tp.amount_usd}，但入账失败",
                                      body=f"TXID {_txid}\n原因：{str(we)[:200]}\n超管请人工处理（钱包调整补入）。")
                    db.commit()
                    break
                from ..core.notify_utils import emit_notification
                from ..core.log_utils import new_trace_id
                emit_notification(db, tenant_id=tp.tenant_id, level="info",
                                  event_type="wallet_topup_paid", trace_id=new_trace_id(),
                                  title=f"充值到账 ${tp.amount_usd:.2f}，余额 ${bal:.2f}",
                                  body=f"充值已到账，可在钱包流水中查看明细。")
                db.commit()
                logger.info(f"[USDT] 充值 #{tp.id} 入账 ${tp.amount_usd}")
                break
        # 无法认领的到账告警（充值单取消后付款/无单直转/金额不符——曾完全静默）
        _alert_unknown_payments(db, addrs, tx_cache, used_txids)
        # ── 卡死订单收口（审计 P1：扣款后进程死在注册链 → 订单永久卡 registering，
        # approve 拒绝重入、无退款入口）——每轮扫超 30 分钟的 registering 钱包订单：
        # 已有退款流水 → 直接 failed（可重试，重试会重新扣款）；无退款 → 自动退款+failed ──
        _reap_stuck_wallet_orders(db)
    except Exception as e:
        logger.warning(f"[USDT] 监听异常: {e}")
    finally:
        db.close()
        release_run_lock(_lock, 121)


def _reap_stuck_wallet_orders(db) -> None:
    """超 30 分钟仍 registering 的钱包订单收口（进程中断遗孤）。"""
    try:
        from ..models.wallet import WalletTxn
        from ..core.wallet import wallet_apply
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
        stuck = db.query(DomainOrder).filter(
            DomainOrder.status == "registering",
            DomainOrder.payment_method == "wallet",
            DomainOrder.fulfilled_at.is_(None),
            DomainOrder.created_at < cutoff).all()
        for o in stuck:
            refunded = db.query(WalletTxn).filter(
                WalletTxn.tenant_id == o.tenant_id, WalletTxn.type == "refund",
                WalletTxn.ref_type == "domain_order_refund", WalletTxn.ref_id == o.id).first()
            if not refunded:
                wallet_apply(db, o.tenant_id, "refund", round(o.total_usd, 2),
                             ref_type="domain_order_refund", ref_id=o.id,
                             note=f"{o.domain} 注册中断自动退回（进程收口）",
                             idempotency=f"order-refund-{o.id}")
            o.status = "failed"
            o.error = "注册进程中断，已收口（款项已退回余额，可重试）"
            db.commit()
            from ..core.notify_utils import emit_notification
            from ..core.log_utils import new_trace_id
            emit_notification(db, tenant_id=o.tenant_id, level="warning",
                              event_type="domain_order_stuck_reaped", trace_id=new_trace_id(),
                              title=f"域名订单 #{o.id} 注册中断已收口",
                              body=f"{o.domain} 注册过程被中断，扣款已退回余额，订单转为可重试——"
                                   f"请到订单页重新提交。")
            db.commit()
            logger.warning(f"[USDT] 收口卡死钱包订单 #{o.id} {o.domain}")
    except Exception as e:
        db.rollback()
        logger.warning(f"[USDT] 卡死订单收口异常: {e}")


def _alert_unknown_payments(db, addrs, tx_cache, used_txids) -> None:
    """无法认领的到账告警（审计 P1：充值单取消后付款/无单直转/金额不符——款到了链上
    但没有任何 pending 单能认领，曾完全静默）。已消费 txid 之外的近期入账 → 平台告警。"""
    try:
        from ..core.notify_utils import emit_notification
        from ..core.log_utils import new_trace_id
        for addr in addrs:
            txs = tx_cache.get(addr) or _fetch_incoming(addr, "")
            # 重新拉（tx_cache 可能未覆盖该地址——本轮没有分配到它的 pending 单）
            if addr not in tx_cache:
                txs = _fetch_incoming(addr, _tg_key_of(db))
            for t in txs:
                try:
                    _txid = str(t.get("transaction_id") or "")
                    amt = round(int(t.get("value", "0")) / 1e6, 2)
                    ts = datetime.fromtimestamp(int(t.get("block_timestamp", 0)) / 1000.0, tz=timezone.utc)
                except Exception:
                    continue
                if _txid in used_txids or (t.get("to") or "") != addr:
                    continue
                if datetime.now(timezone.utc) - ts > timedelta(minutes=30):
                    continue   # 只报近 30 分钟的新到账（历史孤儿单一次性太多，人工对账另做）
                emit_notification(db, tenant_id=1, level="warning",
                                  event_type="payment_unclaimed", trace_id=new_trace_id(),
                                  title=f"收到无法自动认领的 USDT ${amt}",
                                  body=f"地址 {addr[:16]}… TXID {_txid}\n"
                                       f"没有匹配的待付款订单/充值单（可能：充值单被取消后付款、"
                                       f"金额不符、或无单直转）。请人工核对链上与用户诉求后处理。",
                                  dedup_recent=3600)
                db.commit()
                logger.warning(f"[USDT] 无法认领到账 ${amt} txid={_txid[:16]}…")
                break   # 每地址每轮最多报一条（dedup 兜底）
    except Exception as e:
        db.rollback()
        logger.warning(f"[USDT] 无法认领告警异常: {e}")


def _tg_key_of(db) -> str:
    from ..core.config import env_val
    from ..models.system import SystemSetting
    row = db.query(SystemSetting).filter(SystemSetting.key == "payment_usdt").first()
    if row and row.value:
        try:
            import json as _json
            k = str(_json.loads(row.value).get("trongrid_api_key") or "")
            if k:
                return k
        except Exception:
            pass
    return env_val("TRONGRID_API_KEY")

