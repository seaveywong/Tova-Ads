"""lead_form_templates.platform——表单模板按平台隔离（fb/tt）。

存量行回填 'fb'（历史表单模板全部是 FB Instant Form）；
fb_form_id/fb_page_id 两列复用为通用缓存（TT 表单存 form_id/advertiser_id）。

Revision ID: 0079
Revises: 0078
"""
from alembic import op
import sqlalchemy as sa

revision = "0079"
down_revision = "0078"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lead_form_templates", sa.Column("platform", sa.Text(), server_default="fb", nullable=False))
    # 表已授权过 DML（0053 建表已授角色），列级变更无需重授


def downgrade() -> None:
    op.drop_column("lead_form_templates", "platform")
