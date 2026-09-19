"""域名商店路由（批DD 预埋 2026-09-19；同日切 Dynadot 主力）：查价/下单/批准→自动注册→自动接入 CF。

状态机：pending_payment（等付款；钱包上线后自动冻结扣，当前=超管人工确认收款）
  → approved（超管确认）→ 注册链（registering→registered→bound） / failed（原因入库）
全自动链 = 注册商注册（NS 指向 CF）→ CF 建 zone → 入 landing_domains（source=purchased）
→ 团队立即可在其下建落地页子域。注册商由 system_settings['domain_registrar'] 选（dynadot|porkbun），
未配置：查价/批准返回明确引导，订单可先建。
计费预埋：手续费 system_settings['domain_shop_fee_usd']（默认 5），钱包上线后换 pricing_rules。
"""
import re
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..core.config import settings
from ..core.database import get_db, SuperSessionLocal
from ..core.deps import CurrentUser, require_permission, require_superadmin
from ..core.log_utils import write_log, new_trace_id
from ..core.porkbun_client import PorkbunClient, porkbun_configured
from ..core.dynadot_client import DynadotClient, DynadotError
from ..models.landing_lib import LandingDomain

router = APIRouter(prefix="/domains-shop", tags=["domains-shop"])

# 查价缓存（模块级 10min——两注册商 pricing 全表均一次拉，逐单查太浪费且 Dynadot 限 1 req/s）
_PRICING_CACHE: dict = {}
_PRICING_TTL = 600

_FEE_KEY = "domain_shop_fee_usd"
_DEFAULT_FEE = 5.0


def _reg_name(db) -> str:
    """当前注册商（system_settings['domain_registrar']，默认 dynadot）。"""
    from ..models.system import SystemSetting
    row = db.query(SystemSetting).filter(SystemSetting.key == "domain_registrar").first()
    return (row.value if row and row.value in ("dynadot", "porkbun") else "dynadot")


def _reg_ready(db) -> bool:
    if _reg_name(db) == "dynadot":
        return bool(settings.dynadot_api_key)
    return porkbun_configured(settings)


def _registrar_client(db):
    """按选择返回注册商客户端；未配置 400 引导。"""
    if _reg_name(db) == "dynadot":
        if not settings.dynadot_api_key:
            raise HTTPException(400, "DYNADOT_NOT_CONFIGURED")
        return DynadotClient(settings.dynadot_api_key)
    if not porkbun_configured(settings):
        raise HTTPException(400, "PORKBUN_NOT_CONFIGURED")
    return PorkbunClient(settings.porkbun_api_key, settings.porkbun_secret_key)


def _pricing(client, db) -> dict:
    """{tld: {registration, renewal}}（10min 缓存；两注册商客户端已统一此形状）。"""
    import time as _t
    now = _t.time()
    if not _PRICING_CACHE or now - _PRICING_CACHE["at"] > _PRICING_TTL:
        _PRICING_CACHE["pricing"] = client.pricing()
        _PRICING_CACHE["at"] = now
    return _PRICING_CACHE["pricing"] or {}


def _avail(client, d: str) -> dict:
    """可注册性 + 实时价：Dynadot search 一步到位；Porkbun check。"""
    if isinstance(client, DynadotClient):
        r = client.search(d)
        return {"available": r["available"], "price": r.get("price_usd")}
    chk = client.check(d)
    return {"available": str(chk.get("porkbunAvailable")) == "yes", "price": None}


def _fee(db) -> float:
    from ..models.system import SystemSetting
    row = db.query(SystemSetting).filter(SystemSetting.key == _FEE_KEY).first()
    try:
        return float(row.value) if row else _DEFAULT_FEE
    except (TypeError, ValueError):
        return _DEFAULT_FEE


def _norm_domain(raw: str) -> str:
    d = (raw or "").strip().lower().rstrip(".")
    d = d.replace("https://", "").replace("http://", "").split("/")[0]
    if not re.match(r"^[a-z0-9][a-z0-9.-]*[a-z0-9]$", d) or "." not in d or len(d) > 253:
        raise HTTPException(400, "域名格式不正确（例：mybrand.com）")
    parts = d.split(".")
    if len(parts) > 4 or any(len(p) < 1 for p in parts):
        raise HTTPException(400, "域名格式不正确（例：mybrand.com）")
    return d


