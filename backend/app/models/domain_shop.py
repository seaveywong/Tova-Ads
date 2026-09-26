"""域名代购订单 ORM（批DD 预埋，迁移 0103）。"""
from sqlalchemy import Column, BigInteger, Text, Integer, Float, DateTime, ForeignKey, func
from ..core.database import Base


class DomainOrder(Base):
    __tablename__ = "domain_orders"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    created_by = Column(BigInteger, ForeignKey("users.id"))
    domain = Column(Text, nullable=False)
    years = Column(Integer, nullable=False, default=1)
    cost_usd = Column(Float, nullable=False)
    fee_usd = Column(Float, nullable=False, default=5)
    total_usd = Column(Float, nullable=False)
    status = Column(Text, nullable=False, default="pending_payment")
    payment_method = Column(Text, nullable=False, default="usdt")   # 0104：暂统一 USDT，后续扩展枚举
    kind = Column(Text, nullable=False, default="register")   # 0108：register | renew（续费复用订单双通道）
    payment_txid = Column(Text)   # 0105：到账检测的链上 TXID（payment_detected 证据）
    payment_address = Column(Text)  # 0106：收款地址池分配给本单的地址（多地址对账/防资金流串联）
    paid_amount = Column(Float)    # 0105：实收金额（=应付含尾数）
    error = Column(Text)
    porkbun_order_id = Column(Text)
    cf_zone_id = Column(Text)
    approved_by = Column(BigInteger)
    approved_at = Column(DateTime(timezone=True))
    fulfilled_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
