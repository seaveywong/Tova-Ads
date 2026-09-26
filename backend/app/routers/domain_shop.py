"""域名商店路由（批DD 预埋 2026-09-19；同日切 Dynadot 主力）：查价/下单/批准→自动注册→自动接入 CF。

状态机：pending_payment（等付款；钱包上线后自动冻结扣，当前=超管人工确认收款）
  → approved（超管确认）→ 注册链（registering→registered→bound） / failed（原因入库）
全自动链 = 注册商注册（NS 指向 CF）→ CF 建 zone → 入 landing_domains（source=purchased）
→ 团队立即可在其下建落地页子域。注册商由 system_settings['domain_registrar'] 选（dynadot|porkbun），
未配置：查价/批准返回明确引导，订单可先建。
计费预埋：手续费 system_settings['domain_shop_fee_usd']（默认 5），钱包上线后换 pricing_rules。
"""
import json
import re
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..core.config import settings
from ..core.database import get_db, SuperSessionLocal
from ..core.deps import CurrentUser, require_permission, require_superadmin
from ..core.log_utils import write_log, new_trace_id
from ..core.porkbun_client import PorkbunClient, porkbun_configured
from ..core.dynadot_client import DynadotClient, DynadotError
from ..core.porkbun_client import PorkbunError
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


def _dynadot_key() -> str:
    """.env 实时读优先（保存 key 的落点永远最新）→ 进程内 settings 兜底（本地无 .env）。
    曾 settings 优先：4 worker 各自内存里存着首次保存的旧密钥，非空旧值永远压过
    .env 新值——换 key 后部分 worker 仍用旧 key 报 invalid key（2026-09-24 实证）。"""
    from ..core.config import env_val
    return env_val("DYNADOT_API_KEY") or settings.dynadot_api_key


def _dynadot_secret() -> str:
    """REST v2 密钥对之 Secret（同 key 的 .env 优先口径；敏感端点签名用）。"""
    from ..core.config import env_val
    return env_val("DYNADOT_API_SECRET") or settings.dynadot_api_secret


def _reg_ready(db) -> bool:
    if _reg_name(db) == "dynadot":
        return bool(_dynadot_key())
    return porkbun_configured(settings)


def _registrar_client(db):
    """按选择返回注册商客户端；未配置 400 引导。"""
    if _reg_name(db) == "dynadot":
        if not _dynadot_key():
            raise HTTPException(400, "DYNADOT_NOT_CONFIGURED")
        return DynadotClient(_dynadot_key(), _dynadot_secret())
    if not porkbun_configured(settings):
        raise HTTPException(400, "PORKBUN_NOT_CONFIGURED")
    return PorkbunClient(settings.porkbun_api_key, settings.porkbun_secret_key)


def _pricing(client, db) -> dict:
    """{tld: {registration, renewal}}（10min 缓存；两注册商客户端已统一此形状）。
    缓存按注册商分键（扫描修 #4）：切换注册商后旧表 10min 内误计价。"""
    import time as _t
    now = _t.time()
    reg = _reg_name(db)
    if (not _PRICING_CACHE or _PRICING_CACHE.get("reg") != reg
            or now - _PRICING_CACHE["at"] > _PRICING_TTL):
        try:
            _PRICING_CACHE["pricing"] = client.pricing()
        except (DynadotError, PorkbunError) as e:
            # 复审 #7：曾冒泡 500（_avail 400 化时漏了定价表这条同型路径）
            raise HTTPException(400, f"注册商价格表拉取失败：{str(e)[:150]}")
        _PRICING_CACHE["at"] = now
        _PRICING_CACHE["reg"] = reg
    return _PRICING_CACHE["pricing"] or {}


def _avail(client, d: str) -> dict:
    """可注册性 + 实时价：Dynadot search 一步到位；Porkbun check。
    注册商错误统一转 400（扫描修 #6：曾冒泡 500——key 无效/限流/SearchError 用户只见服务器错误）。"""
    try:
        if isinstance(client, DynadotClient):
            r = client.search(d)
            return {"available": r["available"], "price": r.get("price_usd")}
        chk = client.check(d)
        return {"available": str(chk.get("porkbunAvailable")) == "yes", "price": None}
    except (DynadotError, PorkbunError) as e:
        raise HTTPException(400, f"注册商查询失败：{str(e)[:150]}")


