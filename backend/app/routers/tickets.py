"""工单路由：建/列/详情/回复/关闭（doc 07）。只沟通不代操作。"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from ..core.database import get_db
from ..core.deps import CurrentUser, require_permission
from ..core.log_utils import write_log, new_trace_id
from ..core.notify_utils import emit_notification
from ..models.ticket import Ticket, TicketMessage

router = APIRouter(prefix="/tickets", tags=["tickets"])


class CreateTicketIn(BaseModel):
    subject: str
    body: str
    target_type: str = "general"
    target_id: str | None = None


class ReplyIn(BaseModel):
    body: str


@router.post("")
def create_ticket(body: CreateTicketIn,
                  user: CurrentUser = Depends(require_permission("ads.read")),
                  db: Session = Depends(get_db)):
    ticket = Ticket(tenant_id=user.tenant_id, created_by=user.id,
                    subject=body.subject, target_type=body.target_type, target_id=body.target_id)
    db.add(ticket)
    db.flush()
    tid = ticket.id
    msg = TicketMessage(ticket_id=tid, tenant_id=user.tenant_id,
                        author_type="user", author_user_id=user.id, body=body.body)
    db.add(msg)
    db.flush()
    trace_id = new_trace_id()
    write_log(db, tenant_id=user.tenant_id, trace_id=trace_id, actor_type="user",
              actor_user_id=user.id, target_type="ticket", target_id=str(tid),
              action_type="create", source="user", result="success")
    db.commit()
    return {"id": tid, "status": "open", "subject": ticket.subject}


@router.get("")
def list_tickets(user: CurrentUser = Depends(require_permission("ads.read")),
                 db: Session = Depends(get_db), status: str | None = None):
    query = db.query(Ticket).filter(Ticket.tenant_id == user.tenant_id)
    if status:
        query = query.filter(Ticket.status == status)
    tickets = query.order_by(Ticket.updated_at.desc()).limit(50).all()
    return [{"id": t.id, "subject": t.subject, "status": t.status,
             "target_type": t.target_type, "created_at": str(t.created_at)} for t in tickets]


@router.get("/{ticket_id}")
def get_ticket(ticket_id: int, user: CurrentUser = Depends(require_permission("ads.read")),
               db: Session = Depends(get_db)):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(404, "工单不存在")
    msgs = db.query(TicketMessage).filter(TicketMessage.ticket_id == ticket_id).all()
    return {
        "id": ticket.id, "subject": ticket.subject, "status": ticket.status,
        "target_type": ticket.target_type, "target_id": ticket.target_id,
        "messages": [{"id": m.id, "author_type": m.author_type, "body": m.body,
                      "created_at": str(m.created_at)} for m in msgs],
    }


@router.post("/{ticket_id}/messages")
def reply(ticket_id: int, body: ReplyIn,
          user: CurrentUser = Depends(require_permission("ads.read")),
          db: Session = Depends(get_db)):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(404, "工单不存在")
    if ticket.status == "closed":
        raise HTTPException(400, "工单已关闭")
    if ticket.status == "open":
        ticket.status = "in_progress"
    ticket.updated_at = datetime.now(timezone.utc)
    msg = TicketMessage(ticket_id=ticket_id, tenant_id=user.tenant_id,
                        author_type="user", author_user_id=user.id, body=body.body)
    db.add(msg)
    db.flush()
    db.commit()
    return {"id": msg.id, "status": ticket.status}


@router.post("/{ticket_id}/close")
def close_ticket(ticket_id: int,
                 user: CurrentUser = Depends(require_permission("ads.read")),
                 db: Session = Depends(get_db)):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(404, "工单不存在")
    ticket.status = "closed"
    ticket.closed_at = datetime.now(timezone.utc)
    db.commit()
    return {"id": ticket.id, "status": "closed"}
