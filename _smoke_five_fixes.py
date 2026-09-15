# 五修 smoke（断言式）：zone健康门 / 自检CF归因 / 团队彻底删除e2e / bind_errors字段
import json, httpx

BASE = "http://127.0.0.1:8000"
FAILS = []
def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f" | {detail}" if detail else ""))
    if not cond: FAILS.append(name)

from app.core.database import SuperSessionLocal as _S
from app.models.auth import User
from app.core.security import create_access_token

# 拿「拥有 marketbriefnow.xyz 的租户」的 owner 用户（zone 门要过域名库白名单才轮得到测）
_db = _S()
try:
    row = _db.execute(__import__("sqlalchemy").text(
        "SELECT u.id, u.email, m.tenant_id, m.role, u.is_superadmin FROM users u "
        "JOIN tenant_memberships m ON m.user_id = u.id AND m.role = 'owner' "
        "JOIN landing_domains d ON d.tenant_id = m.tenant_id "
        "WHERE d.domain = 'marketbriefnow.xyz' LIMIT 1")).fetchone()
    check("found owner user of marketbriefnow tenant", row is not None, str(row))
    UID, UEMAIL, UTID, UROLE, USUP = row
    TOK = create_access_token(user_id=UID, email=UEMAIL, tenant_id=UTID, role=UROLE, is_superadmin=USUP)
finally:
    _db.close()
H = {"Authorization": f"Bearer {TOK}"}
r = httpx.get(f"{BASE}/auth/me", headers=H, timeout=30)
check("token ok", r.status_code == 200, r.text[:80])

# ── 1) 发布 zone 健康门：marketbriefnow.xyz(moved) → 400 可行动文案 ──
r = httpx.post(f"{BASE}/landing/publish", headers=H, timeout=60, json={
    "title": "smoke-zone-gate-test", "custom_domains": ["marketbriefnow.xyz"],
    "target_urls": ["https://example.com"], "block_enabled": False,
})
check("zone gate 400", r.status_code == 400, f"{r.status_code} {r.text[:100]}")
check("zone gate message actionable", "解析状态异常" in r.text and ("moved" in r.text or "NS" in r.text), r.text[:150])
# 幽灵 draft 行应已被清（发布失败回滚删 draft）
_db = _S()
try:
    n = _db.execute(__import__("sqlalchemy").text(
        "SELECT count(*) FROM landing_pages WHERE title='smoke-zone-gate-test'")).fetchone()[0]
    check("ghost draft cleaned", n == 0, f"count={n}")
finally:
    _db.close()

# ── 2) 自检 CF 归因：page 57 域名/Worker fail 时 detail 带根域 zone=moved ──
_db = _S()
try:
    p57 = _db.execute(__import__("sqlalchemy").text(
        "SELECT id, tenant_id FROM landing_pages WHERE custom_domain='https://lp57.marketbriefnow.xyz'")).fetchone()
finally:
    _db.close()
if p57 and p57[1] == UTID:
    r = httpx.get(f"{BASE}/landing/pages/{p57[0]}/health", headers=H, timeout=120)
    ok = r.status_code == 200
    dom = next((c for c in (r.json().get("checks") or []) if c.get("key") == "domain"), None)
    wk = next((c for c in (r.json().get("checks") or []) if c.get("key") == "worker"), None)
    check("health 200", ok, r.text[:80])
    check("domain check carries CF diag", dom is not None and "moved" in (dom.get("detail") or ""), str(dom)[:160])
    check("worker check carries CF diag", wk is not None and "moved" in (wk.get("detail") or ""), str(wk)[:160])
else:
    print("SKIP health diag (page57 tenant mismatch)")

# ── 3) 团队彻底删除 e2e：建临时团队 → 塞一行带 tenant_id 的数据 → 删 → 验证级联干净 ──
r = httpx.post(f"{BASE}/admin/tenants", headers=H, timeout=30, json={"name": "smoke-del-team"})
# 建团队可能要 superadmin —— 若 403 就直接用 DB 建一条 tenant 行
from sqlalchemy import text as _t
_db = _S()
try:
    if r.status_code == 200:
        tid = r.json().get("id")
    else:
        _db.execute(_t("INSERT INTO tenants (name, plan, status) VALUES ('smoke-del-team','free','active') RETURNING id"))
        tid = _db.execute(_t("SELECT id FROM tenants WHERE name='smoke-del-team'")).fetchone()[0]
        _db.commit()
        print(f"(built tenant via DB: {tid}, create-api {r.status_code})")
    # 塞数据：成员+一条通知（幂等：成员已存在则跳过）
    m_exists = _db.execute(_t("SELECT count(*) FROM tenant_memberships WHERE tenant_id=:t AND user_id=:u"),
                           {"t": tid, "u": UID}).fetchone()[0]
    if not m_exists:
        _db.execute(_t("INSERT INTO tenant_memberships (tenant_id, user_id, role) VALUES (:t, :u, 'owner')"), {"t": tid, "u": UID})
    _db.execute(_t("INSERT INTO notifications (tenant_id, user_id, level, event_type, title, body) "
                   "VALUES (:t, :u, 'info', 'system', 's', 's')"), {"t": tid, "u": UID})
    _db.commit()
    r = httpx.delete(f"{BASE}/admin/tenants/{tid}", headers=H, timeout=120)
    check("hard delete 200", r.status_code == 200, f"{r.status_code} {r.text[:150]}")
    body = r.json()
    check("hard delete returns tables_cleaned", bool(body.get("tables_cleaned")), str(body.get("tables_cleaned"))[:120])
    check("tenant_memberships cleaned", (body.get("tables_cleaned") or {}).get("tenant_memberships", 0) >= 1)
    check("notifications cleaned", (body.get("tables_cleaned") or {}).get("notifications", 0) >= 1)
    # DB 复核：tenant 行没了 + 两张表无残留
    gone = _db.execute(_t("SELECT count(*) FROM tenants WHERE id=:t"), {"t": tid}).fetchone()[0]
    m_left = _db.execute(_t("SELECT count(*) FROM tenant_memberships WHERE tenant_id=:t"), {"t": tid}).fetchone()[0]
    n_left = _db.execute(_t("SELECT count(*) FROM notifications WHERE tenant_id=:t"), {"t": tid}).fetchone()[0]
    check("tenant row gone + no residue", gone == 0 and m_left == 0 and n_left == 0,
          f"tenant={gone} memb={m_left} notif={n_left} skipped={body.get('tables_skipped')}")
finally:
    _db.close()

print("\n" + ("ALL PASS" if not FAILS else f"FAILED: {FAILS}"))