@router.get("/check")
def check_domain(domain: str = "", user: CurrentUser = Depends(require_permission("landing.manage")),
                 db: Session = Depends(get_db)):
    """可注册性 + 实时报价（成本 + 手续费 + 总价）。未配置注册商 → 400 引导。"""
    d = _norm_domain(domain)
    tld = d.rsplit(".", 1)[-1]
    client = _registrar_client(db)
    price = _pricing(client, db).get(tld)
    if not price or price.get("registration") is None:
        raise HTTPException(400, f"暂不支持 .{tld} 后缀")
    av = _avail(client, d)
    fee = _fee(db)
    # Dynadot search 自带实时价（premium 域与表价不同），有则优先
    cost = av.get("price") if av.get("price") is not None else price["registration"]
    return {"domain": d, "available": av["available"], "tld": tld,
            "cost_usd": cost, "fee_usd": fee, "total_usd": round(cost + fee, 2),
            "renewal_usd": price.get("renewal")}


class OrderIn(BaseModel):
    domain: str
    years: int = 1


@router.post("/orders")
def create_order(body: OrderIn, user: CurrentUser = Depends(require_permission("landing.manage")),
                 db: Session = Depends(get_db)):
    """下单：成本快照（下单时实时价）→ pending_payment 等付款确认。"""
    d = _norm_domain(body.domain)
    if body.years < 1 or body.years > 10:
        raise HTTPException(400, "年限 1-10")
    client = _registrar_client(db)
    tld = d.rsplit(".", 1)[-1]
    price = _pricing(client, db).get(tld)
    if not price or price.get("registration") is None:
        raise HTTPException(400, f"暂不支持 .{tld} 后缀")
    av = _avail(client, d)
    if not av["available"]:
        raise HTTPException(400, "该域名不可注册（已被占用或不支持）")
    unit = av.get("price") if av.get("price") is not None else price["registration"]
    cost = round(unit * body.years, 2)
    fee = _fee(db)
    from ..models.system import SystemSetting  # noqa: F401（表已 import 路径一致）
    from ..models.domain_shop import DomainOrder
    order = DomainOrder(tenant_id=user.tenant_id, created_by=user.id, domain=d,
                        years=body.years, cost_usd=cost, fee_usd=fee,
                        total_usd=round(cost + fee, 2), status="pending_payment")
    db.add(order)
    db.commit()
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, target_type="domain_order", target_id=str(order.id),
              action_type="create", source="domain_shop", result="success",
              trigger_detail=f"{d} x{body.years}y total={order.total_usd}")
    db.commit()
    return {"id": order.id, "domain": d, "years": body.years, "total_usd": order.total_usd,
            "status": order.status}


@router.get("/orders")
def list_orders(user: CurrentUser = Depends(require_permission("landing.manage")),
                db: Session = Depends(get_db)):
    """订单列表：超管看全平台，owner 看本团队，operator 只看自己下的。"""
    from ..models.domain_shop import DomainOrder
    q = db.query(DomainOrder)
    if not getattr(user, "is_superadmin", False):
        if getattr(user, "role", "") == "operator":
            q = q.filter(DomainOrder.tenant_id == user.tenant_id,
                         DomainOrder.created_by == user.id)
        else:
            q = q.filter(DomainOrder.tenant_id == user.tenant_id)
    rows = q.order_by(DomainOrder.id.desc()).limit(100).all()
    return [{"id": r.id, "domain": r.domain, "years": r.years, "cost_usd": r.cost_usd,
             "fee_usd": r.fee_usd, "total_usd": r.total_usd, "status": r.status,
             "error": r.error, "created_at": str(r.created_at or "")[:16]} for r in rows]


@router.post("/orders/{oid}/cancel")
def cancel_order(oid: int, user: CurrentUser = Depends(require_permission("landing.manage")),
                 db: Session = Depends(get_db)):
    """取消（仅 pending_payment 可取消；下单人或超管）。"""
    from ..models.domain_shop import DomainOrder
    o = db.query(DomainOrder).filter(DomainOrder.id == oid).first()
    if not o:
        raise HTTPException(404, "订单不存在")
    if not getattr(user, "is_superadmin", False) and o.created_by != user.id:
        from ..core.deps import require_owned
        require_owned(user, o, attr="created_by")
    if o.status != "pending_payment":
        raise HTTPException(400, "仅待付款订单可取消")
    o.status = "cancelled"
    db.commit()
    return {"ok": True, "status": o.status}