def _fee_rules(db) -> dict:
    """手续费规则（2026-09-24 规则化）：system_settings['domain_shop_fee_rules'] JSON
    {mode: fixed|percent, fixed, rate, floor}。percent 模式 = max(floor, rate%×成本)
    （便宜域走保底统一价、贵域按比例——一条公式覆盖两种运营诉求）。
    旧键 domain_shop_fee_usd（纯数字）= fixed 模式兼容读取。"""
    from ..models.system import SystemSetting
    row = db.query(SystemSetting).filter(SystemSetting.key == "domain_shop_fee_rules").first()
    if row and row.value:
        try:
            r = json.loads(row.value)
            if r.get("mode") in ("fixed", "percent"):
                return {"mode": r["mode"], "fixed": float(r.get("fixed") or _DEFAULT_FEE),
                        "rate": float(r.get("rate") or 5), "floor": float(r.get("floor") or 1)}
        except Exception:
            pass
    old = db.query(SystemSetting).filter(SystemSetting.key == _FEE_KEY).first()
    try:
        fx = float(old.value) if old else _DEFAULT_FEE
    except (TypeError, ValueError):
        fx = _DEFAULT_FEE
    return {"mode": "fixed", "fixed": fx, "rate": 5, "floor": 1}


def _fee_for(db, cost: float) -> float:
    """按规则算单笔手续费（费用计算唯一入口——以后加阶梯/封顶都在这改）。"""
    r = _fee_rules(db)
    if r["mode"] == "percent":
        return round(max(r["floor"], r["rate"] * float(cost or 0) / 100.0), 2)
    return round(r["fixed"], 2)


def _parse_exp(v):
    """注册商到期值解析（毫秒/秒时间戳或 ISO 串）→ datetime(UTC)；失败返 None。"""
    if v in (None, "", 0, "0"):
        return None
    try:
        if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):
            ms = int(v)
            if ms > 1e12:
                ms /= 1000.0
            return datetime.fromtimestamp(ms, tz=timezone.utc)
        s = str(v)
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _payment_info(db) -> dict:
    """收款信息（USDT）：system_settings['payment_usdt'] {chain, address, addresses[]}。
    addresses = 收款地址池（2026-09-26：订单按 id 轮询分池地址——分散链上资金流+防串单）。
    配了地址才返回非空——订单页展示打款目标，超管核对收款有据。"""
    from ..models.system import SystemSetting
    row = db.query(SystemSetting).filter(SystemSetting.key == "payment_usdt").first()
    out = {"method": "usdt", "chain": "", "address": "", "addresses": [], "pay_note": ""}
    if row and row.value:
        try:
            j = json.loads(row.value)
            out["chain"] = str(j.get("chain") or "")[:20]
            out["address"] = str(j.get("address") or "")[:120]
            out["pay_note"] = str(j.get("pay_note") or "")[:200]
            pool = j.get("addresses")
            if isinstance(pool, list):
                out["addresses"] = [str(a).strip()[:120] for a in pool if str(a).strip()][:50]
        except Exception:
            pass
    if out["address"] and out["address"] not in out["addresses"]:
        out["addresses"] = [out["address"]] + out["addresses"]
    return out if out["address"] else {"method": "usdt", "chain": "", "address": "", "addresses": [], "pay_note": ""}


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
    price = _pricing(client, db).get(tld) or {}
    av = _avail(client, d)
    # Dynadot search 自带实时价（premium 域与表价不同），有则优先；tld_price 表可能分页不全
    # （缺的 TLD 不再误报「暂不支持」——search 价兜底，续费价缺则前端显 —）
    cost = av.get("price") if av.get("price") is not None else price.get("registration")
    if cost is None:
        raise HTTPException(400, f"暂不支持 .{tld} 后缀")
    fee = _fee_for(db, cost)
    return {"domain": d, "available": av["available"], "tld": tld,
            "cost_usd": cost, "fee_usd": fee, "total_usd": round(cost + fee, 2),
            "renewal_usd": price.get("renewal")}


