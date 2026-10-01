"""ad_builder 纯函数测试：normalize_objective（旧目标名归一）+ build_campaign（系列 payload）。

build_campaign 的默认值是合规硬约束：special_ad_categories 默认空（用户显式选择
才声明）、预算共享显式 false（新一代账户 4834011 实测要求）、ABO/CBO 预算语义分流。
"""
import pytest

from app.core.ad_builder import build_campaign, normalize_objective


class TestNormalizeObjective:
    def test_legacy_objective_names_map_to_outcome_names(self):
        """旧版目标名（1.0 口径）→ 新版 OUTCOME_* 名。"""
        assert normalize_objective("CONVERSIONS") == "OUTCOME_SALES"
        assert normalize_objective("OUTCOME_CONVERSIONS") == "OUTCOME_SALES"
        assert normalize_objective("LINK_CLICKS") == "OUTCOME_TRAFFIC"
        assert normalize_objective("LEAD_GENERATION") == "OUTCOME_LEADS"
        assert normalize_objective("MESSAGES") == "OUTCOME_ENGAGEMENT"
        assert normalize_objective("OUTCOME_MESSAGES") == "OUTCOME_ENGAGEMENT"
        assert normalize_objective("OUTCOME_MESSAGING") == "OUTCOME_ENGAGEMENT"

    def test_canonical_names_pass_through(self):
        """已是新版名 → 原样返回。"""
        for obj in ("OUTCOME_SALES", "OUTCOME_LEADS", "OUTCOME_TRAFFIC",
                    "OUTCOME_ENGAGEMENT", "OUTCOME_AWARENESS"):
            assert normalize_objective(obj) == obj

    def test_unknown_name_passes_through_unchanged(self):
        """未知名不猜不吞：原样返回（合法性由 OPT_GOALS_BY_OBJECTIVE 等校验层负责）。"""
        assert normalize_objective("SOMETHING_NEW") == "SOMETHING_NEW"


class TestBuildCampaignDefaults:
    def test_abo_defaults(self):
        """默认（ABO）payload：状态 ACTIVE、特殊类别空、AUCTION、预算共享显式关闭。"""
        payload = build_campaign("测试系列", "CONVERSIONS")
        assert payload["name"] == "测试系列"
        assert payload["objective"] == "OUTCOME_SALES"      # 传入旧名被归一
        assert payload["status"] == "ACTIVE"
        assert payload["special_ad_categories"] == []
        assert payload["buying_type"] == "AUCTION"
        # ABO 分支覆写为 Python False（CBO 分支保留字符串 "false"——两种表示都=关闭）
        assert payload["is_adset_budget_sharing_enabled"] is False
        # 未配置的预算字段不出现（None/0=不限，不发给 FB）
        assert "daily_budget" not in payload
        assert "lifetime_budget" not in payload
        assert "spend_cap" not in payload

    def test_special_ad_categories_none_becomes_empty_list(self):
        """special_ad_categories=None（默认缺省）→ []（FB 要求字段必须显式为空数组）。"""
        payload = build_campaign("n", "OUTCOME_SALES", special_ad_categories=None)
        assert payload["special_ad_categories"] == []

    def test_explicit_special_ad_categories_kept(self):
        """显式声明的特殊类别（信贷/就业等）原样透传。"""
        payload = build_campaign("n", "OUTCOME_SALES", special_ad_categories=["HOUSING"])
        assert payload["special_ad_categories"] == ["HOUSING"]

    def test_spend_cap_only_when_positive(self):
        """系列支出上限：None/0=不发送；正值转字符串 minor units。"""
        assert "spend_cap" not in build_campaign("s", "OUTCOME_SALES", spend_cap=0)
        assert "spend_cap" not in build_campaign("s", "OUTCOME_SALES", spend_cap=None)
        assert build_campaign("s", "OUTCOME_SALES", spend_cap=12345)["spend_cap"] == "12345"


class TestBuildCampaignBudgetModes:
    def test_cbo_without_budget_raises(self):
        """CBO 必须配系列级预算（日或总），缺配=调用方 bug，尽早暴露。"""
        with pytest.raises(ValueError):
            build_campaign("c", "OUTCOME_SALES", budget_mode="CBO")

    def test_cbo_lifetime_budget_and_string_false(self):
        """CBO：总预算走系列级 lifetime_budget；预算共享保持字符串 "false"。"""
        payload = build_campaign("c", "OUTCOME_SALES", budget_mode="CBO", lifetime_budget=5000)
        assert payload["lifetime_budget"] == "5000"
        assert "daily_budget" not in payload
        assert payload["is_adset_budget_sharing_enabled"] == "false"
        assert payload["bid_strategy"] == "LOWEST_COST_WITHOUT_CAP"

    def test_cbo_daily_budget_used_when_no_lifetime(self):
        """CBO 无总预算时落日预算。"""
        payload = build_campaign("c", "OUTCOME_SALES", budget_mode="CBO", daily_budget=1000)
        assert payload["daily_budget"] == "1000"

    def test_cbo_invalid_bid_strategy_falls_back_to_lowest_cost(self):
        """非法 bid_strategy 回退 LOWEST_COST_WITHOUT_CAP（白名单外不让进 payload）。"""
        payload = build_campaign("c", "OUTCOME_SALES", budget_mode="CBO",
                                 lifetime_budget=5000, bid_strategy="NOT_A_STRATEGY")
        assert payload["bid_strategy"] == "LOWEST_COST_WITHOUT_CAP"
