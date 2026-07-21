"""备份路由（doc 11 运维）：pg_dump → 本地 gzip + 管理员触发/列表。

v1：本地存储（/opt/toveads/backups/，保留 30 天）；R2 推送 v2。
超管专用。
"""
import os, subprocess
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from ..core.deps import require_superadmin
from ..core.database import SuperSessionLocal, settings

router = APIRouter(prefix="/admin/backup", tags=["backup"])

BACKUP_DIR = os.environ.get("BACKUP_DIR", "/opt/toveads/backups")


def _extract_pg_parts(url: str) -> dict:
    """从 postgresql://user:pass@host:port/db 提取部件。"""
    import re
    m = re.match(r"postgresql(?:\+psycopg2)?://([^:]+):([^@]+)@([^:/]+)(?::(\d+))?/(.+)", url or "")
    if not m:
        return {}
    return {"user": m[1], "pass": m[2], "host": m[3], "port": m[4], "db": m[5]}


@router.post("")
def trigger_backup(user=Depends(require_superadmin)):
    """触发 pg_dump 备份（超管）。"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    parts = _extract_pg_parts(settings.database_super_url)
    if not parts:
        raise HTTPException(500, "无法解析数据库连接串")
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    outfile = os.path.join(BACKUP_DIR, f"toveads_{ts}.sql.gz")
    env = {**os.environ, "PGPASSWORD": parts["pass"]}
    try:
        result = subprocess.run(
            ["pg_dump", "-U", parts["user"], "-h", parts["host"], "-p", parts["port"],
             parts["db"], "--no-owner", "--no-privileges"],
            capture_output=True, timeout=300, env=env,
        )
        if result.returncode != 0:
            raise HTTPException(500, f"pg_dump 失败: {result.stderr.decode()[:300]}")
        import gzip
        with gzip.open(outfile, "wb") as f:
            f.write(result.stdout)
    except subprocess.TimeoutExpired:
        raise HTTPException(500, "pg_dump 超时（300s）")
    # 清理 30 天前
    try:
        import time
        now = time.time()
        for fn in os.listdir(BACKUP_DIR):
            fp = os.path.join(BACKUP_DIR, fn)
            if fn.startswith("toveads_") and os.path.isfile(fp) and (now - os.path.getmtime(fp)) > 30 * 86400:
                os.remove(fp)
    except Exception:
        pass
    size = os.path.getsize(outfile) if os.path.exists(outfile) else 0
    return {"ok": True, "file": os.path.basename(outfile), "size_bytes": size}


@router.get("")
def list_backups(user=Depends(require_superadmin)):
    """列已有备份。"""
    if not os.path.isdir(BACKUP_DIR):
        return {"backups": []}
    backups = []
    for fn in sorted(os.listdir(BACKUP_DIR), reverse=True):
        if fn.startswith("toveads_") and fn.endswith(".sql.gz"):
            fp = os.path.join(BACKUP_DIR, fn)
            backups.append({"file": fn, "size_bytes": os.path.getsize(fp),
                            "modified": datetime.fromtimestamp(os.path.getmtime(fp), tz=timezone.utc).isoformat()})
    return {"backups": backups}
