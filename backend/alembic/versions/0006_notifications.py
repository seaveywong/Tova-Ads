"""notifications + tenant_tg_bindings（doc 06 通知体系）

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_RLS = ["notifications", "tenant_tg_bindings"]
_POLICY = "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint)"


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id")),  # null=全租户
        sa.Column("level", sa.Text, nullable=False),  # critical/warning/info
        sa.Column("event_type", sa.Text, nullable=False),  # rule_pause/launch_fail/...
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("body", sa.Text),
        sa.Column("trace_id", sa.Text),
        sa.Column("target_type", sa.Text),
        sa.Column("target_id", sa.Text),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_notif_tenant", "notifications", ["tenant_id"])
    op.create_index("ix_notif_unread", "notifications", ["tenant_id", "user_id", "read_at"])

    op.create_table(
        "tenant_tg_bindings",
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("bot_token_enc", sa.Text, nullable=False),
        sa.Column("chat_id", sa.Text, nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    for t in _RLS:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY;")
        op.execute(f"CREATE POLICY tenant_iso ON {t} FOR ALL {_POLICY};")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_super;")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO toveads_super;")


def downgrade() -> None:
    for t in reversed(_RLS):
        op.execute(f"DROP TABLE IF EXISTS {t};")