# ── 域名候选推送（2026-09-24 域名商店重做）：指定/智能/随机 三模式批量生成候选，
#    Dynadot search_many 一次查 50 个可注册性+实时价，价格段过滤后按价排序推送 ──
_DEFAULT_TLDS = ["com", "net", "xyz", "top", "online", "site", "shop", "store",
                 "icu", "cfd", "link", "fun", "rest", "world", "live", "click"]
_SMART_HEAD = ["", "get", "the", "go", "try", "my"]
_SMART_TAIL = ["", "shop", "store", "app", "site", "hq", "hub", "now", "pro",
               "vip", "labs", "web", "offer", "deal", "go", "bay"]
# 随机模式的品牌词库（短、好读、无歧义；两词组合成品牌感域名）
_RAND_WORDS = [
    "nova", "flex", "pine", "jade", "echo", "apex", "orbit", "vivid", "zen", "flux",
    "halo", "kite", "lunar", "mint", "onyx", "pixel", "quill", "raven", "sage",
    "surge", "terra", "vega", "warp", "amber", "bolt", "cove", "drift", "ember",
    "frost", "gleam", "haven", "iris", "luxe", "mesa", "oak", "prism", "quest",
    "ridge", "sol", "tide", "vale", "wisp", "zenith", "lumen", "cascade", "delta",
    "forge", "grove", "harbor", "indigo", "junction", "krypton", "lotus", "meteor",
]


