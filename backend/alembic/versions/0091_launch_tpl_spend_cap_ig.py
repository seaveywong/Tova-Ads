"""0091: FB 1:1 尾巴小件——launch_templates 系列支出上限 + IG 账号 ID

spend_cap_usd：系列支出上限（USD，可选）。campaign.spend_cap（按账户本币 minor units）
——累计花费达到即停整个系列，与预算（控制投放节奏）语义不同。
instagram_actor_id：创意身份用 IG 账号 ID（可选，空=用主页关联 IG）。
"""
from alembic import op
import sqlalchemy as sa

revision = "0091"
down_revision = "0090"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("launch_templates", sa.Column("spend_cap_usd", sa.Float()))
    op.add_column("launch_templates", sa.Column("instagram_actor_id", sa.Text()))
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON launch_templates TO toveads_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON launch_templates TO toveads_super")


def downgrade() -> None:
    op.drop_column("launch_templates", "instagram_actor_id")
    op.drop_column("launch_templates", "spend_cap_usd")
