"""fb_credentials.created_by 录入人

Revision ID: 0099
Revises: 0098
"""
from alembic import op
import sqlalchemy as sa

revision = "0099"
down_revision = "0098"


def upgrade():
    op.add_column("fb_credentials",
                  sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True))
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON fb_credentials TO toveads_app")
    op.execute("GRANT SELECT ON fb_credentials TO toveads_super")


def downgrade():
    op.drop_column("fb_credentials", "created_by")
