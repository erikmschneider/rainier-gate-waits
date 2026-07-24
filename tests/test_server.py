import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock
from datetime import timedelta
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

    def setUp(self):
        with server.database() as conn:
            conn.execute("delete from wait_estimates")
            conn.execute("delete from wait_reports")
            conn.execute("delete from traffic_snapshots")
            conn.execute("delete from condition_events")
            conn.execute("delete from feedback_submissions")

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
        with mock.patch.object(server, "ALLOW_SYNTHETIC_DATA", True):
            server.seed_demo_snapshots()
            payload = server.current_payload()
        self.assertEqual(len(payload["entrances"]), 2)
        self.assertEqual({item["id"] for item in payload["entrances"]}, {"nisqually", "white-river"})
        self.assertEqual(payload["dataMode"], "demo")
        for entrance in payload["entrances"]:
            self.assertLessEqual(entrance["min"], entrance["max"])
            self.assertIn(entrance["status"], {"clear", "moderate", "severe"})

    def test_public_payload_hides_estimates_without_recent_traffic(self):
        payload = server.current_payload()
        self.assertEqual(payload["dataMode"], "unavailable")
        for entrance in payload["entrances"]:
            self.assertFalse(entrance["displayable"])
            self.assertIsNone(entrance["min"])
            self.assertEqual(entrance["status"], "unavailable")

    def test_stale_observation_is_suppressed_after_display_cutoff(self):
        observed_at = server.utc_now() - timedelta(minutes=server.STALE_MAX_AGE_MINUTES + 1)
        server.store_traffic_snapshot(
            "nisqually", observed_at, 1800, 600, 5000, "google-routes", {"test": True}
        )
        item = next(entry for entry in server.current_payload()["entrances"] if entry["id"] == "nisqually")
        self.assertFalse(item["displayable"])
        self.assertIsNone(item["max"])

    def test_manual_closure_suppresses_estimate(self):
        server.store_traffic_snapshot(
            "white-river", server.utc_now(), 1800, 600, 5000, "google-routes", {"test": True}
        )
        with mock.patch.object(server, "CLOSED_ENTRANCES", {"white-river"}):
            item = next(entry for entry in server.current_payload()["entrances"] if entry["id"] == "white-river")
        self.assertTrue(item["entranceClosed"])
        self.assertFalse(item["displayable"])
        self.assertEqual(item["status"], "closed")

    def test_report_locations_are_ignored_by_default(self):
        started = server.start_report(
            {"entrance": "nisqually", "latitude": 46.75, "longitude": -121.92, "accuracyMeters": 5},
            "test-client",
        )
        with server.database() as conn:
            report = conn.execute("select * from wait_reports where id=?", (started["reportId"],)).fetchone()
        self.assertIsNone(report["queue_entry_lat"])
        self.assertIsNone(report["queue_entry_lng"])

    def test_http_error_body_is_logged_without_exposing_api_key(self):
        api_key = "AIza" + "A" * 35
        response_body = json.dumps({
            "error": {
                "code": 403,
                "status": "PERMISSION_DENIED",
                "message": f"API key {api_key} is not authorized for Routes API",
            }
        }).encode("utf-8")
        error = urllib.error.HTTPError(
            "https://routes.googleapis.com/directions/v2:computeRoutes",
            403,
            "Forbidden",
            {},
            io.BytesIO(response_body),
        )

        with mock.patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(RuntimeError) as raised:
                server.http_json(
                    "https://routes.googleapis.com/directions/v2:computeRoutes",
                    method="POST",
                    headers={"X-Goog-Api-Key": api_key},
                    body={"origin": {}},
                )

        message = str(raised.exception)
        self.assertIn("HTTP 403 Forbidden", message)
        self.assertIn("PERMISSION_DENIED", message)
        self.assertIn("Routes API", message)
        self.assertNotIn(api_key, message)
        self.assertIn("[REDACTED", message)

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
        result = server.complete_report(
            {"reportId": started["reportId"], "reportToken": started["reportToken"]},
            "different-network-client",
        )
        self.assertEqual(result["entrance"], "nisqually")
        self.assertGreaterEqual(result["waitSeconds"], 1)

    def test_report_completion_rejects_missing_token(self):
        started = server.start_report({"entrance": "nisqually"}, "test-client")
        with self.assertRaises(PermissionError):
            server.complete_report({"reportId": started["reportId"]}, "test-client")

    def test_conditions_exclude_legacy_nps_feed_records(self):
        server.upsert_condition(
            source="nps",
            source_event_id="legacy-alert",
            title="Legacy NPS feed alert",
            detail="Should not be returned",
            severity="warning",
            url="https://example.invalid",
        )
        payload = server.conditions_payload()
        self.assertFalse(any(alert.get("tag") == "NPS" for alert in payload["alerts"]))
        self.assertFalse(any("API" in alert.get("detail", "") for alert in payload["alerts"]))

    def test_accuracy_feedback_round_trip_and_admin_review(self):
        result = server.create_feedback(
            {
                "feedbackType": "accuracy",
                "category": "estimate-accuracy",
                "entrance": "nisqually",
                "displayedLowMinutes": 20,
                "displayedHighMinutes": 30,
                "displayedObservedAt": "2026-07-20T18:00:00Z",
                "actualWaitMinutes": 47,
                "gateArrivalAt": "2026-07-20T18:50:00Z",
                "message": "Queue began before the route origin.",
                "contactEmail": "visitor@example.com",
                "pagePath": "/",
            },
            "feedback-client",
        )
        self.assertTrue(result["accepted"])
        payload = server.feedback_admin_payload()
        self.assertEqual(payload["total"], 1)
        item = payload["submissions"][0]
        self.assertEqual(item["actualWaitMinutes"], 47)
        self.assertEqual(item["status"], "new")

        updated = server.update_feedback(
            result["feedbackId"],
            {"status": "calibration", "resolutionNotes": "Use during route validation."},
        )
        self.assertEqual(updated["status"], "calibration")
        filtered = server.feedback_admin_payload("calibration")
        self.assertEqual(filtered["total"], 1)

    def test_methodology_feedback_is_accepted(self):
        result = server.create_feedback(
            {
                "feedbackType": "general",
                "category": "methodology",
                "message": "Consider lowering report influence until field calibration is complete.",
                "pagePath": "/methodology.html",
            },
            "methodology-feedback-client",
        )
        self.assertTrue(result["accepted"])
        item = server.feedback_admin_payload()["submissions"][0]
        self.assertEqual(item["category"], "methodology")
        self.assertEqual(item["pagePath"], "/methodology.html")

    def test_general_feedback_requires_details(self):
        with self.assertRaises(ValueError):
            server.create_feedback(
                {"feedbackType": "general", "category": "website-problem", "message": ""},
                "feedback-client",
            )

    def test_feedback_honeypot_is_not_stored(self):
        result = server.create_feedback(
            {"feedbackType": "general", "message": "Bot message", "website": "spam.example"},
            "feedback-client",
        )
        self.assertTrue(result["accepted"])
        self.assertEqual(server.feedback_admin_payload()["total"], 0)

    def test_feedback_rate_limit_and_csv_export(self):
        with mock.patch.object(server, "FEEDBACK_RATE_LIMIT_PER_HOUR", 2):
            for number in range(2):
                server.create_feedback(
                    {
                        "feedbackType": "general",
                        "category": "feature-suggestion",
                        "message": "=2+2" if number == 0 else f"Suggestion {number}",
                    },
                    "feedback-client",
                )
            with self.assertRaises(PermissionError):
                server.create_feedback(
                    {"feedbackType": "general", "message": "One too many"},
                    "feedback-client",
                )
        csv_text = server.feedback_csv_bytes().decode("utf-8-sig")
        self.assertIn("'=2+2", csv_text)
        self.assertIn("Suggestion 1", csv_text)
        self.assertNotIn("anonymous_client_hash", csv_text)

    def test_health_payload_includes_freshness_and_storage_checks(self):
        payload = server.health_payload()
        self.assertTrue(payload["databaseWritable"])
        self.assertIn("nisqually", payload["entrances"])
        self.assertIn("diskFreeMegabytes", payload)
        self.assertNotIn("npsConfigured", payload)
        self.assertTrue(payload["requestLogsUseHashedClientIdentifiers"])
        self.assertIn("feedbackSubmissionsLast24Hours", payload)
        self.assertIn("unreviewedFeedbackSubmissions", payload)


if __name__ == "__main__":
    unittest.main()
