# -*- coding: utf-8 -*-
"""钱包路由（批1：充值 USDT 自动入账 / 团队余额 / 流水 / 超管调整与全平台视图）。

口径（2026-09-26 用户答疑定稿）：**团队余额**——消费主体是团队（域名入团队库），
owner/finance/超管可充值查看（billing.view）；个人不做独立钱包（团队内分摊属 V3+）。
充值到账=usdt_monitor 检测（地址池+尾号对账，同域名订单）→ wallet_apply(deposit) 自动入账。
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.deps import CurrentUser, require_permission, require_superadmin
from ..core.wallet import wallet_apply, wallet_balance
from ..core.log_utils import new_trace_id, write_log
from ..core.notify_utils import emit_notification
from ..models.auth import Tenant
from ..models.wallet import WalletAccount, WalletTxn, WalletTopup

router = APIRouter(prefix="/wallet", tags=["wallet"])


def _payment_pool(db) -> list:
    from .domain_shop import _payment_info
    return (_payment_info(db).get("addresses") or [])[:50]


class TopupIn(BaseModel):
    amount_usd: float


@router.post("/topup")
def create_topup(body: TopupIn, user: CurrentUser = Depends(require_permission("billing.view")),
                 db: Session = Depends(get_db)):
    """发起充值：生成充值单（应付=面额+单号尾两位美分，链上对号）+ 池地址分配。"""
    amt = round(float(body.amount_usd), 2)
    if not (1 <= amt <= 100000):
        raise HTTPException(400, "充值金额 1 - 100000 美元")
    pool = _payment_pool(db)
    if not pool:
        raise HTTPException(400, "PAYMENT_NOT_CONFIGURED（管理员未配置收款地址）")
    t = WalletTopup(tenant_id=user.tenant_id, created_by=user.id, amount_usd=amt,
                    pay_amount=amt)   # pay_amount 尾数在 flush 拿到 id 后补
    db.add(t)
    db.flush()
    t.pay_amount = round(amt + (t.id % 100) / 100.0, 2)
    t.payment_address = pool[(t.id - 1) % len(pool)]
    db.commit()
    return {"id": t.id, "amount_usd": amt, "pay_amount": t.pay_amount,
            "status": t.status, "payment_address": t.payment_address}


@router.post("/topup/{tid}/cancel")
def cancel_topup(tid: int, user: CurrentUser = Depends(require_permission("billing.view")),
                 db: Session = Depends(get_db)):
    t = db.query(WalletTopup).filter(WalletTopup.id == tid).first()
    if not t:
        raise HTTPException(404, "充值单不存在")
    if t.tenant_id != user.tenant_id and not getattr(user, "is_superadmin", False):
        raise HTTPException(404, "充值单不存在")
    if t.status != "pending":
        raise HTTPException(400, "仅待转账充值单可取消")
    t.status = "cancelled"
    db.commit()
    return {"ok": True}


@router.get("")
def wallet_view(user: CurrentUser = Depends(require_permission("billing.view")),
                db: Session = Depends(get_db)):
    """团队钱包：余额 + 待转账充值单 + 最近流水（充值/扣款/退款/调整）。"""
    txns = (db.query(WalletTxn).filter(WalletTxn.tenant_id == user.tenant_id)
            .order_by(WalletTxn.id.desc()).limit(50).all())
    pend = (db.query(WalletTopup).filter(WalletTopup.tenant_id == user.tenant_id,
                                         WalletTopup.status == "pending")
            .order_by(WalletTopup.id.desc()).limit(10).all())
    return {
        "balance_usd": wallet_balance(db, user.tenant_id),
        "pending_topups": [{"id": t.id, "amount_usd": t.amount_usd, "pay_amount": t.pay_amount,
                            "payment_address": t.payment_address,
                            "created_at": str(t.created_at or "")[:16]} for t in pend],
        "txns": [{"id": x.id, "type": x.type, "amount_usd": x.amount_usd,
                  "balance_after": x.balance_after, "ref_type": x.ref_type, "ref_id": x.ref_id,
                  "txid": x.txid or "", "note": x.note or "",
                  "created_at": str(x.created_at or "")[:16]} for x in txns],
    }


@router.get("/all")
def wallet_all(user: CurrentUser = Depends(require_superadmin),
               db: Session = Depends(get_db)):
    """全平台钱包（超管对账）：各团队余额 + 总额。"""
    accs = db.query(WalletAccount).order_by(WalletAccount.balance_usd.desc()).all()
    tmap = {t.id: t.name for t in db.query(Tenant).all()}
    return {"teams": [{"tenant_id": a.tenant_id, "team": tmap.get(a.tenant_id, str(a.tenant_id)),
                       "balance_usd": round(float(a.balance_usd), 2),
                       "updated_at": str(a.updated_at or "")[:16]} for a in accs],
            "total_usd": round(sum(float(a.balance_usd) for a in accs), 2)}


class AdjustIn(BaseModel):
    tenant_id: int
    amount_usd: float   # 带符号：+加款 / -扣款
    note: str = ""


@router.post("/adjust")
def wallet_adjust(body: AdjustIn, user: CurrentUser = Depends(require_superadmin),
                  db: Session = Depends(get_db)):
    """超管人工调整（退款/纠错/赠款统一走这里；流水留痕 ref=manual）。"""
    amt = round(float(body.amount_usd), 2)
    if amt == 0:
        raise HTTPException(400, "调整金额不能为 0")
    if not (-1000000 <= amt <= 1000000):
        raise HTTPException(400, "金额超出范围")
    if not (body.note or "").strip():
        raise HTTPException(400, "请填调整原因（流水备注必填）")
    try:
        txn = wallet_apply(db, body.tenant_id, "adjust", amt,
                           ref_type="manual", ref_id=None, note=body.note.strip()[:200],
                           user_id=user.id)
    except Exception as e:
        raise HTTPException(400, f"调整失败：{str(e)[:120]}")
    # 手动调整幂等键为 None——同因多笔允许（人工操作，流水为准）
    write_log(db, tenant_id=body.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, target_type="wallet", target_id=str(txn.id),
              action_type="adjust", source="wallet", result="success",
              trigger_detail=f"{amt:+.2f} → {txn.balance_after:.2f} note={body.note[:80]}")
    db.commit()
    emit_notification(db, tenant_id=body.tenant_id, level="info",
                      event_type="wallet_adjusted", trace_id=new_trace_id(),
                      title=f"钱包余额调整 {amt:+.2f} USD",
                      body=f"调整后余额 ${txn.balance_after:.2f}。原因：{body.note.strip()[:120]}")
    db.commit()
    return {"ok": True, "balance_usd": txn.balance_after}
