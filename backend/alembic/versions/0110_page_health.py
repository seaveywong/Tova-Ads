"""0110: 主页健康快照表（主页挂了/禁用的感知与影响面告警，2026-09-27）

背景：主页被 unpublish/下架后平台零感知，直到部署失败「公共主页未发布」才暴露
（job82 实证：Mebrelablo Plogordmire is_published=False，还有同类页在池中）。
FB Page webhook 无状态字段可订阅（官方字段表核实），只能轮询 /me/accounts 的
is_published/promotion_eligible（CLI 实测：管理员令牌可读、无需新权限、成本极低）。

本表存各令牌探测到的最新快照（多令牌可见同一页 upsert 去重），状态翻转
（发布↔未发布/消失）由扫描任务对比旧值产生告警；is_published 恢复也通知。
"""
from alembic import op
import sqlalchemy as sa

revision = "0110"
down_revision = "0109"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "page_health",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, nullable=False),
        sa.Column("page_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255)),
        sa.Column("via_cred_id", sa.Integer),                    # 最后一次探测到它的令牌
        sa.Column("is_published", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("promotion_eligible", sa.Boolean),
        sa.Column("seen", sa.Boolean, nullable=False, server_default=sa.text("true")),  # 本轮任何令牌可见
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "page_id", name="uq_page_health_tenant_page"),
    )
    op.execute("CREATE INDEX ix_page_health_tenant_checked ON page_health (tenant_id, checked_at DESC)")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON page_health TO toveads_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON page_health TO toveads_super")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE page_health_id_seq TO toveads_app")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE page_health_id_seq TO toveads_super")


def downgrade() -> None:
    op.drop_table("page_health")
