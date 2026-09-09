"""0094 批AG 权鉴：guard_rules 加 created_by（operator 只看自己创建的规则）

回填：既有规则归各租户 owner（tenant_memberships role='owner'）——规则历史由 owner 创建。
GRANT toveads_app + toveads_super。
"""
from alembic import op
import sqlalchemy as sa

revision = "0094"
down_revision = "0093"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("guard_rules",
                  sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True))
    # 回填：每租户 owner 用户（多 owner 取最小 id）
    op.execute("""
        UPDATE guard_rules g
        SET created_by = (
            SELECT MIN(m.user_id) FROM tenant_memberships m
            WHERE m.tenant_id = g.tenant_id AND m.role = 'owner'
        )
        WHERE g.created_by IS NULL
    """)
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON guard_rules TO toveads_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON guard_rules TO toveads_super")


def downgrade() -> None:
    op.drop_column("guard_rules", "created_by")
