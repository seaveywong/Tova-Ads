# 自动提取 2.0 架构事实：表/路由/cron/迁移 → ARCHITECTURE 素材
import os, re, json, sys

ROOT = os.path.join(os.path.dirname(__file__), "backend", "app")
out = {"tables": [], "routes": [], "crons": [], "i18n_notify": 0}

# 1) 表（models/*.py 的 __tablename__ + 列）
for fn in sorted(os.listdir(os.path.join(ROOT, "models"))):
    if not fn.endswith(".py") or fn.startswith("__"):
        continue
    src = open(os.path.join(ROOT, "models", fn), encoding="utf-8").read()
    for m in re.finditer(r'class (\w+)\(Base\).*?__tablename__\s*=\s*"(\w+)"(.*?)(?=\nclass |\Z)', src, re.S):
        cls, tbl, body = m.group(1), m.group(2), m.group(3)
        cols = re.findall(r'^\s{4}(\w+)\s*=\s*Column', body, re.M)
        out["tables"].append({"model": cls, "table": tbl, "cols": len(cols), "file": fn})

# 2) 路由（routers/*.py）
for fn in sorted(os.listdir(os.path.join(ROOT, "routers"))):
    if not fn.endswith(".py") or fn.startswith("__"):
        continue
    src = open(os.path.join(ROOT, "routers", fn), encoding="utf-8").read()
    # router prefix（含挂载链变量）
    prefix = ""
    pm = re.search(r'APIRouter\(prefix="([^"]*)"', src)
    if pm:
        prefix = pm.group(1)
    for m in re.finditer(r'@router\.(get|post|put|delete|patch)\(\s*"([^"]*)"', src):
        out["routes"].append({"file": fn, "method": m.group(1).upper(), "path": (prefix + m.group(2)) or "/"})

# 3) cron（main.py scheduler add_job）
src = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
for m in re.finditer(r'_scheduler\.add_job\(\s*([\w\.]+)\s*,\s*[^,]+,\s*(?:kwargs=\{[^}]*\},\s*)?(?:id="([^"]*)",\s*)?[^\)]*?(?:minutes=(\d+)|cron)', src):
    out["crons"].append({"func": m.group(1), "id": m.group(2) or "", "frag": m.group(0)[:120]})

print("== TABLES ==")
for t in out["tables"]:
    print(f"{t['file']:<22} {t['table']:<28} {t['model']:<24} cols={t['cols']}")
print(f"total tables: {len(out['tables'])}")
print("\n== ROUTES ==")
for r in out["routes"]:
    print(f"{r['file']:<24} {r['method']:<7} {r['path']}")
print(f"total routes: {len(out['routes'])}")
print("\n== CRON JOBS (main.py) ==")
for c in out["crons"]:
    print(f"{c['func']:<45} {c['frag']}")
