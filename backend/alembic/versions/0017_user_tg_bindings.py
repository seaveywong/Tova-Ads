"""user_tg_bindings（用户级 TG）+ notifications.roles（角色订阅，06 通知附录决策①③）

Revision ID: 0017
Revises: 0016

决策③：TG 绑定升级用户级（每人绑自己的 TG）。决策①：告警按角色订阅（notifications.roles）。
保留 tenant_tg_bindings 过渡 fallback（用户级没绑时回退租户级，不断现网）。
"""
from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

_RLS = ["user_tg_bindings"]
_POLICY = "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint)"


def upgrade() -> None:
    # 用户级 TG 绑定
    op.create_table(
        "user_tg_bindings",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("bot_token_enc", sa.Text, nullable=False),
        sa.Column("chat_id", sa.Text, nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_user_tg_tenant_user"),
    )
    op.create_index("ix_user_tg_user", "user_tg_bindings", ["tenant_id", "user_id"])
    # notifications 加 roles（角色订阅，决策①；空=全员）
    op.add_column("notifications", sa.Column("roles", sa.Text))  # 逗号分隔 owner,operator,finance

    for t in _RLS:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY;")
        op.execute(f"CREATE POLICY tenant_iso ON {t} FOR ALL {_POLICY};")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_super;")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO toveads_super;")


def downgrade() -> None:
    op.drop_column("notifications", "roles")
    op.execute("DROP TABLE IF EXISTS user_tg_bindings;")
