"""角色 → 功能键映射。

v1: 3 固定角色硬编码（permissions.py）。
v2 (2026-07-20): roles 表（租户自定义角色 + 权限矩阵）。
DB 查不到角色时（兼容）退回硬编码默认。
"""
import logging
logger = logging.getLogger("toveads.auth")

# 硬编码兜底（roles 表不存在 / 角色没找到时用）
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "owner": {
        "ads.create", "ads.read", "ads.pause", "ads.resume", "ads.update", "ads.delete",
        "rules.create", "rules.edit", "rules.read",
        "landing.manage", "assets.manage",
        "billing.view", "billing.manage",
        "members.invite", "members.manage", "audit.read",
    },
    "operator": {
        "ads.create", "ads.read", "ads.pause", "ads.resume", "ads.update", "ads.delete",
        "rules.create", "rules.edit", "rules.read",
        "landing.manage", "assets.manage",
    },
    "finance": {
        "billing.view", "ads.read",
    },
}

# 所有合法权限 key（供前端渲染权限矩阵 + 后端校验）
ALL_PERMISSIONS = sorted({
    "ads.create", "ads.read", "ads.pause", "ads.resume", "ads.update", "ads.delete",
    "rules.create", "rules.edit", "rules.read",
    "landing.manage", "assets.manage",
    "billing.view", "billing.manage",
    "members.invite", "members.manage", "audit.read",
})

# 权限分组（前端渲染用）
PERMISSION_GROUPS = [
    {"label": "广告管理", "keys": ["ads.read", "ads.create", "ads.pause", "ads.resume", "ads.update", "ads.delete"]},
    {"label": "规则引擎", "keys": ["rules.read", "rules.create", "rules.edit"]},
    {"label": "落地页", "keys": ["landing.manage"]},
    {"label": "素材库", "keys": ["assets.manage"]},
    {"label": "账单", "keys": ["billing.view", "billing.manage"]},
    {"label": "成员管理", "keys": ["members.invite", "members.manage"]},
    {"label": "审计日志", "keys": ["audit.read"]},
]


def permissions_for_role(db, tenant_id: int, role_name: str) -> set[str]:
    """查角色的权限集（DB 优先，硬编码兜底）。"""
    try:
        from ..models.auth import Role
        import json
        row = db.query(Role).filter(
            Role.tenant_id == tenant_id, Role.name == role_name
        ).first()
        if row and row.permissions:
            perms = row.permissions
            if isinstance(perms, str):
                import json as _j
                perms = _j.loads(perms)
            return set(perms)
    except Exception as e:
        logger.debug(f"[RBAC] DB 查角色失败，退回硬编码: {e}")
    # 兜底
    return ROLE_PERMISSIONS.get(role_name, set())


def permissions_for(role: str) -> set[str]:
    """硬编码兜底（JWT 解析时用——无 DB 上下文）。"""
    if not role:
        return set()
    return ROLE_PERMISSIONS.get(role, set())
