"""ORM：工单 + 消息（doc 07）。"""
from sqlalchemy import Column, BigInteger, Text, DateTime, ForeignKey, func
from ..core.database import Base


class Ticket(Base):
    __tablename__ = "tickets"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    created_by = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    subject = Column(Text, nullable=False)
    target_type = Column(Text)
    target_id = Column(Text)
    status = Column(Text, default="open")
    priority = Column(Text, default="normal")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
    closed_at = Column(DateTime(timezone=True))


class TicketMessage(Base):
    __tablename__ = "ticket_messages"
    id = Column(BigInteger, primary_key=True)
    ticket_id = Column(BigInteger, ForeignKey("tickets.id"), nullable=False)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    author_type = Column(Text, default="user")
    author_user_id = Column(BigInteger)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
