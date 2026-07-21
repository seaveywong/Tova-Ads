"""guard_rules.scope_act_id（规则作用域：NULL=全局所有账户 / 指定 act_id=该账户，2026-07-07 用户决策）

Revision ID: 0018
Revises: 0017

用户：规则分全局（名下所有账户）+ 账户级（指定账户）两种作用域。账户级不覆盖全局（并存各评估）。
"""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("guard_rules", sa.Column("scope_act_id", sa.Text))  # NULL=全局；act_id(裸数字)=仅该账户
    op.create_index("ix_guard_rules_scope", "guard_rules", ["tenant_id", "enabled", "scope_act_id"])


def downgrade() -> None:
    op.drop_index("ix_guard_rules_scope", table_name="guard_rules")
    op.drop_column("guard_rules", "scope_act_id")
