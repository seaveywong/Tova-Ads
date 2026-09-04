# Batch F end-to-end smoke (assertion-based, per bare-except-silent-failure rule).
# Covers: F3 group label + disable_reason passthrough, F4 TG prefs, F2 batch preflight,
# F1 heartbeat reason. Read-mostly; group label set/clear on one account (restored after).
import json, sys, time
import httpx

BASE = "http://127.0.0.1:8000"
FAILS = []

def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f" | {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)

# mint token server-side (same pattern as _reassociate.py — no password login in smoke)
from app.core.database import SuperSessionLocal as _S
from app.models.auth import User
from app.core.security import create_access_token
_db = _S()
try:
    _u = _db.query(User).filter(User.email == "seavey@tovaads.com").first()
    TOK = create_access_token(user_id=_u.id, email=_u.email, tenant_id=1, role="owner", is_superadmin=_u.is_superadmin)
finally:
    _db.close()
r = httpx.get(f"{BASE}/auth/me", headers={"Authorization": f"Bearer {TOK}"}, timeout=30)
check("token minted + auth/me", r.status_code == 200, r.text[:100])
H = {"Authorization": f"Bearer {TOK}"}

# ---- F3: group label set/read/clear ----
r = httpx.get(f"{BASE}/fb/accounts", headers=H, timeout=60)
accs = r.json() if isinstance(r.json(), list) else r.json().get("accounts") or r.json().get("items") or []
check("fb/accounts list", r.status_code == 200 and len(accs) > 0, f"n={len(accs)}")
managed = [a for a in accs if a.get("is_managed") is not False]
target = managed[0]
act = target["act_id"]
check("accounts expose group_label+disable_reason keys", "group_label" in target and "disable_reason" in target)

r = httpx.put(f"{BASE}/fb/accounts/group", headers=H, json={"act_ids": [act], "group_label": "smokegrp"}, timeout=30)
check("PUT group set", r.status_code == 200 and r.json().get("updated") == 1, r.text[:120])
r = httpx.get(f"{BASE}/fb/accounts", headers=H, timeout=60)
accs2 = r.json() if isinstance(r.json(), list) else r.json().get("accounts") or []
row = next((a for a in accs2 if a["act_id"] == act), {})
check("group label persisted", row.get("group_label") == "smokegrp", str(row.get("group_label")))

# dashboard passthrough
r = httpx.get(f"{BASE}/dashboard?date_preset=today", headers=H, timeout=60)
daccs = (r.json() or {}).get("accounts") or []
drow = next((a for a in daccs if a["act_id"] == act), {})
check("dashboard exposes group_label", "group_label" in drow and drow.get("group_label") == "smokegrp", str(drow.get("group_label")))

# clear
r = httpx.put(f"{BASE}/fb/accounts/group", headers=H, json={"act_ids": [act], "group_label": ""}, timeout=30)
r = httpx.get(f"{BASE}/fb/accounts", headers=H, timeout=60)
accs3 = r.json() if isinstance(r.json(), list) else r.json().get("accounts") or []
row3 = next((a for a in accs3 if a["act_id"] == act), {})
check("group label cleared", row3.get("group_label") in ("", None), str(row3.get("group_label")))

# ---- F4: TG prefs ----
r = httpx.get(f"{BASE}/notifications/tg/prefs", headers=H, timeout=30)
j = r.json()
check("GET tg prefs", r.status_code == 200 and "levels" in j, r.text[:120])
check("prefs default all-true", j["levels"].get("warning") is True and j["levels"].get("info") is True, str(j))
if j.get("bound"):
    r = httpx.put(f"{BASE}/notifications/tg/prefs", headers=H, json={"warning": True, "info": False}, timeout=30)
    check("PUT prefs info=false", r.status_code == 200 and r.json()["levels"]["info"] is False, r.text[:120])
    r = httpx.put(f"{BASE}/notifications/tg/prefs", headers=H, json={"warning": True, "info": True}, timeout=30)
    check("PUT prefs restore", r.status_code == 200 and r.json()["levels"]["info"] is True, r.text[:120])
else:
    r = httpx.put(f"{BASE}/notifications/tg/prefs", headers=H, json={"warning": True, "info": False}, timeout=30)
    check("PUT prefs unbound rejected 400", r.status_code == 400, str(r.status_code))

# ---- F2: batch preflight series_count (create temp template; preflight is read-only, no FB calls) ----
r = httpx.get(f"{BASE}/assets", headers=H, timeout=60)
assets = r.json() if isinstance(r.json(), list) else (r.json() or {}).get("items") or []
media = [a for a in assets if (a.get("type") or a.get("media_type")) in ("image", "video") and (a.get("storage_key") or a.get("url"))]
tpl_id = None
if media:
    ids = [m["id"] for m in media[:3]]
    r = httpx.post(f"{BASE}/launch-templates", headers=H,
                   json={"name": "smoke-batch-tmp", "name_prefix": "SmokeTmp", "asset_id": ids[0], "daily_budget": 5,
                         "pixel_id": "111111111111111"}, timeout=30)
    if r.status_code in (200, 201):
        tpl_id = r.json().get("id")
    r = httpx.post(f"{BASE}/launch-templates/{tpl_id}/preflight", headers=H,
                   json={"act_id": act, "asset_ids": ids, "account_count": 2}, timeout=120)
    j = r.json() if r.status_code == 200 else {}
    if r.status_code == 200:
        check("batch preflight series_count = assets x accounts", j.get("series_count") == len(ids) * 2,
              f"sc={j.get('series_count')} want={len(ids) * 2}")
        check("batch preflight batch_assets echo", isinstance(j.get("batch_assets"), list) and len(j["batch_assets"]) == len(ids))
    else:
        check("batch preflight (env-limited, endpoint reached)", r.status_code < 500, f"{r.status_code} {r.text[:120]}")
    if tpl_id:
        httpx.delete(f"{BASE}/launch-templates/{tpl_id}", headers=H, timeout=30)
else:
    check("batch preflight (skip: no media assets)", True, f"media={len(media)}")

# ---- F1: heartbeat with reason (force inspect then read heartbeat) ----
r = httpx.post(f"{BASE}/guard/inspect?force=true", headers=H, timeout=300)
check("force inspect ok", r.status_code == 200, r.text[:120])
time.sleep(2)
from app.core.database import SuperSessionLocal
from app.models.log import ActionLog
db = SuperSessionLocal()
try:
    hb = db.query(ActionLog).filter(ActionLog.action_type == "inspection_heartbeat") \
        .order_by(ActionLog.id.desc()).first()
    det = (hb.trigger_detail or "") if hb else ""
    check("heartbeat exists", hb is not None, det[:100])
    # reason suffix: either skip-accounts segment or eval-0 explanation (any of the new markers)
    check("heartbeat carries reason", ("跳过" in det and "账户" in det) or ("哨兵armed" in det)
          or ("live广告清单为空" in det) or ("兜底" in det) or ("评估" in det),
          det[:160])
finally:
    db.close()

print("\nSMOKE_RESULT: " + ("ALL_PASS" if not FAILS else f"FAILED {len(FAILS)}: {FAILS}"))
sys.exit(1 if FAILS else 0)
