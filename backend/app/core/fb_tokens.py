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
    """cred 可用：active + 不在冷却期。学习 1.0 交接包 §3.4（限流冷却）。

    rate_limited + 冷却已过 = 可用（自动恢复；否则一次 code-17 令牌永久出池 → 止损静默停摆）。
    """
    if c.status not in ("active", "rate_limited"):
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
    """选满足 op_kind 的可用 cred（多令牌候选池 + priority + RR 轮换 + PAUSE 兜底）。

    优先从 account_fb_credentials 候选池（多令牌同账户）选：
    - 读：RR 轮换（分摊压力）
    - 写/PAUSE：绑死 priority 最高（防孤儿 + FB 一致性）
    回退：accounts.fb_credential_id 主令牌 + 全 tenant RR（向后兼容，候选池空时兜底）。
    """
    from ..models.fb import AccountFbCredential
    acc = db.query(Account).filter(
        Account.tenant_id == tenant_id, Account.act_id == act_id,
    ).first()

    # 优先：account_fb_credentials 候选池（多令牌同账户）
    if acc:
        pool_creds = db.query(FbCredential).join(
            AccountFbCredential, AccountFbCredential.fb_credential_id == FbCredential.id
        ).filter(
            AccountFbCredential.account_id == acc.id,
            AccountFbCredential.status == "active",
            FbCredential.status == "active",
        ).order_by(AccountFbCredential.priority, FbCredential.id).all()
        pool_avail = [c for c in pool_creds if _is_cred_available(c) and _op_ok(c, op_kind)]
        if pool_avail:
            if op_kind in ("write", "pause"):
                return pool_avail[0]  # 写/PAUSE 绑死 priority 最高（防孤儿）
            # 读：RR 轮换（分摊压力）
            key = (tenant_id, act_id, op_kind)
            cursor = _RR_STATE.get(key, 0)
            pick = pool_avail[cursor % len(pool_avail)]
            _RR_STATE[key] = cursor + 1
            return pick

    # 回退：全 tenant FbCredential（向后兼容 + 候选池空时兜底）
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


def _account_write_candidates(db: Session, tenant_id: int, act_id: str,
                              op_kind: str = "write") -> list[FbCredential]:
    """账户的 op_kind 候选令牌，按优先级序（pool → bound → tenant-wide 兜底），去重。
    主页感知选择扫描用（返全序，不止选一个）。"""
    from ..models.fb import AccountFbCredential
    acc = db.query(Account).filter(
        Account.tenant_id == tenant_id, Account.act_id == act_id,
    ).first()
    ordered: list[FbCredential] = []
    seen: set[int] = set()

    def _add(c):
        if c and c.id not in seen and _is_cred_available(c) and _op_ok(c, op_kind):
            ordered.append(c); seen.add(c.id)

    if acc:
        for c in db.query(FbCredential).join(
            AccountFbCredential, AccountFbCredential.fb_credential_id == FbCredential.id
        ).filter(
            AccountFbCredential.account_id == acc.id,
            AccountFbCredential.status == "active",
            FbCredential.status == "active",
        ).order_by(AccountFbCredential.priority, FbCredential.id).all():
            _add(c)
        if acc.fb_credential_id:
            _add(db.query(FbCredential).filter(FbCredential.id == acc.fb_credential_id).first())
    for c in db.query(FbCredential).filter(
        FbCredential.tenant_id == tenant_id, FbCredential.status == "active",
    ).order_by(FbCredential.id).all():
        _add(c)
    return ordered


def cred_for_account_page(db: Session, tenant_id: int, act_id: str, page_id: str,
                          op_kind: str = "write",
                          _cache: Optional[dict] = None) -> Optional[FbCredential]:
    """选同时满足 op_kind 且能管 page_id 的 cred（跟帖 reuse 部署用）。
    扫候选池 priority 序，返第一个 get_page_access_token(page_id)≠空的；无则 None。
    _cache={cred_id:bool} 跨账户复用（多账户共享令牌时只查一次 FB）。"""
    if not page_id:
        return None
    for c in _account_write_candidates(db, tenant_id, act_id, op_kind):
        manages = _cache.get(c.id) if _cache is not None else None
        if manages is None:
            try:
                manages = bool(FbClient(decrypt(c.access_token_enc)).get_page_access_token(page_id))
            except Exception:
                manages = False
            if _cache is not None:
                _cache[c.id] = manages
        if manages:
            return c
    return None


