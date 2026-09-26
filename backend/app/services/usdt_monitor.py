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
from datetime import datetime, timezone

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
        tx_cache: dict = {}   # 地址 → 入账列表（多地址各自拉一次，同地址只拉一次）
        hits = 0
        used_txids: set = set()   # 复审II：同一笔入账只能消费一次——曾内层 break 只跳单不标 tx，
        # 同尾号两单会被同一笔付款重复匹配（一笔款标两单 detected）
        for o in pend:
            target = (o.payment_address or "").strip() or addrs[0]
            if target not in addrs:
                continue   # 订单分到的地址已不在池中（池被改）——留人工
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
                                           f"超管请在 投放链接 → 域名 → 订单 点「确认收款」重试注册链。")
                else:
                    emit_notification(db, tenant_id=o.tenant_id, level="info",
                                      event_type="domain_delivered", trace_id=new_trace_id(),
                                      title=f"域名 {o.domain} 已自动交付",
                                      body=f"订单 #{o.id} 检测到 USDT 到账 ${amt}（TXID {o.payment_txid}），"
                                           f"已自动确认并完成注册接入，现在可以在落地页中使用该域名。")
                break
        if hits:
            db.commit()
            logger.info(f"[USDT] 本轮匹配 {hits} 笔待付款订单")
    except Exception as e:
        logger.warning(f"[USDT] 监听异常: {e}")
    finally:
        db.close()
        release_run_lock(_lock, 121)
