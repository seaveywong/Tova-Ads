"""0092: 批次I FB 对齐——launch_templates 增 WhatsApp 显式号码列

whatsapp_phone_number：Click-to-WhatsApp 广告的 adset promoted_object.whatsapp_phone_number。
仅 OUTCOME_ENGAGEMENT 目标下发（蓝图：Engagement=广告层 Accounts 区显式选号；
Traffic/Sales=随主页绑定的 WA 号隐式选定，不传）。空=不传。
"""
from alembic import op
import sqlalchemy as sa

revision = "0092"
down_revision = "0091"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("launch_templates", sa.Column("whatsapp_phone_number", sa.Text()))
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON launch_templates TO toveads_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON launch_templates TO toveads_super")


def downgrade() -> None:
    op.drop_column("launch_templates", "whatsapp_phone_number")
