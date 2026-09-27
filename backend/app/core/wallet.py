# -*- coding: utf-8 -*-
"""钱包记账唯一入口（批1 铁律：余额变更只走这里）。

原子性：行锁（FOR UPDATE）保证并发扣款串行；幂等：(ref_type, ref_id, type) 唯一约束，
重复记账（如监听重试）返回既有流水不再扣/入；断言：balance_after = 记账前 + amount，
余额不得为负（扣款不足=InsufficientBalance，调用方先查再扣或捕获处理）。
"""
import logging
from datetime import datetime, timezone

from fastapi import HTTPException

from ..models.wallet import WalletAccount, WalletTxn

logger = logging.getLogger("toveads.wallet")


class InsufficientBalance(Exception):
    pass


def wallet_apply(db, tenant_id: int, type_: str, amount: float, ref_type: str,
                 ref_id=None, txid: str = "", note: str = "", user_id=None,
                 idempotency: str = "") -> WalletTxn:
    """记账一笔（amount 带符号：+入账 / -扣款）并提交。
    type_: deposit | charge | refund | adjust（adjust 的方向由 amount 符号定）。

    幂等（0109 重构——审计 P0 教训）：只认 idempotency 键（唯一部分索引 + 快查）。
    ref_type/ref_id 转纯对账展示，不再做幂等（旧约束已删——续费曾用域名 row.id 当键，
    同域名第二次续费被旧流水吞掉扣款却照常续费）。idempotency 为空 = 不去重
    （人工 adjust、无重放风险的调用方）。
    同一业务事件的 charge 与 refund 必须用不同 idem 后缀（如 ...-rf）。"""
    if idempotency:
        hit = db.query(WalletTxn).filter(WalletTxn.idempotency == idempotency).first()
        if hit:
            return hit
    # 行锁账户（无则建）
    acc = (db.query(WalletAccount)
           .filter(WalletAccount.tenant_id == tenant_id)
           .with_for_update().first())
    if not acc:
        db.rollback()   # 释放可能的路由级事务，再以干净状态插入
        try:
            db.add(WalletAccount(tenant_id=tenant_id))
            db.commit()
        except Exception:
            db.rollback()   # 并发首建竞态：对方已插
        acc = (db.query(WalletAccount)
               .filter(WalletAccount.tenant_id == tenant_id)
               .with_for_update().first())
        if not acc:
            raise RuntimeError("WALLET_ACCOUNT_CREATE_FAILED")
    new_bal = round(float(acc.balance_usd) + float(amount), 2)
    if new_bal < -0.005:
        db.rollback()
        raise InsufficientBalance(f"余额不足：{acc.balance_usd:.2f} < {abs(amount):.2f}")
    txn = WalletTxn(tenant_id=tenant_id, type=type_, amount_usd=round(float(amount), 2),
                    balance_after=new_bal, ref_type=ref_type, ref_id=ref_id,
                    txid=txid or None, note=note or None, created_by=user_id,
                    idempotency=idempotency or None)
    acc.balance_usd = new_bal
    acc.version = (acc.version or 0) + 1
    db.add(txn)
    try:
        db.commit()
    except Exception:
        # 并发同 idem 撞唯一索引：回滚后按 idem 回读对手已插的流水（幂等收敛）
        db.rollback()
        if idempotency:
            hit = db.query(WalletTxn).filter(WalletTxn.idempotency == idempotency).first()
            if hit:
                return hit
        raise
    logger.info(f"[wallet] t={tenant_id} {type_} {amount:+.2f} → {new_bal:.2f} ref={ref_type}/{ref_id} idem={idempotency or '-'}")
    return txn


def wallet_balance(db, tenant_id: int) -> float:
    acc = db.query(WalletAccount).filter(WalletAccount.tenant_id == tenant_id).first()
    return round(float(acc.balance_usd), 2) if acc else 0.0
