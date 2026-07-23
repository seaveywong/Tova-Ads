"""roles 表补 RLS（迁移 0042 建表时漏了 ENABLE/POLICY）

Revision ID: 0044
Revises: 0043
"""
from alembic import op
import sqlalchemy as sa

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE roles ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE roles FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_iso ON roles FOR ALL
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint)
    """)
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON roles TO toveads_app, toveads_super")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_iso ON roles")
    op.execute("ALTER TABLE roles NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE roles DISABLE ROW LEVEL SECURITY")
