"""landing_pixels 唯一约束改为 (tenant_id, pixel_id, act_id) —— 允许一个像素绑多个账户(BM 共享像素)

Revision ID: 0040
Revises: 0039
"""
from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE landing_pixels DROP CONSTRAINT IF EXISTS uq_landing_pixels_tenant_pixel")
    op.create_unique_constraint("uq_landing_pixels_tenant_pixel_act", "landing_pixels",
                                ["tenant_id", "pixel_id", "act_id"])


def downgrade() -> None:
    op.drop_constraint("uq_landing_pixels_tenant_pixel_act", "landing_pixels")
