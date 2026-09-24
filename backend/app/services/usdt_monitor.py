"""USDT-TRC20 到账监听（域名商店收款确认，2026-09-24 批）。

链上公开数据直读（TronGrid = Tron 官方免费 API，无第三方支付网关、零抽成）：
轮询收款地址的 TRC20 USDT 入账 → 按「应付金额 = 总价 + 订单号尾两位美分」精确对号
（TRC20 无 memo，同额订单靠唯一尾数区分）→ pending_payment 转 payment_detected
（TXID/实收额入库 + 通知带证据）→ 超管一键确认后注册。全自动模式留钱包批。
调度：main.py 每 2 分钟；advisory lock 121。
"""
import logging
import httpx
from datetime import datetime, timezone

from ..core.database import SuperSessionLocal, acquire_run_lock, release_run_lock

logger = logging.getLogger("toveads.usdt")

_TRONGRID = "https://api.trongrid.io"
_USDT_TRC20 = "TR7NHqjeKQxGTCi8qMZYkYKsqLWNKq9iC1"   # USDT (TRC20) 官方合约


def pay_amount_for(total_usd: float, order_id: int) -> float:
    """应付金额 = 总价 + 订单号尾两位（美分）——唯一化防同额串单（TRC20 无 memo）。"""
    return round(float(total_usd) + (order_id % 100) / 100.0, 2)


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
        addr, chain, tg_key = "", "", ""
        if row and row.value:
            try:
                j = json.loads(row.value)
                addr, chain = str(j.get("address") or ""), str(j.get("chain") or "").upper()
                tg_key = str(j.get("trongrid_api_key") or "")
            except Exception:
                addr = ""
        if not tg_key:
            from ..core.config import env_val
            tg_key = env_val("TRONGRID_API_KEY")   # 免 key 可用（限流更低），有 key 更稳
        if not addr or len(addr) < 20:
            return
        if chain and "TRC" not in chain:
            return   # 自动监听暂只支持 TRC20（ERC20 留后续）
        pend = db.query(DomainOrder).filter(
            DomainOrder.status == "pending_payment",
        ).order_by(DomainOrder.id.asc()).limit(50).all()   # 复审：旧单优先——同总额且 id%100 相同的两单尾号相同，asc 让入账先对上更早创建的那单（付款人意图通常为先下的单）
        if not pend:
            return
        txs = _fetch_incoming(addr, tg_key)
        hits = 0
        for o in pend:
            want = pay_amount_for(o.total_usd, o.id)
            created_ts = (o.created_at or datetime.now(timezone.utc)).timestamp()
            for t in txs:
                try:
                    if (t.get("to") or "") != addr:
                        continue
                    amt = round(int(t.get("value", "0")) / 1e6, 2)
                    ts = int(t.get("block_timestamp", 0)) / 1000.0
                except Exception:
                    continue
                if amt != want or ts + 600 < created_ts:
                    continue
                o.status = "payment_detected"
                o.payment_txid = str(t.get("transaction_id") or "")
                o.paid_amount = amt
                hits += 1
                from ..core.notify_utils import emit_notification
                from ..core.log_utils import new_trace_id
                emit_notification(db, tenant_id=o.tenant_id, level="info",
                                  event_type="domain_payment_detected", trace_id=new_trace_id(),
                                  title=f"域名订单 #{o.id} 检测到 USDT 到账 ${amt}",
                                  body=f"{o.domain} 应付 ${want}（含订单尾号）\n"
                                       f"TXID {o.payment_txid}\n"
                                       f"请到 投放链接 → 域名 → 订单 一键确认收款，确认后自动注册并接入。")
                break
        if hits:
            db.commit()
            logger.info(f"[USDT] 本轮匹配 {hits} 笔待付款订单")
    except Exception as e:
        logger.warning(f"[USDT] 监听异常: {e}")
    finally:
        db.close()
        release_run_lock(_lock, 121)
