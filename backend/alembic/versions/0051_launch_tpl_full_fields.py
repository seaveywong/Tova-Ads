"""launch_templates 加完整 FB Ads Manager 字段(optimization_goal/billing_event/destination_type/audience_json/advanced_config/budget_usd)；assets 加 language

Phase 1 投放模板编辑器对等 FB Ads Manager（[[launch-templates-module]] P1）。

Revision ID: 0051
Revises: 0050
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade():
    for col, typ in [
        ("optimization_goal", sa.Text()),
        ("billing_event", sa.Text()),
        ("destination_type", sa.Text()),
        ("audience_json", sa.Text()),
        ("advanced_config", sa.Text()),
        ("budget_usd", sa.Float()),
    ]:
        op.add_column("launch_templates", sa.Column(col, typ))
    op.add_column("assets", sa.Column("language", sa.Text()))
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_super;")


def downgrade():
    op.drop_column("assets", "language")
    for col in ("budget_usd", "advanced_config", "audience_json", "destination_type", "billing_event", "optimization_goal"):
        op.drop_column("launch_templates", col)
