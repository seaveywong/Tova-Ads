"""launch_job_items 加 error_code（FB 错误 category，供前端 i18n 翻译失败原因）

投放每账户失败时存 FB error category（cert_required/invalid_param/bid_required/...），
前端按 category 查中英翻译，不再显示原文。

Revision ID: 0058
Revises: 0057
Create Date: 2026-07-31
"""
from alembic import op
import sqlalchemy as sa

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("launch_job_items", sa.Column("error_code", sa.Text()))


def downgrade():
    op.drop_column("launch_job_items", "error_code")
