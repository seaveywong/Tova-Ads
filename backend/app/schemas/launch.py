"""铺广告 / 子码 / 预检 Schema。"""
from pydantic import BaseModel


class GenerateSubcodeIn(BaseModel):
    act_id: str | None = None
    page_id: int | None = None


class SubcodeOut(BaseModel):
    id: int
    slug: str
    url: str
    act_id: str | None = None
    status: str
    ad_id: str | None = None


# ── 预检 ──
class PrecheckIn(BaseModel):
    act_id: str
    objective: str = "OUTCOME_SALES"
    page_id: str | None = None
    pixel_id: str | None = None
    landing_url: str | None = None
    subcode_slug: str | None = None
    bid_strategy: str = "LOWEST_COST_WITHOUT_CAP"
    target_cpa: float | None = None


class PrecheckItem(BaseModel):
    key: str
    label: str
    status: str  # pass/fail/warn
    msg: str


class PrecheckOut(BaseModel):
    pass_: bool
    items: list[PrecheckItem]
