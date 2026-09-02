"""fb_apps policy WITH CHECK 收紧（同 0075 tt_apps 写法——FB 侧唯一遗留 RLS 债）。

fb_apps_tenant 原 USING/WITH CHECK 均允许 tenant_id IS NULL 的系统行被租户角色
写入（0023 遗留）。收紧后租户角色只能读写自己租户的行；系统行（tenant_id NULL）
的写入只走 SuperSessionLocal（BYPASSRLS），与 tt_apps 0075 同构。

Revision ID: 0080
Revises: 0079
"""
from alembic import op

revision = "0080"
down_revision = "0079"
branch_labels = None
depends_on = None

_OLD_POLICY = "fb_apps_tenant"
_NEW_USING = "tenant_id IS NULL OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint"
_NEW_CHECK = "tenant_id IS NOT NULL AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint"


def upgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {_OLD_POLICY} ON fb_apps")
    op.execute(f"CREATE POLICY {_OLD_POLICY} ON fb_apps FOR ALL USING ({_NEW_USING}) WITH CHECK ({_NEW_CHECK})")


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {_OLD_POLICY} ON fb_apps")
    op.execute(
        "CREATE POLICY fb_apps_tenant ON fb_apps FOR ALL "
        "USING (tenant_id IS NULL OR tenant_id = current_setting('app.tenant_id', true)::bigint) "
        "WITH CHECK (tenant_id IS NULL OR tenant_id = current_setting('app.tenant_id', true)::bigint)"
    )
