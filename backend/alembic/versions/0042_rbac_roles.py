"""RBAC: roles 表（租户自定义角色 + 权限矩阵）

Revision ID: 0042
Revises: 0041
"""
from alembic import op
import json

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None

# 16 个权限 key（模块化）
_ALL_PERMS = {
    "ads.create", "ads.read", "ads.pause", "ads.resume", "ads.update", "ads.delete",
    "rules.create", "rules.edit", "rules.read",
    "landing.manage", "assets.manage",
    "billing.view", "billing.manage",
    "members.invite", "members.manage", "audit.read",
}
_OWNER = _ALL_PERMS
_OPERATOR = {
    "ads.create", "ads.read", "ads.pause", "ads.resume", "ads.update", "ads.delete",
    "rules.create", "rules.edit", "rules.read",
    "landing.manage", "assets.manage",
}
_FINANCE = {"billing.view", "ads.read"}


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS roles (
            id BIGSERIAL PRIMARY KEY,
            tenant_id BIGINT NOT NULL REFERENCES tenants(id),
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            permissions JSONB NOT NULL DEFAULT '[]',
            is_system BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now(),
            UNIQUE(tenant_id, name)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_roles_tenant ON roles (tenant_id)")
    # GRANT（同其他业务表——建表迁移务必带 GRANT，参 0011）
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON roles TO toveads_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON roles TO toveads_super")
    op.execute("GRANT USAGE, SELECT ON roles_id_seq TO toveads_app")
    op.execute("GRANT USAGE, SELECT ON roles_id_seq TO toveads_super")

    # 种默认角色到每个现有租户
    from sqlalchemy import text as _text
    conn = op.get_bind()
    tenants = conn.execute(_text("SELECT id FROM tenants")).fetchall()
    for (tid,) in tenants:
        for name, perms, desc, is_sys in [
            ("owner",      sorted(_OWNER),     "全部权限（不可删除）", True),
            ("operator",   sorted(_OPERATOR),  "广告+规则+落地页（日常操作）", True),
            ("finance",    sorted(_FINANCE),   "只读看板+账单", True),
        ]:
            conn.execute(_text(
                "INSERT INTO roles (tenant_id, name, description, permissions, is_system) "
                "VALUES (:tid, :name, :desc, :perms::jsonb, :sys) "
                "ON CONFLICT (tenant_id, name) DO NOTHING"
            ), {"tid": tid, "name": name, "desc": desc, "perms": json.dumps(perms), "sys": is_sys})


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS roles")
