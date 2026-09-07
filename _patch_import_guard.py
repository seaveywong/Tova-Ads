import io
edits = []
p = "backend/app/routers/fb.py"
s = io.open(p, encoding="utf-8").read()

old1 = '''    if not cleaned:
        return {"imported": [], "count": 0, "skipped_existing": 0,
                "not_found": [], "total": 0}'''
new1 = old1 + '''
    if len(cleaned) > 200:
        raise HTTPException(400, f"单批最多导入 200 个账户（收到 {len(cleaned)}）——请分批（导入保护）")'''
assert old1 in s, "batch cap"
s = s.replace(old1, new1, 1); edits.append("batch cap 200")

old2 = '''    imported: list[str] = []
    skipped_existing = 0
    covered: set = set()
    touched_creds: set = set()
    for aid in cleaned:'''
new2 = '''    imported: list[str] = []
    skipped_existing = 0
    covered: set = set()
    touched_creds: set = set()
    skipped_over_limit: list[str] = []
    # 令牌级绑定上限（0087 导入保护）：预取覆盖令牌的现有绑定数与 max_accounts——
    # operate 默认 100（防一个操作号带几千账户炸巡检/同步），超额令牌不再接收新绑定
    _cand_cred_ids = {t["id"] for row in rows.values() for t in (row.get("tokens") or [])}
    _cred_max: dict = {}
    _cred_bound: dict = {}
    if _cand_cred_ids:
        from sqlalchemy import func as _fn
        for c in db.query(FbCredential).filter(FbCredential.id.in_(_cand_cred_ids)).all():
            _cred_max[c.id] = c.max_accounts
        for r2 in db.query(AccountFbCredential.fb_credential_id, _fn.count(AccountFbCredential.id)).filter(
            AccountFbCredential.tenant_id == user.tenant_id,
            AccountFbCredential.fb_credential_id.in_(_cand_cred_ids),
            AccountFbCredential.status == "active",
        ).group_by(AccountFbCredential.fb_credential_id).all():
            _cred_bound[r2[0]] = int(r2[1])

    def _cred_slot_ok(cred_id) -> bool:
        _mx = _cred_max.get(cred_id)
        return _mx is None or _cred_bound.get(cred_id, 0) < int(_mx)

    def _cred_slot_take(cred_id):
        _cred_bound[cred_id] = _cred_bound.get(cred_id, 0) + 1

    for aid in cleaned:'''
assert old2 in s, "preload"
s = s.replace(old2, new2, 1); edits.append("cred limit preload")

old3 = '''        tokens = row.get("tokens") or []
        if not tokens:
            continue
        cred_id = tokens[0]["id"]
        touched_creds.add(cred_id)'''
new3 = '''        tokens = row.get("tokens") or []
        if not tokens:
            continue
        # 上限内选第一个可用覆盖令牌；全超额 → 跳过（明细返回，不报错）
        _pick = next((t["id"] for t in tokens if _cred_slot_ok(t["id"])), None)
        if _pick is None:
            skipped_over_limit.append(aid)
            covered.add(aid)   # 有覆盖但全超额——不算 not_found
            continue
        cred_id = _pick
        _cred_slot_take(cred_id)
        touched_creds.add(cred_id)'''
assert old3 in s, "pick"
s = s.replace(old3, new3, 1); edits.append("cred limit pick")

old4 = '''    not_found = sorted(set(cleaned) - covered)
    return {"imported": imported, "count": len(imported),
            "skipped_existing": skipped_existing,
            "not_found": not_found, "total": len(cleaned)}'''
new4 = '''    not_found = sorted(set(cleaned) - covered)
    return {"imported": imported, "count": len(imported),
            "skipped_existing": skipped_existing,
            "skipped_over_limit": skipped_over_limit,
            "not_found": not_found, "total": len(cleaned)}'''
assert old4 in s, "return"
s = s.replace(old4, new4, 1); edits.append("return over_limit")

old5 = '@router.put("/credentials/{cred_id}/token-type")'
new5 = '''class MaxAccountsIn(BaseModel):
    max_accounts: int | None = None  # None=不限


@router.put("/credentials/{cred_id}/max-accounts")
def set_max_accounts(cred_id: int, body: MaxAccountsIn,
                     user: CurrentUser = Depends(require_permission("ads.create")),
                     db: Session = Depends(get_db)):
    """令牌级账户绑定上限（导入保护 0087）。null=不限；operate 型建议 ≤100（令牌抽屉可改）。"""
    cred = db.query(FbCredential).filter(
        FbCredential.tenant_id == user.tenant_id, FbCredential.id == cred_id).first()
    if not cred:
        raise HTTPException(404, "令牌不存在")
    v = body.max_accounts
    if v is not None and (v < 1 or v > 10000):
        raise HTTPException(400, "max_accounts 需在 1-10000 或 null（不限）")
    cred.max_accounts = v
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, target_type="fb_credential", target_id=str(cred_id),
              action_type="set_max_accounts", source="user", result="success",
              metadata={"max_accounts": v})
    db.commit()
    return {"id": cred_id, "max_accounts": v}


@router.put("/credentials/{cred_id}/token-type")'''
assert old5 in s, "endpoint"
s = s.replace(old5, new5, 1); edits.append("max-accounts endpoint")

old6 = '"last_verified_at": str(c.last_verified_at) if c.last_verified_at else None,'
assert old6 in s
s = s.replace(old6, old6 + '\n        "max_accounts": c.max_accounts,', 1)
edits.append("dict expose")

io.open(p, "w", encoding="utf-8", newline="\n").write(s)
print("fb.py:", edits)
