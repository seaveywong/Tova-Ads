"""landing_pixels 加 act_id（绑账户）+ source（sync/manual）

Revision ID: 0028
Revises: 0027
"""
from alembic import op
import sqlalchemy as sa

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("landing_pixels", sa.Column("act_id", sa.Text()))
    op.add_column("landing_pixels", sa.Column("source", sa.Text(), server_default="manual"))
    op.create_index("ix_landing_pixels_act_id", "landing_pixels", ["act_id"])
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON landing_pixels TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON landing_pixels TO toveads_super;")


def downgrade() -> None:
    op.drop_index("ix_landing_pixels_act_id", table_name="landing_pixels")
    op.drop_column("landing_pixels", "source")
    op.drop_column("landing_pixels", "act_id")
