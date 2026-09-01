"""素材库孤儿文件清理：ASSET_DIR 中不被任何 Asset.storage_key 引用的文件。

存储布局（2026-09-02 核实）：
- ASSET_DIR（默认 /opt/toveads/assets）是扁平目录，只存素材上传文件：
  storage_key = uuid4().hex + 白名单扩展名，无子目录。
  写入口只有 assets.py 的 upload；guard_engine（保活）/ launch_templates（部署）
  只按 Asset.storage_key 读；main.py 把目录挂 /static-assets 只读对外。
  落地页 worker/模板等其他模块不写此目录 → 目录不混用，可整目录做孤儿判定。
- 引用集必须跨租户取全量：storage_key 是全局唯一 uuid，但 RLS 会话只看到
  本租户行，直接用会把别的租户文件误判成孤儿 → 调用方须传 SuperSessionLocal 会话。

删除安全闸（delete_orphans）：
- 只接受明确的文件名列表（调用方显式确认），绝不做"全目录清空"；
- 文件名必须是纯 basename（拒绝路径分隔符 / ../ 穿越）；
- 删除前重新实时计算引用集与孤儿集合，只删仍在当前孤儿集合里的文件
  （防列表展示后、删除前有并发上传复用了该名字）。
"""
import os
import re
import time
from datetime import datetime, timezone

# 上传 storage_key 形状：32 位 hex + 白名单扩展名（assets.py upload 的生成规则）
_KEY_RE = re.compile(r"^[0-9a-f]{32}\.[a-z0-9]{1,5}$")

# 文件落盘 → Asset 行 commit 之间有竞态窗口：太新的文件先不当孤儿（下轮再清）
_MIN_AGE_SEC = 600


def _asset_dir() -> str:
    return os.environ.get("ASSET_DIR", "/opt/toveads/assets")


def referenced_storage_keys(db) -> set:
    """全租户 Asset.storage_key 集合（必须用 BYPASSRLS 会话查）。"""
    from ..models.launch import Asset
    return {row[0] for row in db.query(Asset.storage_key).all() if row[0]}


def scan_orphans(db, min_age_sec: int = _MIN_AGE_SEC) -> list:
    """列出目录中无 DB 行引用的文件。只列不删。

    返回 [{filename, size, mtime(UTC ISO), pattern_ok}]，按 mtime 升序。
    pattern_ok=False 表示文件名不符合上传 key 规则（人工放进目录的东西），
    仍会列出但由调用方决定是否删。
    """
    root = _asset_dir()
    referenced = referenced_storage_keys(db)
    now = time.time()
    try:
        names = os.listdir(root)
    except (FileNotFoundError, NotADirectoryError):
        return []
    out = []
    for name in names:
        path = os.path.join(root, name)
        if name in referenced:
            continue
        try:
            st = os.stat(path)
        except OSError:
            continue
        if not os.path.isfile(path) or os.path.islink(path):
            continue
        if now - st.st_mtime < min_age_sec:
            continue
        out.append({
            "filename": name,
            "size": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            "pattern_ok": bool(_KEY_RE.match(name)),
        })
    out.sort(key=lambda x: x["mtime"])
    return out


def delete_orphans(db, filenames: list) -> dict:
    """删除指定孤儿文件。安全闸见模块 docstring。"""
    root = _asset_dir()
    wanted = []
    for f in filenames or []:
        if isinstance(f, str) and f and os.path.basename(f) == f and f not in wanted:
            wanted.append(f)
    current = {o["filename"] for o in scan_orphans(db)}
    deleted, skipped, freed = [], [], 0
    for name in wanted:
        path = os.path.join(root, name)
        if name not in current:
            skipped.append({"filename": name, "reason": "not_orphan_or_missing"})
            continue
        try:
            freed += os.path.getsize(path)
            os.remove(path)
            deleted.append(name)
        except OSError as e:
            skipped.append({"filename": name, "reason": f"os_error:{getattr(e, 'errno', '?')}"})
    return {"deleted": deleted, "skipped": skipped, "freed_bytes": freed, "count": len(deleted)}
