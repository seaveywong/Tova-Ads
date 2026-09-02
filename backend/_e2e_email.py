"""端到端模拟 GET /settings/email-routing 的全部数据源（用户打开邮箱转发 Tab 看到的）。"""
from app.routers.settings import _em_ctx, _em_missing_dns, _addr_verified, _dns_key
from app.core.database import SuperSessionLocal
from app.models.system import EmailRoute

cf, zid, domain = _em_ctx()
print(f"ctx: zid={zid} domain={domain}")

routing = cf.get_email_routing(zid) or {}
raw = routing.get("status") or "unconfigured"
status = "enabled" if raw == "ready" else raw
print(f"路由状态: {status} (raw={raw})")

missing = _em_missing_dns(cf, zid) if status in ("enabled", "disabled") else []
print(f"DNS 缺口: {len(missing)} 条 {[m.get('type') for m in missing]}")

addresses = cf.list_email_addresses(zid)
print(f"目的地邮箱: {len(addresses)} 个 {[(a.get('email'), _addr_verified(a)) for a in addresses]}")

rules = {r.get("id"): r for r in cf.list_email_rules(zid)} if status == "enabled" else {}
print(f"CF 规则: {len(rules)} 条")

db = SuperSessionLocal()
rows = db.query(EmailRoute).order_by(EmailRoute.alias).all()
print(f"本地映射: {len(rows)} 条 {[r.alias for r in rows]}")
db.close()
print("\n✅ 全链路数据源就绪")
