"""FB token 解析 helper（多 token 一致性，2026-07 清扫债）。

统一"为某个操作选哪个 token"的逻辑，避免各 router 各自 .first() 随机选：
- 账户特定操作（铺广告/dashboard/账户 insights）→ client_for_account：按 accounts.fb_credential_id 选。
- 聚合操作（列资产/导入）→ iter_tenant_clients：遍历所有 active token。
- token 无关操作（兴趣搜索）→ first_client：任一 active。
"""
from typing import Optional
from sqlalchemy.orm import Session
from .encryption import decrypt
from .fb_client import FbClient
from ..models.fb import FbCredential, Account


def iter_tenant_clients(db: Session, tenant_id: int) -> list[tuple[FbCredential, FbClient]]:
    """租户的所有 active token → [(cred, FbClient), ...]。聚合操作用（合并多 token 的资产）。"""
    creds = db.query(FbCredential).filter(
        FbCredential.tenant_id == tenant_id, FbCredential.status == "active"
    ).all()
    return [(c, FbClient(decrypt(c.access_token_enc))) for c in creds]


def first_client(db: Session, tenant_id: int) -> Optional[FbClient]:
    """任一 active token（token 无关操作，如兴趣搜索）。无则 None。"""
    creds = db.query(FbCredential).filter(
        FbCredential.tenant_id == tenant_id, FbCredential.status == "active"
    ).order_by(FbCredential.id).all()
    if not creds:
        return None
    return FbClient(decrypt(creds[0].access_token_enc))


def _is_cred_available(c) -> bool:
    """cred 可用：active + 不在冷却期。学习 1.0 交接包 §3.4（限流冷却）。"""
    if c.status != "active":
        return False
    if c.cooldown_until:
        from datetime import datetime, timezone
        if c.cooldown_until > datetime.now(timezone.utc):
            return False  # 冷却中
    return True


# RR 轮转游标（进程内；多 worker 各自近似均衡，巡检单调度内一致）
_RR_STATE: dict = {}  # {(tenant_id, act_id, op_kind): cursor}


def _op_ok(c, op_kind: str) -> bool:
    """token 是否满足操作类型。

    以 FB 实际 scopes 为准（permission_snapshot），token_type 标签仅作 fallback。
    - read: 任意 token 都行
    - pause/write: 需 ads_management scope（FB ground truth），或 token_type 为 manage/operate
    """
    if op_kind == "read":
        return True
    if op_kind in ("pause", "write"):
        # 优先看 FB 实际权限（ground truth）
        import json as _json
        snap = {}
        try:
            raw = c.permission_snapshot
            snap = _json.loads(raw) if isinstance(raw, str) else (raw or {})
        except Exception:
            pass
        scopes = snap.get("scopes") or []
        if "ads_management" in scopes:
            return True
        # fallback: 看 token_type 标签（清引号）
        tt = (c.token_type or "").strip().strip("'\"").lower() or "manage"
        return tt in ("manage", "operate")
    return True


def cred_for_account_op(db: Session, tenant_id: int, act_id: str,
                        op_kind: str = "read") -> Optional[FbCredential]:
    """选满足 op_kind 的可用 cred（绑定优先 + RR 兜底 + cooldown）。

    巡检/操作用（要 cred 写 cooldown / 审计）。op_kind: read/pause/write。
    """
    acc = db.query(Account).filter(
        Account.tenant_id == tenant_id, Account.act_id == act_id,
    ).first()
    creds = db.query(FbCredential).filter(
        FbCredential.tenant_id == tenant_id,
    ).all()
    if not creds:
        return None
    cred_map = {c.id: c for c in creds}
    if acc and acc.fb_credential_id and acc.fb_credential_id in cred_map:
        bound = cred_map[acc.fb_credential_id]
        if _is_cred_available(bound) and _op_ok(bound, op_kind):
            return bound
    avail = [c for c in creds if _is_cred_available(c) and _op_ok(c, op_kind)]
    if not avail:
        return None
    key = (tenant_id, act_id, op_kind)
    cursor = _RR_STATE.get(key, 0)
    pick = avail[cursor % len(avail)]
    _RR_STATE[key] = cursor + 1
    return pick


def client_for_account(db: Session, tenant_id: int, act_id: str,
                       op_kind: str = "read") -> Optional[FbClient]:
    """按账户选 client（绑定优先 + RR 兜底）。op_kind: read 任意可用 / pause 管理+操作 / write 操作。"""
    cred = cred_for_account_op(db, tenant_id, act_id, op_kind)
    return FbClient(decrypt(cred.access_token_enc)) if cred else None


