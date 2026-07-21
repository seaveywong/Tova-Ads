"""action_logs: 操作/止损/哨兵日志（trace_id 关联全链路，doc 05/10）

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "action_logs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("trace_id", sa.Text, nullable=False),
        sa.Column("actor_user_id", sa.BigInteger),
        sa.Column("actor_type", sa.Text, server_default="system"),  # user/system/sentinel/warmup/sync
        sa.Column("target_type", sa.Text),   # ad/adset/campaign/account/rule/...
        sa.Column("target_id", sa.Text),
        sa.Column("action_type", sa.Text),   # create/pause/resume/inspect/sentinel_arm/...
        sa.Column("source", sa.Text),        # fb_api/landing/rule_engine/user/scheduled
        sa.Column("result", sa.Text, server_default="success"),  # success/fail
        sa.Column("raw_error", sa.Text),     # 平台视图
        sa.Column("friendly_error", sa.Text),# 客户视图（doc 05 翻译层）
        sa.Column("trigger_type", sa.Text),  # 规则触发时填: bleed_abs/cpa_exceed/...
        sa.Column("trigger_detail", sa.Text),# 命中指标详情
        sa.Column("metadata", sa.Text),      # JSON 快照
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_action_logs_tenant", "action_logs", ["tenant_id"])
    op.create_index("ix_action_logs_trace", "action_logs", ["trace_id"])
    op.create_index("ix_action_logs_target", "action_logs", ["target_type", "target_id"])

    op.execute("ALTER TABLE action_logs ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE action_logs FORCE ROW LEVEL SECURITY;")
    op.execute("CREATE POLICY tenant_iso ON action_logs FOR ALL "
               "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint);")

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_super;")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO toveads_super;")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS action_logs;")
