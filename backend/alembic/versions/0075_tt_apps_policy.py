"""tt_apps RLS policy 收紧：租户会话不能写系统级行（tenant_id IS NULL）。

0070 的 tt_apps_tenant 照抄了 fb_apps（0023）的写法：WITH CHECK 允许
`tenant_id IS NULL OR tenant_id = current`——RLS 受限的租户角色可 INSERT/UPDATE
系统级行（改全租户共享的 App 配置）。系统行的正常写路径走 SuperSessionLocal
（BYPASSRLS），不受本收紧影响。

收紧后：
- USING 不变（系统行对所有租户可读——resolve_tt_app 依赖）
- WITH CHECK = tenant_id IS NOT NULL AND tenant_id = current（租户只能写自己的行）

fb_apps 存在同款问题但**留档不动**（FB 红线：本批不改任何 FB 行为，另批处理）。

Revision ID: 0075
Revises: 0074
"""
from alembic import op

revision = "0075"
down_revision = "0074"
branch_labels = None
depends_on = None

# 0070 原版（downgrade 恢复用）
_POLICY_0070 = """CREATE POLICY tt_apps_tenant ON tt_apps
        FOR ALL
        USING (tenant_id IS NULL OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint)
        WITH CHECK (tenant_id IS NULL OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint);"""

# 收紧版：租户会话只写本租户行（系统行写入仅 BYPASSRLS 会话可做）
_POLICY_TIGHT = """CREATE POLICY tt_apps_tenant ON tt_apps
        FOR ALL
        USING (tenant_id IS NULL OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint)
        WITH CHECK (tenant_id IS NOT NULL AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint);"""


def upgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tt_apps_tenant ON tt_apps;")
    op.execute(_POLICY_TIGHT)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tt_apps_tenant ON tt_apps;")
    op.execute(_POLICY_0070)