def mark_cred_cooldown(db: Session, cred_id: int, minutes: int = 30,
                       status: str = "rate_limited") -> None:
    """标记 cred 冷却（巡检/操作遇限流时调，下轮 client_for_account 自动跳过）。"""
    from datetime import datetime, timezone, timedelta
    c = db.query(FbCredential).filter(FbCredential.id == cred_id).first()
    if c:
        c.status = status
        c.cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=minutes)


def cred_for_account(db: Session, tenant_id: int, act_id: str) -> Optional[FbCredential]:
    """账户绑定的 cred 对象（写 accounts.fb_credential_id / 审计用）。"""
    acc = db.query(Account).filter(
        Account.tenant_id == tenant_id, Account.act_id == act_id,
    ).first()
    creds = db.query(FbCredential).filter(
        FbCredential.tenant_id == tenant_id, FbCredential.status == "active"
    ).all()
    cred_map = {c.id: c for c in creds}
    if acc and acc.fb_credential_id and acc.fb_credential_id in cred_map:
        return cred_map[acc.fb_credential_id]
    return creds[0] if creds else None


def reassociate_orphan_accounts(db: Session, tenant_id: int) -> dict:
    """重绑孤儿账户（fb_credential_id 失效/空）→ 覆盖它的 active cred。

    1.0 教训的 2.0 版：删/换 token 后账户变孤儿 → 读不到/操作不了。
    本函数拉每个 active cred 的 adaccounts，把孤儿账户重绑到覆盖它的 cred。
    token-add 时 + 定时（watchdog）调，实现自愈。返回 {checked, rebound}。
    """
    creds = db.query(FbCredential).filter(
        FbCredential.tenant_id == tenant_id, FbCredential.status == "active"
    ).all()
    if not creds:
        return {"checked": 0, "rebound": 0}
    # 建 account_id(裸数字) -> cred_id 覆盖图
    act_to_cred: dict[str, int] = {}
    for c in creds:
        try:
            fb = FbClient(decrypt(c.access_token_enc))
            for a in fb.get_ad_accounts():
                aid = a.get("account_id")
                if aid and aid not in act_to_cred:
                    act_to_cred[aid] = c.id
        except Exception:
            continue  # 单 cred 读失败不阻断
    active_ids = {c.id for c in creds}
    orphans = db.query(Account).filter(
        Account.tenant_id == tenant_id,
        (Account.fb_credential_id.is_(None)) | (Account.fb_credential_id.notin_(active_ids)),
    ).all()
    rebound = 0
    still_orphan: list[dict] = []
    for acc in orphans:
        cid = act_to_cred.get(acc.act_id)  # accounts.act_id 存裸数字
        if cid and cid != acc.fb_credential_id:
            acc.fb_credential_id = cid
            rebound += 1
        elif not cid:
            # 无任何 active cred 覆盖 → 真孤儿（所有令牌对该账户全失效）
            still_orphan.append({"act_id": acc.act_id, "name": acc.name})
    if rebound:
        db.commit()
    return {"checked": len(orphans), "rebound": rebound,
            "active_creds": len(creds), "covered_acts": len(act_to_cred),
            "still_orphan": still_orphan}


def run_with_fallback(db: Session, tenant_id: int, act_id: str, op_fn):
    """token fallback 执行器（照搬 1.0 _run_with_token_fallback 思路）。

    op_fn(fb) -> result。按"账户绑定的 token 优先"排序，遇 token_expired/permissions
    错误轮换其他 active token；全失败抛最后一个错。返回 (result, used_cred)。
    只对【读操作 / 幂等操作】用——写操作（建广告）若中途换 token 会产生孤儿对象，应绑死 token + 失败告警。
    """
    creds = db.query(FbCredential).filter(
        FbCredential.tenant_id == tenant_id, FbCredential.status == "active"
    ).order_by(FbCredential.id).all()
    if not creds:
        return None, None
    acc = db.query(Account).filter(
        Account.tenant_id == tenant_id, Account.act_id == act_id,
    ).first()
    bound_id = acc.fb_credential_id if acc else None
    # 绑定 token 优先
    ordered = sorted(creds, key=lambda c: 0 if c.id == bound_id else 1)
    last_err = None
    for cred in ordered:
        fb = FbClient(decrypt(cred.access_token_enc))
        try:
            return op_fn(fb), cred
        except Exception as e:
            from .fb_client import FbApiError
            last_err = e
            # 仅 token/权限类错误才轮换；其余（参数错等）直接抛
            if isinstance(e, FbApiError) and e.category in ("token_expired", "permissions",
                                                              "permission_denied") and len(ordered) > 1:
                continue
            raise
    raise last_err
