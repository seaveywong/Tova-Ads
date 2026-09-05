"""KPI AI regression assertions; --offline skips PostgreSQL integration checks.

Provider responses are mocked. DB checks use unique test keys and clean up in finally.
No ad operations, notifications, or real AI requests are issued by this suite.
"""
import json
import pathlib
import re
import subprocess
import sys
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend" if (ROOT / "backend/app").is_dir() else ROOT))

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.core.ai_client import AiClient, AiError
from app.core.config import settings
from app.core.database import SuperSessionLocal
from app.core.deps import require_superadmin
from app.core.error_i18n import translate_error
from app.core.kpi_mapping import _default_mapping
from app.models.system import SystemSetting
from app.routers.settings import router as settings_router
from app.services import kpi_resolver as kpi

PURCHASE = "offsite_conversion.fb_pixel_purchase"
ACTIONS = [{"action_type": PURCHASE, "value": "13"},
           {"action_type": "link_click", "value": "500"}]
QUOTA_BODY = [{"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                         "message": "Your prepayment credits are depleted."}}]
QUOTA_ZH = "AI 服务额度不足，请检查服务商余额或配额后重试。"
RATE_ZH = "AI 请求过于频繁，请稍后重试。"


def client_for(key):
    return AiClient(base_url="https://kpi-smoke.invalid/v1", api_key=key, model="smoke")


def resolve(db, objective="SMOKE_UNKNOWN"):
    return kpi.resolve_kpi(db, 1, "smoke-no-campaign", objective, "", ACTIONS)


class OfflineChecks(unittest.TestCase):
    def setUp(self):
        self.client = client_for(uuid.uuid4().hex)
        self.db = Mock()
        self.db.query.return_value.filter.return_value.first.return_value = None
        self.addCleanup(patch.stopall)
        patch.object(kpi, "AiClient", return_value=self.client).start()
        patch("app.core.kpi_mapping.get_kpi_mapping", return_value=_default_mapping()).start()
        kpi._AI_KPI_CACHE.clear()

    def test_429_classification_and_bilingual_details(self):
        cases = [(QUOTA_BODY, QUOTA_ZH),
                 ({"error": {"type": "insufficient_quota"}}, QUOTA_ZH),
                 ({"error": {"status": "RESOURCE_EXHAUSTED", "message": "Rate limit exceeded"}}, RATE_ZH)]
        for payload, expected in cases:
            with self.subTest(payload=payload), patch("app.core.ai_client.httpx.post", return_value=httpx.Response(429, json=payload)):
                with self.assertRaises(AiError) as caught:
                    self.client.chat([])
                self.assertEqual((caught.exception.status, str(caught.exception)), (429, expected))
                en = translate_error(expected, "en")
                self.assertNotEqual(en, expected)
                self.assertIsNone(re.search(r"[\u3400-\u9fff]", en))

    def test_connection_test_localizes_text_and_vision_errors(self):
        app = FastAPI()
        app.include_router(settings_router)
        app.dependency_overrides[require_superadmin] = lambda: SimpleNamespace(is_superadmin=True)
        web = TestClient(app)
        with patch.object(settings, "ai_api_key", "smoke"), patch.object(settings, "ai_vision_api_key", "smoke"):
            for payload, message in [(QUOTA_BODY, QUOTA_ZH), ({"error": "rate limited"}, RATE_ZH)]:
                with patch("app.core.ai_client.httpx.post", return_value=httpx.Response(429, json=payload)):
                    for locale in ("zh", "en", "EN"):
                        for vision in ("false", "true"):
                            r = web.post("/settings/ai/test?vision=" + vision, headers={"X-Locale": locale})
                            self.assertEqual(r.status_code, 200)
                            self.assertEqual(r.json(), {"ok": False, "detail": translate_error(message, locale.lower())})

    def test_quota_failure_preserves_fallback_conversions(self):
        with patch.object(kpi, "_kpi_ai_json", side_effect=AiError(QUOTA_ZH, 429)), self.assertLogs("toveads.kpi", "WARNING"):
            result = resolve(self.db)
        self.assertEqual((result["source"], result["kpi_field"], result["conversions"]), ("fallback", PURCHASE, 13))

    def test_manual_and_matrix_kpis_do_not_require_ai(self):
        with patch.object(kpi, "_kpi_ai_json", side_effect=AssertionError("AI must not be called")):
            result = resolve(self.db, "OUTCOME_SALES")
            self.assertEqual((result["source"], result["conversions"]), ("rule", 13))
            self.db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(kpi_field=PURCHASE, target_cpa=7.5)
            result = resolve(self.db)
            self.assertEqual((result["source"], result["conversions"], result["target_cpa"]), ("manual", 13, 7.5))

    def test_success_cache_is_scoped_to_ai_configuration(self):
        with patch.object(kpi, "_kpi_ai_json", return_value={"field": PURCHASE}) as call:
            self.assertEqual(resolve(self.db)["conversions"], 13)
            resolve(self.db)
            self.assertEqual(call.call_count, 1)
            self.client.api_key = "rotated-smoke-key"
            resolve(self.db)
            self.assertEqual(call.call_count, 2)

    def test_ai_failure_does_not_promote_clicks_or_video_to_conversions(self):
        actions = [{"action_type": "video_view", "value": "900"}, {"action_type": "link_click", "value": "500"}]
        with patch.object(kpi, "_kpi_ai_json", side_effect=AssertionError("No valid conversion candidate")):
            result = kpi.resolve_kpi(self.db, 1, "", "SMOKE_UNKNOWN", "", actions)
        self.assertEqual((result["source"], result["conversions"]), ("default", 0))


class DatabaseChecks(unittest.TestCase):
    def setUp(self):
        self.token = "smoke-" + uuid.uuid4().hex
        self.client = client_for(self.token)
        self.key = kpi._ai_retry_key(self.client)
        self.pending_key = self.token + "-pending"
        self.lock = 1_000_000_000 + uuid.uuid4().int % 1_000_000_000
        self.addCleanup(self.cleanup_state)
        self.addCleanup(patch.stopall)
        patch.object(kpi, "_AI_KPI_LOCK", self.lock).start()
        patch.object(kpi, "AiClient", return_value=self.client).start()
        patch("app.core.kpi_mapping.get_kpi_mapping", return_value=_default_mapping()).start()
        self.db = SuperSessionLocal()
        self.addCleanup(self.db.close)
        kpi._AI_KPI_CACHE.clear()

    def cleanup_state(self):
        with SuperSessionLocal() as db:
            db.query(SystemSetting).filter(SystemSetting.key.in_([self.key, self.pending_key])).delete(synchronize_session=False)
            db.commit()

    def child_probe(self):
        # New interpreters have no inherited Python cache or settings patches.
        p = subprocess.run([sys.executable, str(pathlib.Path(__file__).resolve()), "--child", self.token, str(self.lock)],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("CHILD_FALLBACK_13_NO_HTTP", p.stdout)

    def test_429_shared_across_processes_and_caller_rollback(self):
        self.db.add(SystemSetting(key=self.pending_key, value="uncommitted"))
        self.db.flush()
        with patch("app.core.ai_client.httpx.post", return_value=httpx.Response(429, json=QUOTA_BODY)) as call, self.assertLogs("toveads.kpi", "WARNING"):
            for objective in ("SMOKE_A", "SMOKE_B", "SMOKE_C"):
                result = resolve(self.db, objective)
                self.assertEqual((result["source"], result["conversions"]), ("fallback", 13))
            self.assertEqual(call.call_count, 1)
        with SuperSessionLocal() as independent:
            self.assertIsNone(independent.get(SystemSetting, self.pending_key), "Caller transaction was committed")
            state = json.loads(independent.get(SystemSetting, self.key).value)
            self.assertEqual(state["status"], 429)
            self.assertGreater(state["retry_after"], kpi.time.time())
        self.assertEqual(self.db.get(SystemSetting, self.pending_key).value, "uncommitted")
        self.db.rollback()
        for _ in range(4):
            self.child_probe()

    def test_busy_provider_returns_fallback_without_waiting_or_requesting(self):
        with SuperSessionLocal() as holder:
            self.assertTrue(holder.execute(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": self.lock}).scalar())
            self.child_probe()

    def test_expired_429_retries_and_success_removes_marker(self):
        self.db.add(SystemSetting(key=self.key, value=json.dumps({"retry_after": 0, "status": 429})))
        self.db.commit()
        response = httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"field": PURCHASE})}}]})
        with patch("app.core.ai_client.httpx.post", return_value=response) as call:
            result = resolve(self.db)
            self.assertEqual((result["source"], result["conversions"]), ("ai", 13))
            self.assertEqual(call.call_count, 1)
        with SuperSessionLocal() as independent:
            self.assertIsNone(independent.get(SystemSetting, self.key))

    def test_expired_429_failure_renews_marker_once(self):
        self.db.add(SystemSetting(key=self.key, value=json.dumps({"retry_after": 0, "status": 429})))
        self.db.commit()
        with patch("app.core.ai_client.httpx.post", return_value=httpx.Response(429, json=QUOTA_BODY)) as call, self.assertLogs("toveads.kpi", "WARNING"):
            for objective in ("SMOKE_RETRY_A", "SMOKE_RETRY_B"):
                self.assertEqual(resolve(self.db, objective)["conversions"], 13)
            self.assertEqual(call.call_count, 1)
        with SuperSessionLocal() as independent:
            state = json.loads(independent.get(SystemSetting, self.key).value)
            self.assertGreater(state["retry_after"], kpi.time.time())

    def test_changed_credentials_bypass_old_failure_state(self):
        self.db.add(SystemSetting(key=self.key, value=json.dumps({"retry_after": kpi.time.time() + 300, "status": 429})))
        self.db.commit()
        self.client.api_key += "-new"
        response = httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"field": PURCHASE})}}]})
        with patch("app.core.ai_client.httpx.post", return_value=response) as call:
            result = resolve(self.db)
            self.assertEqual((result["source"], result["conversions"], call.call_count), ("ai", 13, 1))


def run_checks(with_db=True):
    suite = unittest.TestSuite()
    for cls in ([OfflineChecks, DatabaseChecks] if with_db else [OfflineChecks]):
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(cls))
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    if "--child" in sys.argv:
        client = client_for(sys.argv[2])
        with patch.object(kpi, "AiClient", return_value=client), patch.object(kpi, "_AI_KPI_LOCK", int(sys.argv[3])), \
                patch("app.core.kpi_mapping.get_kpi_mapping", return_value=_default_mapping()), \
                patch("app.core.ai_client.httpx.post", side_effect=AssertionError("Child must not call provider")) as call, \
                SuperSessionLocal() as db:
            result = resolve(db, "SMOKE_CHILD")
            assert (result["source"], result["conversions"]) == ("fallback", 13), result
            assert call.call_count == 0, "Provider called despite shared state/lock"
        print("CHILD_FALLBACK_13_NO_HTTP")
    else:
        sys.exit(0 if run_checks(with_db="--offline" not in sys.argv) else 1)
