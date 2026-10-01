"""kpi_resolver 纯函数测试：_action_count（actions 计数）+ _kpi_config_cache（L0 缓存）。

_action_count 是 KPI 转化计数的最终落点（PAGE_LIKES 回传 0 事故的修复层）；
_kpi_config_cache 的关键不变量：查不到（None）也要缓存——巡检 per-ad 高频查询，
不缓存 None 等于缓存失效。
"""
import time

import pytest

from app.services import kpi_resolver
from app.services.kpi_resolver import _action_count, _kpi_config_cache
from app.models.kpi import KpiConfig


class _StubQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._result


class _StubDb:
    """最小 db stub：query(Model).filter(...).first() → 预设结果，并统计查询次数。"""

    def __init__(self, result=None):
        self._result = result
        self.query_count = 0

    def query(self, model):
        assert model is KpiConfig, f"意外查询模型: {model}"
        self.query_count += 1
        return _StubQuery(self._result)


@pytest.fixture(autouse=True)
def _clean_module_cache():
    """_KPI_CFG_CACHE 是模块级全局，必须每测清空避免跨测试污染。"""
    kpi_resolver._KPI_CFG_CACHE.clear()
    yield
    kpi_resolver._KPI_CFG_CACHE.clear()


class TestActionCount:
    def test_empty_actions_returns_zero(self):
        """无 actions（无投放数据的新广告）→ 0，不报错。"""
        assert _action_count([], "like") == 0

    def test_matching_action_converts_string_value_to_int(self):
        """FB insights 的 value 是字符串，须转 int（'19' → 19 而非按字符串比较）。"""
        actions = [{"action_type": "like", "value": "19"},
                   {"action_type": "link_click", "value": "100"}]
        assert _action_count(actions, "like") == 19
        assert _action_count(actions, "link_click") == 100

    def test_multiple_entries_sum_not_supported_returns_first_match(self):
        """命中第一个匹配 action_type 即返回（同字段多条时取首条，不累加）。"""
        actions = [{"action_type": "like", "value": "3"},
                   {"action_type": "like", "value": "5"}]
        assert _action_count(actions, "like") == 3

    def test_float_value_truncates_to_int(self):
        """小数值截断为整数（3.7 → 3），不四舍五入。"""
        assert _action_count([{"action_type": "purchase", "value": "3.7"}], "purchase") == 3

    def test_non_numeric_value_returns_zero(self):
        """value 非数字（脏数据）→ 0，不抛异常。"""
        assert _action_count([{"action_type": "purchase", "value": "n/a"}], "purchase") == 0

    def test_field_not_in_actions_returns_zero(self):
        """目标字段不在 actions 里 → 0。"""
        actions = [{"action_type": "like", "value": "19"}]
        assert _action_count(actions, "purchase") == 0

    def test_empty_kpi_field_returns_zero(self):
        """kpi_field 为空串 → 不可能命中任何 action_type → 0。"""
        actions = [{"action_type": "like", "value": "19"}]
        assert _action_count(actions, "") == 0


class TestKpiConfigCache:
    def test_db_miss_none_is_cached(self):
        """查不到配置（None）也要缓存：60s 内重复调用不再打 DB（高频巡检路径）。"""
        db = _StubDb(result=None)
        assert _kpi_config_cache(db, 1, "camp-1") is None
        assert _kpi_config_cache(db, 1, "camp-1") is None
        assert db.query_count == 1, "None 结果应被缓存，第二次调用不应再查库"

    def test_db_hit_returns_config_and_caches(self):
        """查到配置 → 返回同一对象，且 60s 内复用缓存实例。"""
        cfg = KpiConfig(tenant_id=1, target_type="campaign", target_id="camp-1",
                        kpi_field="like")
        db = _StubDb(result=cfg)
        assert _kpi_config_cache(db, 1, "camp-1") is cfg
        assert _kpi_config_cache(db, 1, "camp-1") is cfg
        assert db.query_count == 1

    def test_expired_entry_requeries_db(self):
        """缓存过期（>60s TTL）→ 重新查库并覆盖缓存。"""
        stale = KpiConfig(tenant_id=1, target_type="campaign", target_id="camp-1",
                          kpi_field="like")
        kpi_resolver._KPI_CFG_CACHE[(1, "camp-1")] = (
            time.time() - kpi_resolver._KPI_CFG_TTL - 1.0, stale)
        db = _StubDb(result=None)
        assert _kpi_config_cache(db, 1, "camp-1") is None, "过期条目不应再被返回"
        assert db.query_count == 1
        assert kpi_resolver._KPI_CFG_CACHE[(1, "camp-1")][1] is None

    def test_different_tenants_do_not_share_cache(self):
        """缓存键含 tenant_id：同 campaign_id 不同租户各自查库（RLS 口径）。"""
        db = _StubDb(result=None)
        _kpi_config_cache(db, 1, "camp-1")
        _kpi_config_cache(db, 2, "camp-1")
        assert db.query_count == 2
