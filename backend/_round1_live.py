"""R1 实测：未验证路径全走一遍（全部可逆/幂等）。"""
from types import SimpleNamespace
from fastapi import HTTPException
from app.routers.settings import (create_email_route, toggle_email_route, delete_email_route,
                                  _em_ctx, _addr_verified, enable_email_routing)
from app.core.database import SuperSessionLocal
from app.models.system import EmailRoute

db = SuperSessionLocal()
user = SimpleNamespace(id=1, tenant_id=1)
cf, zid, domain = _em_ctx()

# A. enable 幂等性（已 enabled 状态下再调一次，验证邮箱令牌能过 enable 端点）
try:
    enable_email_route = None
    import app.routers.settings as S
    r = S.enable_email_routing(user=user, db=db)  # type: ignore[arg-type]
    print(f"A. enable(幂等重调): PASS {r}")
except HTTPException as e:
    print(f"A. enable(幂等重调): HTTP {e.status_code} {str(e.detail)[:120]}")
except Exception as e:
    print(f"A. enable(幂等重调): 异常 {type(e).__name__} {str(e)[:120]}")

# B. "@" 名字的 DNS 写（get_email_dns 兜底记录集用的 name="@"）
try:
    rec = cf.add_dns_record(zid, {"type": "TXT", "name": "@", "content": "smoke-apex-probe", "ttl": 60, "proxied": False})
    print(f"B. apex(@) DNS 写: PASS id={str(rec.get('id'))[:8]}…")
    import httpx
    from app.core.cf_client import CF_API_BASE
    rr = httpx.delete(f"{CF_API_BASE}/zones/{zid}/dns_records/{rec['id']}", headers=cf.headers, timeout=30)
    print(f"B2. 清理: {'PASS' if rr.json().get('success') else 'FAIL'}")
except Exception as e:
    print(f"B. apex(@) DNS 写: FAIL {str(e)[:140]}")

# C. 映射全生命周期：建 → 停 → 启 → 删
addrs = cf.list_email_addresses(zid)
dest = next((a["email"].lower() for a in addrs if _addr_verified(a)), None)
print(f"C. 前置: verified 目的地 = {dest}")
if dest:
    body = SimpleNamespace(alias="r1lifecycle", destination_email=dest, enabled=True)
    try:
        r = create_email_route(body, user=user, db=db)  # type: ignore[arg-type]
        rid = r["id"]
        print(f"C1. 建: PASS {r['alias_email']} cf_enabled={r['cf_enabled']}")
        t1 = toggle_email_route(rid, SimpleNamespace(enabled=False), user=user, db=db)  # type: ignore[arg-type]
        print(f"C2. 停: PASS enabled={t1.get('enabled')} cf={t1.get('cf_enabled')}")
        t2 = toggle_email_route(rid, SimpleNamespace(enabled=True), user=user, db=db)  # type: ignore[arg-type]
        print(f"C3. 启: PASS enabled={t2.get('enabled')} cf={t2.get('cf_enabled')}")
        d = delete_email_route(rid, user=user, db=db)  # type: ignore[arg-type]
        print(f"C4. 删: PASS {d}")
    except HTTPException as e:
        print(f"Cx: HTTP {e.status_code} {str(e.detail)[:150]}")
        row = db.query(EmailRoute).filter(EmailRoute.alias == "r1lifecycle").first()
        if row:
            if row.rule_id:
                try:
                    cf.delete_email_rule(zid, row.rule_id)
                except Exception:
                    pass
            db.delete(row); db.commit()
            print("   已清理残留")
    except Exception as e:
        print(f"Cx: 异常 {type(e).__name__} {str(e)[:150]}")
db.close()
