"""Ads Manager read-model assertions. No platform writes or live ad changes."""
import pathlib
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

root = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(root / 'backend' if (root / 'backend/app').is_dir() else root))
from app.routers.ads import _perf_map, _attach_perf


class ReadModelChecks(unittest.TestCase):
    def test_results_account_platform_isolation_and_zero(self):
        db = Mock()
        query = db.query.return_value
        query.filter.return_value = query
        query.group_by.return_value = query
        now = datetime.now(timezone.utc)
        # ad id, USD, native, combined, impressions, clicks, reach, FB,
        # measured row count, total row count, updated, account, platform
        query.all.return_value = [
            ('same', 20, 140, 9, 100, 10, 70, 2, 1, 1, now, 'a', 'fb'),
            ('same', 30, 30, 10, 200, 20, 100, 0, 1, 1, now, 'b', 'fb'),
            ('same', 90, 90, 11, 300, 30, 200, 8, 1, 1, now, 'a', 'tt'),
        ]
        perf = _perf_map(db, 1, '', '2026-09-01', '2026-09-09')
        rows = _attach_perf([
            {'id': 'same', 'act_id': 'a', 'platform': 'fb'},
            {'id': 'same', 'act_id': 'b', 'platform': 'fb'},
            {'id': 'same', 'act_id': 'a', 'platform': 'tt'},
        ], perf)
        self.assertEqual([r['results_fb'] for r in rows], [2, 0, 8])
        self.assertEqual([r['conversions'] for r in rows], [9, 10, 11])
        self.assertEqual(rows[0]['cost_per_result'], 70)
        self.assertEqual(rows[0]['cost_per_result_usd'], 10)
        self.assertIsNone(rows[1]['cost_per_result'])
        self.assertEqual(rows[0]['spend'], 140)

    def test_missing_or_partial_fb_data_remains_unknown(self):
        row = {'id': '1', 'act_id': 'a', 'platform': 'fb'}
        self.assertIsNone(_attach_perf([row], {})[0]['results_fb'])
        perf = {('fb', 'a', '1'): dict(spend=10, spend_usd=10, conv=99,
                impressions=1, clicks=1, reach=1, results_fb=2, results_fb_complete=False)}
        result = _attach_perf([row], perf)[0]
        self.assertIsNone(result['results_fb'])
        self.assertFalse(result['results_fb_complete'])
        self.assertEqual(result['conversions'], 99)

    def test_results_fb_availability_flag(self):
        """0093 前迁移默认 0 不可冒充实测；新行/非零行/TT 行口径判定。"""
        from app.routers.ads import _FB_RESULTS_EPOCH
        db = Mock()
        query = db.query.return_value
        query.filter.return_value = query
        query.group_by.return_value = query
        pre_epoch = _FB_RESULTS_EPOCH - timedelta(days=7)
        fresh = datetime.now(timezone.utc)
        naive_old = (_FB_RESULTS_EPOCH - timedelta(days=1)).replace(tzinfo=None)
        query.all.return_value = [
            # ad id, USD, native, combined, impressions, clicks, reach, FB,
            # measured row count, total row count, updated, account, platform
            ('old0', 10, 10, 1, 1, 1, 1, 0, 1, 1, pre_epoch, 'a', 'fb'),
            ('oldnaive', 10, 10, 1, 1, 1, 1, 0, 1, 1, naive_old, 'a', 'fb'),
            ('new0', 10, 10, 1, 1, 1, 1, 0, 1, 1, fresh, 'a', 'fb'),
            ('oldnonzero', 10, 10, 1, 1, 1, 1, 3, 1, 1, pre_epoch, 'a', 'fb'),
            ('ttfresh', 10, 10, 1, 1, 1, 1, 0, 1, 1, fresh, 'a', 'tt'),
        ]
        perf = _perf_map(db, 1, '', '2026-09-01', '2026-09-09')
        self.assertFalse(perf[('fb', 'a', 'old0')]['results_fb_available'])
        self.assertFalse(perf[('fb', 'a', 'oldnaive')]['results_fb_available'])
        self.assertTrue(perf[('fb', 'a', 'new0')]['results_fb_available'])
        self.assertTrue(perf[('fb', 'a', 'oldnonzero')]['results_fb_available'])
        self.assertFalse(perf[('tt', 'a', 'ttfresh')]['results_fb_available'])
        row = _attach_perf([{'id': 'old0', 'act_id': 'a', 'platform': 'fb'}], perf)[0]
        self.assertFalse(row['results_fb_available'])
        self.assertEqual(row['results_fb'], 0)  # 原始值保留，呈现由前端按 available 判定
        self.assertTrue(_attach_perf([{'id': 'ghost', 'act_id': 'a', 'platform': 'fb'}], perf)[0]['results_fb_available'] is False)


if __name__ == '__main__':
    unittest.main(verbosity=2)
