"""0108: 域名生命周期（批2，方案 toveads/域名续费与有效期方案.md，用户拍板：自动续费默认开+双通道续费）

landing_domains：expires_at（到期日，注册响应/每日同步对齐）/ auto_renew（默认开）/
  registrar（dynadot|porkbun|external，external 不参与续费）/ last_renewed_at / last_notice_tier（提醒档去重）。
domain_orders：kind（register|renew——续费复用订单双通道：余额直扣 or USDT 直付到账自动续）。
"""
from alembic import op
import sqlalchemy as sa

revision = "0108"
down_revision = "0107"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("landing_domains", sa.Column("expires_at", sa.DateTime(timezone=True)))
    op.add_column("landing_domains", sa.Column("auto_renew", sa.Boolean, nullable=False, server_default="true"))
    op.add_column("landing_domains", sa.Column("registrar", sa.Text))
    op.add_column("landing_domains", sa.Column("last_renewed_at", sa.DateTime(timezone=True)))
    op.add_column("landing_domains", sa.Column("last_notice_tier", sa.Integer))
    op.add_column("domain_orders", sa.Column("kind", sa.Text, nullable=False, server_default="register"))
    op.execute("CREATE INDEX IF NOT EXISTS ix_landing_domains_expires ON landing_domains (expires_at)")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON landing_domains TO toveads_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON landing_domains TO toveads_super")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON domain_orders TO toveads_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON domain_orders TO toveads_super")


def downgrade() -> None:
    op.drop_column("domain_orders", "kind")
    op.drop_column("landing_domains", "last_notice_tier")
    op.drop_column("landing_domains", "last_renewed_at")
    op.drop_column("landing_domains", "registrar")
    op.drop_column("landing_domains", "auto_renew")
    op.drop_column("landing_domains", "expires_at")
