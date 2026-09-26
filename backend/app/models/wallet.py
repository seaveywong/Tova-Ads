# -*- coding: utf-8 -*-
"""钱包模型（2026-09-26 批1，方案见 toveads/钱包计费方案.md v2）。

口径：**团队余额**（tenant 级唯一账户）——消费主体是团队（域名入团队库、订单属团队），
与 RBAC 域一致；充值/查看=billing.view（owner/finance/超管）。
铁律：余额变更只走 core/wallet.py wallet_apply()（行锁+幂等+balance_after 断言），
任何直接 UPDATE balance_usd 都是 bug。
"""
from sqlalchemy import BigInteger, ForeignKey, Integer, Text, Float, DateTime, UniqueConstraint, func

from ..core.database import Base


class WalletAccount(Base):
    __tablename__ = "wallet_accounts"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False, unique=True, index=True)
    balance_usd = Column(Float, nullable=False, default=0)
    version = Column(Integer, nullable=False, default=0)   # 乐观锁（行锁主防，双保险）
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WalletTxn(Base):
    __tablename__ = "wallet_txns"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False, index=True)
    # type×方向：deposit=充值入账 / charge=消费扣款 / refund=退款入账 / adjust=人工调整(±)
    type = Column(Text, nullable=False)
    amount_usd = Column(Float, nullable=False)             # 带符号：+入账 / -扣款
    balance_after = Column(Float, nullable=False)          # 记账后余额快照（对账断言）
    ref_type = Column(Text, nullable=False)                # topup / domain_order / manual
    ref_id = Column(BigInteger)                            # 关联单号
    txid = Column(Text)                                    # 链上证据（充值）
    note = Column(Text)
    created_by = Column(BigInteger)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("ref_type", "ref_id", "type", name="uq_wallet_txn_ref"),)


class WalletTopup(Base):
    """充值单（USDT-TRC20，与域名订单同款到账监听+地址池分配+尾号对账）。"""
    __tablename__ = "wallet_topups"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False, index=True)
    created_by = Column(BigInteger)
    amount_usd = Column(Float, nullable=False)             # 充值面额
    pay_amount = Column(Float, nullable=False)             # 面额 + id%100 美分（链上对号）
    payment_address = Column(Text)                         # 地址池分配
    status = Column(Text, nullable=False, default="pending")   # pending / paid / cancelled
    txid = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    paid_at = Column(DateTime(timezone=True))
