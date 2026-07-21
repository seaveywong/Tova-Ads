"""ORM：广告每日表现快照（doc 03 + 看板缓存层，审计项目9 + 2026-07-07 调研）。"""
from sqlalchemy import Column, BigInteger, Text, Integer, Float, DateTime, ForeignKey, UniqueConstraint, func
from ..core.database import Base


class PerfSnapshot(Base):
    __tablename__ = "perf_snapshots"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    act_id = Column(Text, nullable=False)
    ad_id = Column(Text, nullable=False)
    snapshot_date = Column(Text, nullable=False)  # 账户本地日 YYYY-MM-DD
    spend = Column(Float, default=0)            # USD 换算后
    spend_native = Column(Float, default=0)      # 本币原值
    currency = Column(Text)
    conversions = Column(Integer, default=0)
    cpa = Column(Float)
    roas = Column(Float)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    reach = Column(Integer, default=0)
    frequency = Column(Float)
    ctr = Column(Float)
    cpc = Column(Float)
    # KPI 诊断（交接包 §4.1：排查"FB显示X我们显示Y"）
    actions_json = Column(Text)       # FB 回传的原始 actions JSON
    resolved_kpi = Column(Text)      # resolver 实际用的 kpi_field
    kpi_source = Column(Text)        # 解析来源（manual/matrix/objective_fallback/semantic）
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("ad_id", "snapshot_date", name="uq_perf_ad_date"),)


class PerfSnapshotTick(Base):
    """趋势折线时序数据：每次巡检验证写一条（5min 粒度），供折线图最小颗粒度。
    与 PerfSnapshot 区别：后者每日 upsert（缓存），本表不覆盖（时序，每次一条）。"""
    __tablename__ = "perf_snapshot_ticks"
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    act_id = Column(Text, nullable=False)
    snapshot_date = Column(Text, nullable=False)      # 北京日
    snapshot_at = Column(DateTime(timezone=True), nullable=False)  # 巡检时刻（5min 粒度）
    spend = Column(Float, default=0)                  # USD
    conversions = Column(Integer, default=0)
    cpa = Column(Float)
    roas = Column(Float)


class CurrencyRate(Base):
    __tablename__ = "currency_rates"
    code = Column(Text, primary_key=True)
    rate = Column(Float, nullable=False)  # 1 USD = rate × 本币
    fetched_at = Column(DateTime(timezone=True), server_default=func.now())