@router.post("/orders/{oid}/approve")
def approve_order(oid: int, user: CurrentUser = Depends(require_superadmin),
                  db: Session = Depends(get_db)):
    """超管确认收款 → 自动注册链：Porkbun 注册（NS 直指 CF）→ CF 建 zone → 入域名库。
    Porkbun 未配置：订单转 approved 并提示（等配置后重跑本端点续链）。"""
    from ..models.domain_shop import DomainOrder
    o = db.query(DomainOrder).filter(DomainOrder.id == oid).first()
    if not o:
        raise HTTPException(404, "订单不存在")
    if o.status not in ("pending_payment", "approved"):
        raise HTTPException(400, f"状态 {o.status} 不可批准")
    if not _reg_ready(db):
        o.status = "approved"
        o.approved_by, o.approved_at = user.id, datetime.now(timezone.utc)
        db.commit()
        reg = _reg_name(db).upper()
        raise HTTPException(400, f"{reg}_NOT_CONFIGURED_ORDER_APPROVED")
    o.status = "registering"
    o.approved_by, o.approved_at = user.id, datetime.now(timezone.utc)
    db.commit()
    return _fulfill(o, user, db)


def _fulfill(o, user, db) -> dict:
    """注册链（register→CF zone→入库）。失败置 failed 留 error，可重试（approve 重入）。"""
    from ..core.cf_client import CfClient
    try:
        if not (settings.cf_api_token and settings.cf_account_id):
            raise RuntimeError("CF_API_NOT_CONFIGURED")
        cf = CfClient(settings.cf_api_token, settings.cf_account_id)
        # ① CF 先建 zone（拿到分配的 NS 对）
        zone = cf.create_zone(o.domain)
        ns = zone.get("name_servers") or []
        # ② 注册商注册并把 NS 指到 CF——注册生效后 zone 自动转 active。
        #    Dynadot register 不带 NS 参数：注册→set_ns 两步（客户端内已限速 1.1s）。
        if _reg_name(db) == "dynadot":
            dyna = DynadotClient(settings.dynadot_api_key)
            dyna.register(o.domain, o.years)
            dyna.set_ns(o.domain, ns)
        else:
            pb = PorkbunClient(settings.porkbun_api_key, settings.porkbun_secret_key)
            pb.register(o.domain, o.years, ns=ns)
        # ③ 入域名库（团队立即可建落地页）
        exists = db.query(LandingDomain).filter(
            LandingDomain.tenant_id == o.tenant_id, LandingDomain.domain == o.domain).first()
        if not exists:
            db.add(LandingDomain(tenant_id=o.tenant_id, created_by=o.created_by,
                                 domain=o.domain, source="purchased",
                                 cf_zone_status="pending", note=f"代购订单 #{o.id}"))
        o.status, o.cf_zone_id = "bound", zone.get("id")
        o.fulfilled_at = datetime.now(timezone.utc)
        db.commit()
        write_log(db, tenant_id=o.tenant_id, trace_id=new_trace_id(), actor_type="user",
                  actor_user_id=user.id, target_type="domain_order", target_id=str(o.id),
                  action_type="approve", source="domain_shop", result="success",
                  trigger_detail=f"{o.domain} 注册成功 NS={'/'.join(ns)}")
        db.commit()
        from ..core.notify_utils import emit_notification
        emit_notification(db, tenant_id=o.tenant_id, level="info",
                          event_type="domain_order_fulfilled", trace_id=new_trace_id(),
                          title=f"域名 {o.domain} 已交付",
                          body=f"注册成功并已接入 Cloudflare（NS 已自动指向）。"
                               f"现在可以在落地页中使用该域名。")
        db.commit()
        return {"ok": True, "status": "bound", "domain": o.domain, "name_servers": ns}
    except Exception as e:
        db.rollback()
        o.status, o.error = "failed", str(e)[:300]
        db.commit()
        raise HTTPException(500, f"注册链失败（可重试批准）: {str(e)[:150]}")
