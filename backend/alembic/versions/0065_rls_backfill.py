"""9 张租户数据表补 RLS 策略（审计 2026-08-17：新表快速堆叠时漏开 RLS）

page_posts / ads_cache / leads / ad_redirect_overrides / launch_templates /
launch_jobs / launch_job_items / message_templates / lead_form_templates
此前只靠 ORM 层显式 tenant_id 过滤兜底；本迁移补 ENABLE+FORCE+tenant_iso 策略（纵深防御，
任何后续查询遗漏过滤即 fail-closed 而非裸奔）。

Revision ID: 0065
Revises: 0064
Create Date: 2026-08-17
"""
from alembic import op

revision = "0065"
down_revision = "0064"

_TABLES = [
    "page_posts", "ads_cache", "leads", "ad_redirect_overrides",
    "launch_templates", "launch_jobs", "launch_job_items",
    "message_templates", "lead_form_templates",
]
_POLICY = (
    "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint)"
)


def upgrade():
    for t in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_iso ON {t};")
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY;")
        op.execute(f"CREATE POLICY tenant_iso ON {t} FOR ALL {_POLICY};")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_super")


def downgrade():
    for t in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_iso ON {t};")
        op.execute(f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY;")