def _suggest_candidates(q: str, mode: str, tlds: list) -> list:
    """生成候选域名（去重、label 合法、cap 48——Dynadot search 一次查完）。"""
    import random as _rand
    raw = (q or "").strip().lower()
    if "." in raw:            # 输入完整域名 → 抽词根
        raw = raw.rsplit(".", 1)[0]
    root = re.sub(r"[^a-z0-9]", "", raw)[:24]
    tlds = [t for t in tlds if re.match(r"^[a-z]{2,10}$", t)][:12] or _DEFAULT_TLDS[:8]
    cands: list = []

    def _add(name: str):
        if 1 <= len(name) <= 40 and re.match(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$", name):
            cands.append(f"{name}.{t}")

    if mode == "random":
        rng = _rand.Random()
        seen = set()
        while len(cands) < 48 and len(seen) < 400:
            t = rng.choice(tlds)
            if root and rng.random() < 0.4:
                name = root + rng.choice(_RAND_WORDS)
            else:
                name = rng.choice(_RAND_WORDS) + rng.choice(_RAND_WORDS)
            if name in seen:
                continue
            seen.add(name)
            _add(name)
        return cands
    if mode == "exact":
        for t in tlds:
            _add(root)
        return cands
    # 模糊（2026-09-26 用户拍板：选购域名必须支持模糊搜索）：词根本体 → 词库包含匹配
    # （输 oak 出 oakwood/oakland）→ 拼写容错（相邻重复字母折叠 oakk→oak）→ 修饰组合补量
    rng = _rand.Random()
    roots = [root]
    folded = re.sub(r"(.)\1+", r"\1", root)
    if len(folded) >= 3 and folded != root:
        roots.append(folded)
    _seen = set()

    def _try_name(name: str) -> bool:
        """加入候选（name×全部选中 TLD 一次进，_seen 防跨来源重名）。返 True=已达 cap。"""
        if (name in _seen or not (1 <= len(name) <= 40)
                or not re.match(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$", name)):
            return len(cands) >= 48
        _seen.add(name)
        for t in tlds:
            cands.append(f"{name}.{t}")
        return len(cands) >= 48

    for rt in roots:                       # ① 搜什么先看到什么（词根本体+折叠容错变体）
        if _try_name(rt):
            return cands
    from ..core.domain_words import WORDS
    contains = [w for w in WORDS if any(rt in w and w != rt for rt in roots)]
    rng.shuffle(contains)
    for w in contains[:24]:                # ② 词库包含匹配（模糊核心）
        if _try_name(w):
            return cands
    combos = [(h, tl) for h in _SMART_HEAD for tl in _SMART_TAIL]
    rng.shuffle(combos)
    for h, tl in combos:                   # ③ 前后缀修饰组合补量
        if _try_name(f"{h}{root}{tl}"):
            return cands
    return cands


@router.get("/suggest")
def suggest_domains(q: str = "", mode: str = "smart", tlds: str = "",
                    price_min: float = 0.0, price_max: float = 0.0, limit: int = 30,
                    user: CurrentUser = Depends(require_permission("landing.manage")),
                    db: Session = Depends(get_db)):
    """域名候选推送：mode=exact（词根×选中后缀）/ smart（**模糊**——词根本体+内置词库
    包含匹配+拼写容错+修饰组合）/ random（品牌词库随机，q 可作种子）。**价格取官方价目表
    （tld_price，10min 缓存）——0 API 秒回**；可注册性不做实时批量核验（Dynadot search
    实测一次只收一个域名，逐个查 48 候选=53s 限流灾难），下单时 /check+create_order
    单域名实时校验兜底。live_check=false 标记：列表价=价目表价，实时价/premium 以下单核验为准。"""
    if mode not in ("exact", "smart", "random"):
        raise HTTPException(400, "mode 必须是 exact/smart/random")
    if not (1 <= limit <= 50):
        raise HTTPException(400, "limit 1-50")
    if mode != "random" and not re.sub(r"[^a-z0-9]", "", (q or "").lower().rsplit(".", 1)[0]):
        raise HTTPException(400, "请输入品牌词（例：mybrand）")
    tld_list = [t.strip().lstrip(".").lower() for t in (tlds or "").split(",") if t.strip()]
    client = _registrar_client(db)
    pricing = _pricing(client, db)
    cands = _suggest_candidates(q, mode, tld_list)
    out = []
    for d in cands:
        tld = d.rsplit(".", 1)[-1]
        cost = (pricing.get(tld) or {}).get("registration")
        if cost is None:
            continue          # 价目表没有的 TLD 不推（下单也会拒）
        if price_min and cost < price_min:
            continue
        if price_max and cost > price_max:
            continue
        fee = _fee_for(db, cost)
        out.append({"domain": d, "tld": tld, "cost_usd": cost,
                    "fee_usd": fee, "total_usd": round(cost + fee, 2)})
    out.sort(key=lambda x: (x["cost_usd"], len(x["domain"])))
    return {"results": out[:limit], "searched": len(cands), "taken": 0,
            "live_check": False}


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
    price = _pricing(client, db).get(tld) or {}
    av = _avail(client, d)
    if not av["available"]:
        raise HTTPException(400, "该域名不可注册（已被占用或不支持）")
    unit = av.get("price") if av.get("price") is not None else price.get("registration")
    if unit is None:
        raise HTTPException(400, f"暂不支持 .{tld} 后缀")
    cost = round(unit * body.years, 2)
    fee = _fee_for(db, cost)
    from ..models.system import SystemSetting  # noqa: F401（表已 import 路径一致）
    from ..models.domain_shop import DomainOrder
    order = DomainOrder(tenant_id=user.tenant_id, created_by=user.id, domain=d,
                        years=body.years, cost_usd=cost, fee_usd=fee,
                        total_usd=round(cost + fee, 2), status="pending_payment")
    db.add(order)
    db.flush()   # 拿 order.id —— 地址池按 id 轮询分配
    pool = _payment_info(db).get("addresses") or []
    if pool:
        order.payment_address = pool[(order.id - 1) % len(pool)]   # 稳定轮询：相邻订单不同地址
    db.commit()
    # 钱包余额充足 → 直接扣款+全自动注册（免转账免确认）；不足回落 USDT 直付。
    # 注册失败自动原路退回余额（订单置 failed 留人工重试，重试时重新扣款）
    from ..core.wallet import wallet_balance, wallet_apply, InsufficientBalance
    if wallet_balance(db, user.tenant_id) >= order.total_usd - 0.005:
        try:
            wallet_apply(db, user.tenant_id, "charge", -round(order.total_usd, 2),
                         ref_type="domain_order", ref_id=order.id, user_id=user.id,
                         note=f"{d} x{body.years}y")
            order.payment_method = "wallet"
            order.approved_by, order.approved_at = user.id, datetime.now(timezone.utc)
            db.commit()
            write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
                      actor_user_id=user.id, target_type="domain_order", target_id=str(order.id),
                      action_type="create", source="domain_shop", result="success",
                      trigger_detail=f"{d} x{body.years}y wallet-charge total={order.total_usd}")
            db.commit()
            from ..services.usdt_monitor import pay_amount_for  # noqa: F401（返回结构一致）
            if not _reg_ready(db):
                order.status = "approved"
                db.commit()
                return {"id": order.id, "domain": d, "years": body.years, "total_usd": order.total_usd,
                        "status": order.status, "payment_method": "wallet",
                        "pending_registrar": True, "registrar": _reg_name(db).upper(),
                        "payment": _payment_info(db)}
            order.status = "registering"
            db.commit()
            try:
                _fulfill(order, user, db)
                return {"id": order.id, "domain": d, "years": body.years, "total_usd": order.total_usd,
                        "status": order.status, "payment_method": "wallet",
                        "payment": _payment_info(db)}
            except Exception as fe:
                detail = str(getattr(fe, "detail", None) or fe)[:200]
                wallet_apply(db, user.tenant_id, "refund", round(order.total_usd, 2),
                             ref_type="domain_order_refund", ref_id=order.id, user_id=user.id,
                             note=f"{d} 注册失败自动退回：{detail[:80]}")
                raise HTTPException(500, f"已从余额扣款但注册失败，款项已退回余额。原因：{detail[:150]}（订单保留可重试）")
        except InsufficientBalance:
            pass   # 并发把余额扣完——订单入库时已是 pending_payment，走下方 USDT 直付返回
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, target_type="domain_order", target_id=str(order.id),
              action_type="create", source="domain_shop", result="success",
              trigger_detail=f"{d} x{body.years}y total={order.total_usd}")
    db.commit()
    from ..services.usdt_monitor import pay_amount_for
    return {"id": order.id, "domain": d, "years": body.years, "total_usd": order.total_usd,
            "status": order.status, "payment_method": order.payment_method,
            "pay_amount": pay_amount_for(order.total_usd, order.id),
            "payment": _payment_info(db)}


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
    from ..services.usdt_monitor import pay_amount_for
    from ..models.auth import Tenant, User
    # 复审 P2：曾每次全表扫 User/Tenant；改只查本页订单涉及的 id（订单已 limit 100）。
    tids = {r.tenant_id for r in rows}
    uids = {r.created_by for r in rows if r.created_by}
    tmap = {t.id: t.name for t in db.query(Tenant).filter(Tenant.id.in_(tids)).all()} if tids else {}
    umap = {u.id: (u.email or "") for u in db.query(User).filter(User.id.in_(uids)).all()} if uids else {}
    return {"orders": [{"id": r.id, "domain": r.domain, "years": r.years, "cost_usd": r.cost_usd,
                        "fee_usd": r.fee_usd, "total_usd": r.total_usd, "status": r.status,
                        "team": tmap.get(r.tenant_id, ""), "created_by_name": umap.get(r.created_by, ""),
                        "payment_method": r.payment_method or "usdt",
                        "pay_amount": pay_amount_for(r.total_usd, r.id),
                        "payment_address": r.payment_address or "",
                        "payment_txid": r.payment_txid or "", "paid_amount": r.paid_amount,
                        "error": r.error, "created_at": str(r.created_at or "")[:16]} for r in rows],
            "payment": _payment_info(db)}


@router.post("/orders/{oid}/cancel")
def cancel_order(oid: int, user: CurrentUser = Depends(require_permission("landing.manage")),
                 db: Session = Depends(get_db)):
    """取消（仅 pending_payment 可取消；下单人或超管）。"""
    from ..models.domain_shop import DomainOrder
    o = db.query(DomainOrder).filter(DomainOrder.id == oid).first()
    if not o:
        raise HTTPException(404, "订单不存在")
    # 越租户闸（2026-09-26 权限审计）：require_owned 只拦 operator 不校验租户——
    # owner 曾可凭他团队订单 ID 直调 API 越租户取消
    if not getattr(user, "is_superadmin", False) and o.tenant_id != user.tenant_id:
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
    if o.status not in ("pending_payment", "approved", "payment_detected", "failed"):
        raise HTTPException(400, f"状态 {o.status} 不可批准")
    if not _reg_ready(db):
        o.status = "approved"
        o.approved_by, o.approved_at = user.id, datetime.now(timezone.utc)
        db.commit()
        reg = _reg_name(db).upper()
        # 复审 P2：曾 400 + 副作用（订单已悄悄转 approved、前端却弹报错）。改 200 明确告知
        # 「已确认收款、待注册商配置后重试续链」——状态与提示一致，不再误导超管。
        return {"ok": True, "status": "approved", "domain": o.domain,
                "pending_registrar": True, "registrar": reg}
    o.status = "registering"
    o.approved_by, o.approved_at = user.id, datetime.now(timezone.utc)
    db.commit()
    return _fulfill(o, user, db)


def _fulfill(o, user, db) -> dict:
    """交付链。kind=register（注册→CF zone→入库）/ kind=renew（0108 续费：只 renew+顺延到期，
    不建 zone 不动 NS）。失败置 failed 留 error，可重试（approve 重入）。"""
    from ..core.cf_client import CfClient
    try:
        if (getattr(o, "kind", None) or "register") == "renew":
            # 续费分支：域名已在库（不建 zone / 不动 NS / 不重复入库）
            row = db.query(LandingDomain).filter(
                LandingDomain.tenant_id == o.tenant_id,
                LandingDomain.domain == o.domain).first()
            reg = _reg_name(db)
            if reg == "dynadot":
                r = DynadotClient(_dynadot_key(), _dynadot_secret()).renew(o.domain, o.years) or {}
            else:
                r = PorkbunClient(settings.porkbun_api_key, settings.porkbun_secret_key) \
                    .renew(o.domain, o.years) or {}
            base = (row.expires_at if row and row.expires_at
                    and row.expires_at > datetime.now(timezone.utc)
                    else datetime.now(timezone.utc))
            exp = _parse_exp(r.get("expiration_date")) or (base + timedelta(days=365 * o.years))
            if row:
                row.registrar = row.registrar or reg
                row.expires_at = exp
                row.last_renewed_at = datetime.now(timezone.utc)
                row.last_notice_tier = None
            o.status, o.fulfilled_at = "bound", datetime.now(timezone.utc)
            db.commit()
            write_log(db, tenant_id=o.tenant_id, trace_id=new_trace_id(), actor_type="user",
                      actor_user_id=user.id, target_type="domain_order", target_id=str(o.id),
                      action_type="renew", source="domain_shop", result="success",
                      trigger_detail=f"{o.domain} 续费 {o.years}y → {str(exp)[:10]}")
            db.commit()
            from ..core.notify_utils import emit_notification
            emit_notification(db, tenant_id=o.tenant_id, level="info",
                              event_type="domain_renewed", trace_id=new_trace_id(),
                              title=f"域名 {o.domain} 已续费 {o.years} 年",
                              body=f"新到期日 {str(exp)[:10]}。")
            db.commit()
            return {"ok": True, "status": "bound", "domain": o.domain, "expires_at": str(exp)[:10]}
        if not (settings.cf_api_token and settings.cf_account_id):
            raise RuntimeError("CF_API_NOT_CONFIGURED")
        cf = CfClient(settings.cf_api_token, settings.cf_account_id)
        # ① CF 先建 zone（拿到分配的 NS 对）
        zone = cf.create_zone(o.domain)
        ns = zone.get("name_servers") or []
        # ② 注册商注册并把 NS 指到 CF——注册生效后 zone 自动转 active。
        #    Dynadot register 不带 NS 参数：注册→set_ns 两步（客户端内已限速 1.1s）。
        reg = _reg_name(db)
        if reg == "dynadot":
            dyna = DynadotClient(_dynadot_key(), _dynadot_secret())
            r = dyna.register(o.domain, o.years)
            dyna.set_ns(o.domain, ns)
        else:
            pb = PorkbunClient(settings.porkbun_api_key, settings.porkbun_secret_key)
            r = pb.register(o.domain, o.years, ns=ns) or {}
        # ③ 入域名库（团队立即可建落地页）+ 到期日（0108：注册响应 expiration_date 毫秒，
        #    解析不到按 365×年近似，每日同步 cron 对齐纠正）
        exists = db.query(LandingDomain).filter(
            LandingDomain.tenant_id == o.tenant_id, LandingDomain.domain == o.domain).first()
        if not exists:
            exists = LandingDomain(tenant_id=o.tenant_id, created_by=o.created_by,
                                   domain=o.domain, source="purchased",
                                   cf_zone_status="pending", note=f"代购订单 #{o.id}")
            db.add(exists)
        exists.registrar = reg
        exists.expires_at = _parse_exp((r or {}).get("expiration_date")) or \
            (datetime.now(timezone.utc) + timedelta(days=365 * o.years))
        exists.last_renewed_at = datetime.now(timezone.utc)
        exists.last_notice_tier = None
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


# ── 域名续费与生命周期（0108 批2：手动续费双通道 + 自动续费开关）──
class RenewIn(BaseModel):
    years: int = 1


@router.get("/domains/{did}/renew-quote")
def renew_quote(did: int, years: int = 1,
                user: CurrentUser = Depends(require_permission("landing.manage")),
                db: Session = Depends(get_db)):
    """续费询价（弹窗展示：续费单价×年 + 手续费 = 总价；单一总价口径同购买）。"""
    from ..models.landing_lib import LandingDomain as _LD
    row = db.query(_LD).filter(_LD.id == did).first()
    if not row or row.tenant_id != user.tenant_id:
        raise HTTPException(404, "域名不存在")
    years = max(1, min(10, years))
    client = _registrar_client(db)
    tld = row.domain.rsplit(".", 1)[-1]
    unit = (_pricing(client, db).get(tld) or {}).get("renewal")
    if unit is None:
        raise HTTPException(400, f"暂不支持 .{tld} 续费（价目表缺价）")
    cost = round(unit * years, 2)
    fee = _fee_for(db, cost)
    from ..core.wallet import wallet_balance
    return {"domain": row.domain, "years": years, "unit": unit, "cost_usd": cost,
            "fee_usd": fee, "total_usd": round(cost + fee, 2),
            "expires_at": str(row.expires_at)[:10] if row.expires_at else "",
            "balance_usd": wallet_balance(db, user.tenant_id)}


@router.post("/domains/{did}/renew")
def renew_domain(did: int, body: RenewIn,
                 user: CurrentUser = Depends(require_permission("landing.manage")),
                 db: Session = Depends(get_db)):
    """手动续费（双通道，用户拍板 2026-09-27）：余额够 → 扣款+renew 即时完成；
    不够 → 创建 kind=renew 订单走 USDT 直付（到账自动续费，同注册全自动口径）。
    可续窗口：到期 ≤90 天或已过期（宽限期内）。自有域名（external）不支持。"""
    from ..models.landing_lib import LandingDomain as _LD
    row = db.query(_LD).filter(_LD.id == did).first()
    if not row or row.tenant_id != user.tenant_id:
        raise HTTPException(404, "域名不存在")
    if not row.registrar or row.registrar == "external":
        raise HTTPException(400, "自有域名请在原注册商侧续费（平台仅管理代购域名）")
    if body.years < 1 or body.years > 10:
        raise HTTPException(400, "年限 1-10")
    if row.expires_at:
        from datetime import date as _d
        days = (row.expires_at.date() - _d.today()).days
        if days > 90:
            raise HTTPException(400, f"距到期还有 {days} 天（超过 90 天暂不可续）")
    client = _registrar_client(db)
    tld = row.domain.rsplit(".", 1)[-1]
    unit = (_pricing(client, db).get(tld) or {}).get("renewal")
    if unit is None:
        raise HTTPException(400, f"暂不支持 .{tld} 续费（价目表缺价）")
    cost = round(unit * body.years, 2)
    fee = _fee_for(db, cost)
    total = round(cost + fee, 2)
    # 通道一：钱包余额（优先）
    from ..core.wallet import wallet_balance, wallet_apply, InsufficientBalance
    if wallet_balance(db, user.tenant_id) >= total - 0.005:
        try:
            wallet_apply(db, user.tenant_id, "charge", -total,
                         ref_type="domain_renew_manual", ref_id=row.id, user_id=user.id,
                         note=f"{row.domain} 手动续费 {body.years}y")
        except InsufficientBalance:
            pass
        else:
            reg = _reg_name(db)
            try:
                if reg == "dynadot":
                    r = DynadotClient(_dynadot_key(), _dynadot_secret()).renew(row.domain, body.years) or {}
                else:
                    r = PorkbunClient(settings.porkbun_api_key, settings.porkbun_secret_key) \
                        .renew(row.domain, body.years) or {}
                base = row.expires_at if (row.expires_at and row.expires_at > datetime.now(timezone.utc)) \
                    else datetime.now(timezone.utc)
                row.expires_at = _parse_exp(r.get("expiration_date")) or (base + timedelta(days=365 * body.years))
                row.last_renewed_at = datetime.now(timezone.utc)
                row.last_notice_tier = None
                db.commit()
            except Exception as e:
                db.rollback()
                wallet_apply(db, user.tenant_id, "refund", total,
                             ref_type="domain_renew_manual_refund", ref_id=row.id, user_id=user.id,
                             note=f"{row.domain} 续费失败退回")
                raise HTTPException(500, f"已扣款但续费失败，款项已退回余额：{str(e)[:150]}")
            from ..core.notify_utils import emit_notification
            from ..core.log_utils import new_trace_id as _ntid
            emit_notification(db, tenant_id=user.tenant_id, level="info",
                              event_type="domain_renewed", trace_id=_ntid(),
                              title=f"域名 {row.domain} 已续费 {body.years} 年",
                              body=f"扣款 ${total:.2f}，新到期日 {str(row.expires_at)[:10]}。")
            db.commit()
            return {"ok": True, "paid_by": "wallet", "total_usd": total,
                    "expires_at": str(row.expires_at)[:10]}
    # 通道二：USDT 直付订单（kind=renew，到账监听自动续费——_fulfill renew 分支）
    order = DomainOrder(tenant_id=user.tenant_id, created_by=user.id, kind="renew",
                        domain=row.domain, years=body.years, cost_usd=cost, fee_usd=fee,
                        total_usd=total, status="pending_payment")
    db.add(order)
    db.flush()
    pool = _payment_info(db).get("addresses") or []
    if pool:
        order.payment_address = pool[(order.id - 1) % len(pool)]
    db.commit()
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, target_type="domain_order", target_id=str(order.id),
              action_type="renew", source="domain_shop", result="success",
              trigger_detail=f"{row.domain} 续费单 x{body.years}y total={total} (usdt)")
    db.commit()
    return {"ok": True, "paid_by": "usdt", "order_id": order.id, "total_usd": total,
            "pay_amount": pay_amount_for(total, order.id)}


class AutoRenewIn(BaseModel):
    on: bool


@router.post("/domains/{did}/auto-renew")
def set_auto_renew(did: int, body: AutoRenewIn,
                   user: CurrentUser = Depends(require_permission("landing.manage")),
                   db: Session = Depends(get_db)):
    """自动续费开关（默认开；到期前 14/3 天余额足则自动扣款续费，不足只提醒不垫付）。"""
    from ..models.landing_lib import LandingDomain as _LD
    row = db.query(_LD).filter(_LD.id == did).first()
    if not row or row.tenant_id != user.tenant_id:
        raise HTTPException(404, "域名不存在")
    row.auto_renew = bool(body.on)
    db.commit()
    return {"ok": True, "auto_renew": row.auto_renew}
