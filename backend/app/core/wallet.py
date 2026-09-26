# -*- coding: utf-8 -*-
"""钱包记账唯一入口（批1 铁律：余额变更只走这里）。

原子性：行锁（FOR UPDATE）保证并发扣款串行；幂等：(ref_type, ref_id, type) 唯一约束，
重复记账（如监听重试）返回既有流水不再扣/入；断言：balance_after = 记账前 + amount，
余额不得为负（扣款不足=InsufficientBalance，调用方先查再扣或捕获处理）。
"""
import logging
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import text

from ..database import SuperSessionLocal
from ..models.wallet import WalletAccount, WalletTxn

logger = logging.getLogger("toveads.wallet")


class InsufficientBalance(Exception):
    pass


def wallet_apply(db, tenant_id: int, type_: str, amount: float, ref_type: str,
                 ref_id=None, txid: str = "", note: str = "", user_id=None) -> WalletTxn:
    """记账一笔（amount 带符号：+入账 / -扣款）并提交。幂等：同 ref 已记则直接返回旧流水。
    type_: deposit | charge | refund | adjust（adjust 的方向由 amount 符号定）。"""
    # 幂等快查（唯一约束兜底并发）。ref_id=None（人工调整）无幂等键——每笔必记，
    # 不能查 NULL 旳流水（会把新调整误判为已记）
    if ref_id is not None:
        hit = db.query(WalletTxn).filter(WalletTxn.ref_type == ref_type,
                                         WalletTxn.ref_id == ref_id,
                                         WalletTxn.type == type_).first()
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
                    txid=txid or None, note=note or None, created_by=user_id)
    acc.balance_usd = new_bal
    acc.version = (acc.version or 0) + 1
    db.add(txn)
    db.commit()
    logger.info(f"[wallet] t={tenant_id} {type_} {amount:+.2f} → {new_bal:.2f} ref={ref_type}/{ref_id}")
    return txn


def wallet_balance(db, tenant_id: int) -> float:
    acc = db.query(WalletAccount).filter(WalletAccount.tenant_id == tenant_id).first()
    return round(float(acc.balance_usd), 2) if acc else 0.0
