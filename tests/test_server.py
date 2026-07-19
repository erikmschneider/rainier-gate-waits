import os
import sys
import tempfile
import unittest
from unittest import mock
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Import against an isolated database.
_tmp = tempfile.TemporaryDirectory()
os.environ["RAINIER_DB_PATH"] = str(Path(_tmp.name) / "test.sqlite3")
os.environ["ENABLE_BACKGROUND_POLLING"] = "false"

import server  # noqa: E402


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize_database()

    def test_google_duration_parser(self):
        self.assertEqual(server.parse_google_duration("3.5s"), 4)
        self.assertEqual(server.parse_google_duration("120s"), 120)
        with self.assertRaises(ValueError):
            server.parse_google_duration("120")

    def test_forecast_payload(self):
        result = server.forecast_payload("nisqually", "2026-07-18", "weekend")
        self.assertEqual(result["entrance"], "nisqually")
        self.assertEqual(len(result["hours"]), 12)
        self.assertGreater(result["hours"][6]["high"], result["hours"][0]["high"])

    def test_demo_poll_produces_current_estimates(self):
        server.seed_demo_snapshots()
        payload = server.current_payload()
        self.assertEqual(len(payload["entrances"]), 2)
        self.assertEqual({item["id"] for item in payload["entrances"]}, {"nisqually", "white-river"})
        self.assertEqual(payload["dataMode"], "demo")
        for entrance in payload["entrances"]:
            self.assertLessEqual(entrance["min"], entrance["max"])
            self.assertIn(entrance["status"], {"clear", "moderate", "severe"})

    def test_google_request_uses_pro_fields_for_two_entrances(self):
        captured = []

        def fake_http_json(url, **kwargs):
            captured.append((url, kwargs))
            return {
                "routes": [{
                    "duration": "600s",
                    "staticDuration": "480s",
                    "distanceMeters": 5000,
                }]
            }

        with mock.patch.object(server, "GOOGLE_ROUTES_API_KEY", "test-key"), \
             mock.patch.object(server, "http_json", side_effect=fake_http_json):
            errors = server.poll_google_routes()

        self.assertEqual(errors, [])
        self.assertEqual(len(captured), 2)
        for _, kwargs in captured:
            self.assertEqual(
                kwargs["headers"]["X-Goog-FieldMask"],
                "routes.duration,routes.staticDuration,routes.distanceMeters",
            )
            self.assertNotIn("extraComputations", kwargs["body"])
            self.assertNotIn("polylineQuality", kwargs["body"])

    def test_public_polling_window_defaults(self):
        self.assertEqual(server.POLL_SECONDS, 900)
        self.assertEqual(server.POLL_START_HOUR_LOCAL, 6)
        self.assertEqual(server.POLL_END_HOUR_LOCAL, 20)

    def test_report_round_trip(self):
        client = "test-client"
        started = server.start_report({"entrance": "nisqually"}, client)
        result = server.complete_report({"reportId": started["reportId"]}, client)
        self.assertEqual(result["entrance"], "nisqually")
        self.assertGreaterEqual(result["waitSeconds"], 1)


if __name__ == "__main__":
    unittest.main()
