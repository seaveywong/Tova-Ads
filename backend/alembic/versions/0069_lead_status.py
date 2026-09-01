"""leads.status/note/status_updated_at——潜客轻 CRM 跟进字段。

潜客列表从只读数据变可跟进：status 流转（new/contacted/won/lost，DB 端默认 new，
存量行由 server_default 回填）+ note 跟进备注 + status_updated_at 最近更新时间。
均为本地状态，不回写 FB。

Revision ID: 0069
Revises: 0068
"""
from alembic import op
import sqlalchemy as sa

revision = "0069"
down_revision = "0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("status", sa.Text(), nullable=False, server_default="new"))
    op.add_column("leads", sa.Column("note", sa.Text()))
    op.add_column("leads", sa.Column("status_updated_at", sa.DateTime(timezone=True)))
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON leads TO toveads_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON leads TO toveads_super")
    # leads 建表时漏授 id 序列（toveads_super 无 USAGE → SuperSessionLocal 插 lead 直接
    # permission denied，webhook 入库会崩）。此处补齐；prod 已手工执行过同一语句。
    op.execute("GRANT USAGE, SELECT ON SEQUENCE leads_id_seq TO toveads_app")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE leads_id_seq TO toveads_super")


def downgrade() -> None:
    op.drop_column("leads", "status_updated_at")
    op.drop_column("leads", "note")
    op.drop_column("leads", "status")
