"""guard_rules.rule_scope：user=仅创建人名下账户 / team=全团队（仅 owner/超管可选）

Revision ID: 0101
Revises: 0100
"""
from alembic import op
import sqlalchemy as sa

revision = "0101"
down_revision = "0100"


def upgrade():
    op.add_column("guard_rules",
                  sa.Column("rule_scope", sa.Text(), server_default="user", nullable=False))
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON guard_rules TO toveads_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON guard_rules TO toveads_super")


def downgrade():
    op.drop_column("guard_rules", "rule_scope")