def client_for_account_page(db: Session, tenant_id: int, act_id: str, page_id: str,
                            op_kind: str = "write",
                            _cache: Optional[dict] = None) -> Optional[FbClient]:
    """跟帖 reuse 部署：选能管 page_id 的写令牌 → FbClient。无则 None（调用方报清晰错）。"""
    cred = cred_for_account_page(db, tenant_id, act_id, page_id, op_kind, _cache)
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
    # 建 account_id(裸数字) -> [覆盖它的 cred_id 列表]（多 token 共管：一个账户可被多个 cred 覆盖，
    # 必须收全部覆盖 cred，否则第二个起令牌会被先到的挤掉 → 候选池永远只有 1 个）
    act_to_creds: dict[str, list[int]] = {}
    for c in creds:
        try:
            fb = FbClient(decrypt(c.access_token_enc))
            for a in fb.get_ad_accounts():
                aid = a.get("account_id")
                if aid and c.id not in act_to_creds.setdefault(aid, []):
                    act_to_creds[aid].append(c.id)
        except Exception:
            continue  # 单 cred 读失败不阻断
    active_ids = {c.id for c in creds}
    orphans = db.query(Account).filter(
        Account.tenant_id == tenant_id,
        Account.is_managed == True,  # 只重绑在管账户；is_managed=false（已软删/移出BM）不再当孤儿告警
        (Account.fb_credential_id.is_(None)) | (Account.fb_credential_id.notin_(active_ids)),
    ).all()
    rebound = 0
    still_orphan: list[dict] = []
    for acc in orphans:
        cids = act_to_creds.get(acc.act_id) or []  # accounts.act_id 存裸数字
        cid = cids[0] if cids else None  # 主令牌取覆盖列表第一个
        if cid and cid != acc.fb_credential_id:
            acc.fb_credential_id = cid
            rebound += 1
        elif not cid:
            # 无任何 active cred 覆盖 → 真孤儿（所有令牌对该账户全失效）
            still_orphan.append({"act_id": acc.act_id, "name": acc.name})
    if rebound:
        db.commit()
    # 已导入账户的多 token 共管补链。
    # ⚠ 不为"令牌能管但用户没显式导入"的账户自动建 managed 行（用户明确要求：只导入选中的）。
    # 这些账户仍会出现在「载入账户」列表（loadable-accounts 实时拉 FB）供用户手动导入。
    from ..models.fb import AccountFbCredential
    existing_acts = {a.act_id for a in db.query(Account).filter(
        Account.tenant_id == tenant_id).all()}
    discovered = 0  # 令牌能管但未导入的（不纳管，仅计数）
    new_links = 0
    for aid, cids in act_to_creds.items():
        if aid in existing_acts:
            acc = db.query(Account).filter(
                Account.tenant_id == tenant_id, Account.act_id == aid).first()
            if acc:
                for cid in cids:
                    has_link = db.query(AccountFbCredential).filter(
                        AccountFbCredential.account_id == acc.id,
                        AccountFbCredential.fb_credential_id == cid,
                    ).first()
                    if not has_link:
                        db.add(AccountFbCredential(
                            tenant_id=tenant_id, account_id=acc.id,
                            fb_credential_id=cid, priority=0, status="active",
                        ))
                        new_links += 1
        else:
            discovered += 1  # 不自动纳管
    if new_links:
        db.commit()
    return {"checked": len(orphans), "rebound": rebound,
            "active_creds": len(creds), "covered_acts": len(act_to_creds),
            "still_orphan": still_orphan,
            "new_discovered": discovered, "new_links": new_links}


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
