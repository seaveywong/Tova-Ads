"""assets 表加 AI 识别字段（ai_copy_json/ai_audience_json/ai_status/ai_error/analyzed_at/country）

素材 AI 分析：视觉模型看图 → 生成文案(ai_copy_json) + 受众建议(ai_audience_json)。
ai_status 状态机：none(未分析) / analyzing(分析中) / done(完成) / failed(失败)。

Revision ID: 0047
Revises: 0046
Create Date: 2026-07-26
"""
from alembic import op
import sqlalchemy as sa

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("assets", sa.Column("country", sa.Text()))
    op.add_column("assets", sa.Column("ai_copy_json", sa.Text()))
    op.add_column("assets", sa.Column("ai_audience_json", sa.Text()))
    op.add_column("assets", sa.Column("ai_status", sa.Text(), server_default="none"))
    op.add_column("assets", sa.Column("ai_error", sa.Text()))
    op.add_column("assets", sa.Column("analyzed_at", sa.DateTime(timezone=True)))
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toveads_super;")


def downgrade():
    for col in ("analyzed_at", "ai_error", "ai_status", "ai_audience_json", "ai_copy_json", "country"):
        op.drop_column("assets", col)
