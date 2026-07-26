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
            conn.execute("delete from traffic_polyline_snapshots")
            conn.execute("delete from traffic_snapshots")
            conn.execute("delete from condition_events")
            conn.execute("delete from feedback_submissions")

    def test_nisqually_queue_v3_defaults(self):
        entrance = server.ENTRANCES["nisqually"]
        self.assertEqual(entrance["route_version"], "nisqually-queue-v3")
        self.assertAlmostEqual(entrance["origin"]["latitude"], 46.751415, places=6)
        self.assertAlmostEqual(entrance["origin"]["longitude"], -121.940160, places=6)
        self.assertAlmostEqual(entrance["destination"]["latitude"], 46.740813, places=6)
        self.assertAlmostEqual(entrance["destination"]["longitude"], -121.915494, places=6)
        self.assertEqual(entrance["configured_free_flow_seconds"], 180)

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

    def test_wait_uses_free_flow_baseline_not_google_static_duration(self):
        entry = server.ENTRANCES["nisqually"]
        original = entry["configured_free_flow_seconds"]
        try:
            entry["configured_free_flow_seconds"] = 600
            server.store_traffic_snapshot(
                "nisqually", server.utc_now(), 1800, 1500, 9000,
                "google-routes", {"test": True}, free_flow_baseline_seconds=600,
            )
            estimate = server.compute_estimate("nisqually")
        finally:
            entry["configured_free_flow_seconds"] = original
        self.assertEqual(estimate.traffic_delay_seconds, 1200)
        self.assertEqual(estimate.basis["traffic_delay_minutes"], 20.0)
        self.assertEqual(estimate.basis["google_historical_duration_minutes"], 25.0)

    def test_learned_baseline_uses_only_current_route_version(self):
        entry = server.ENTRANCES["nisqually"]
        original = entry["configured_free_flow_seconds"]
        try:
            entry["configured_free_flow_seconds"] = 720
            now = server.utc_now()
            # An old-route row must not influence the new corridor baseline.
            server.store_traffic_snapshot(
                "nisqually", now, 300, 300, 5000, "google-routes", {},
                route_version="legacy-short-route", free_flow_baseline_seconds=300,
            )
            for index, duration in enumerate([650, 660, 670, 680]):
                server.store_traffic_snapshot(
                    "nisqually", now + timedelta(seconds=index), duration, 700, 9000,
                    "google-routes", {}, route_version=entry["route_version"],
                    free_flow_baseline_seconds=720,
                )
            with mock.patch.object(server, "FREE_FLOW_LEARNING_MIN_SAMPLES", 4):
                baseline, source, count = server.learned_free_flow_baseline("nisqually")
        finally:
            entry["configured_free_flow_seconds"] = original
        self.assertEqual(baseline, 650)
        self.assertEqual(source, "learned-lower-decile")
        self.assertEqual(count, 4)

    def test_google_polyline_decoder_matches_reference_coordinates(self):
        points = server.decode_google_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
        self.assertEqual(len(points), 3)
        self.assertAlmostEqual(points[0][0], 38.5, places=5)
        self.assertAlmostEqual(points[0][1], -120.2, places=5)
        self.assertAlmostEqual(points[2][0], 43.252, places=5)
        self.assertAlmostEqual(points[2][1], -126.453, places=5)

    def test_polyline_scan_is_not_due_again_within_the_hour(self):
        with server.database() as conn:
            conn.execute(
                """
                insert into traffic_polyline_snapshots (
                  entrance_slug, observed_at, route_version, distance_meters,
                  slow_distance_meters, jam_distance_meters,
                  encoded_polyline, speed_intervals_json, raw_payload, created_at
                ) values ('nisqually', ?, ?, 1000, 0, 0, 'encoded', '[]', '{}', ?)
                """,
                (server.iso(), server.ENTRANCES["nisqually"]["route_version"], server.iso()),
            )
        with mock.patch.object(server, "ENABLE_TRAFFIC_POLYLINE", True):
            self.assertFalse(server.traffic_polyline_due("nisqually"))

    def test_gate_connected_congestion_ignores_unrelated_upstream_traffic(self):
        # Roughly 111 meters between each point at the equator.
        points = [(0.0, index / 1000) for index in range(8)]
        intervals = [
            {"endPolylinePointIndex": 2, "speed": "TRAFFIC_JAM"},
            {"startPolylinePointIndex": 2, "endPolylinePointIndex": 5, "speed": "NORMAL"},
            {"startPolylinePointIndex": 5, "endPolylinePointIndex": 7, "speed": "SLOW"},
        ]
        result = server.analyze_gate_connected_congestion(
            points, intervals, gate_connection_meters=300, normal_gap_meters=150,
        )
        self.assertEqual(result["queueStartIndex"], 5)
        self.assertGreater(result["queueDistanceMeters"], 200)
        self.assertGreater(result["slowDistanceMeters"], 200)
        self.assertEqual(result["jamDistanceMeters"], 0)

    def test_congestion_too_far_from_gate_is_not_reported_as_queue(self):
        points = [(0.0, index / 1000) for index in range(10)]
        intervals = [
            {"endPolylinePointIndex": 2, "speed": "TRAFFIC_JAM"},
            {"startPolylinePointIndex": 2, "endPolylinePointIndex": 9, "speed": "NORMAL"},
        ]
        result = server.analyze_gate_connected_congestion(
            points, intervals, gate_connection_meters=300, normal_gap_meters=150,
        )
        self.assertIsNone(result["queueStartIndex"])
        self.assertIsNone(result["queueDistanceMeters"])

    def test_traffic_polyline_request_uses_hourly_enterprise_fields(self):
        captured = []
        fake_route = {
            "distanceMeters": 1000,
            "polyline": {"encodedPolyline": "}boeF~zbjVAg@EmB`GWHlD"},
            "travelAdvisory": {"speedReadingIntervals": [
                {"endPolylinePointIndex": 1, "speed": "NORMAL"},
                {"startPolylinePointIndex": 1, "endPolylinePointIndex": 2, "speed": "SLOW"},
                {"startPolylinePointIndex": 2, "endPolylinePointIndex": 4, "speed": "NORMAL"},
            ]},
        }

        def fake_http_json(url, **kwargs):
            captured.append((url, kwargs))
            return {"routes": [fake_route]}

        with mock.patch.object(server, "GOOGLE_ROUTES_API_KEY", "test-key"), \
             mock.patch.object(server, "ENABLE_TRAFFIC_POLYLINE", True), \
             mock.patch.object(server, "traffic_polyline_due", return_value=True), \
             mock.patch.object(server, "http_json", side_effect=fake_http_json):
            errors = server.poll_google_traffic_polylines()

        self.assertEqual(errors, [])
        self.assertEqual(len(captured), 2)
        for _, kwargs in captured:
            self.assertEqual(kwargs["body"]["extraComputations"], ["TRAFFIC_ON_POLYLINE"])
            self.assertEqual(kwargs["body"]["polylineQuality"], "HIGH_QUALITY")
            self.assertIn("routes.polyline.encodedPolyline", kwargs["headers"]["X-Goog-FieldMask"])
            self.assertIn("routes.travelAdvisory.speedReadingIntervals", kwargs["headers"]["X-Goog-FieldMask"])

    def test_recent_polyline_queue_is_exposed_with_estimate(self):
        server.store_traffic_snapshot(
            "nisqually", server.utc_now(), 1500, 1000, 9000,
            "google-routes", {}, free_flow_baseline_seconds=720,
        )
        with server.database() as conn:
            conn.execute(
                """
                insert into traffic_polyline_snapshots (
                  entrance_slug, observed_at, route_version, distance_meters,
                  queue_start_lat, queue_start_lng, queue_distance_meters,
                  slow_distance_meters, jam_distance_meters,
                  congestion_start_index, congestion_end_index,
                  encoded_polyline, speed_intervals_json, raw_payload, created_at
                ) values ('nisqually', ?, ?, 9000, 46.75, -122.0, 3219,
                          1600, 1200, 3, 10, 'encoded', '[]', '{}', ?)
                """,
                (server.iso(), server.ENTRANCES["nisqually"]["route_version"], server.iso()),
            )
        item = next(entry for entry in server.current_payload()["entrances"] if entry["id"] == "nisqually")
        self.assertEqual(item["queueMiles"], 2.0)
        self.assertEqual(item["queueStart"]["latitude"], 46.75)

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

    # ------------------------------------------------------------------
    # v0.7.0 pre-launch hardening
    # ------------------------------------------------------------------

    def test_static_allowlist_excludes_project_files(self):
        for private in ("server.py", "README.md", "render.yaml", "Dockerfile", "tests/test_server.py"):
            self.assertNotIn(private, server.PUBLIC_STATIC_FILES)
        for public in ("index.html", "styles.css", "app.js", "privacy.html", "robots.txt"):
            self.assertIn(public, server.PUBLIC_STATIC_FILES)
            self.assertTrue((ROOT / public).is_file(), f"{public} is allowlisted but missing")

    def test_signal_band_is_capped_until_field_calibration(self):
        with mock.patch.object(server, "ESTIMATOR_FIELD_CALIBRATED", False):
            self.assertEqual(server.confidence_label(95), "Medium")
            self.assertEqual(server.confidence_label(60), "Medium")
            self.assertEqual(server.confidence_label(20), "Low")
        with mock.patch.object(server, "ESTIMATOR_FIELD_CALIBRATED", True):
            self.assertEqual(server.confidence_label(95), "High")

    def test_separate_devices_behind_one_network_can_each_report(self):
        shared_network = "shared-carrier-hash"
        for index in range(server.DEVICE_REPORT_LIMIT_PER_HOUR + 3):
            started = server.start_report(
                {"entrance": "nisqually", "deviceId": f"device-{index}"},
                shared_network,
            )
            self.assertTrue(started["reportId"])

    def test_one_device_is_still_rate_limited(self):
        for _ in range(server.DEVICE_REPORT_LIMIT_PER_HOUR):
            server.start_report({"entrance": "nisqually", "deviceId": "repeat-device"}, "network-a")
        with self.assertRaises(PermissionError):
            server.start_report({"entrance": "nisqually", "deviceId": "repeat-device"}, "network-b")

    def test_device_hash_is_stored_rather_than_the_raw_identifier(self):
        server.start_report({"entrance": "nisqually", "deviceId": "plain-device-value"}, "network-a")
        with server.database() as conn:
            row = conn.execute("select device_hash from wait_reports limit 1").fetchone()
        self.assertIsNotNone(row["device_hash"])
        self.assertNotEqual(row["device_hash"], "plain-device-value")
        self.assertEqual(len(row["device_hash"]), 64)

    def test_implausible_reports_are_excluded_from_the_estimate(self):
        rows = self._fake_report_rows([12.0, 14.0, 240.0, 0.2])
        plausible, high, low = server.filter_plausible_reports(rows, traffic_minutes=15.0)
        self.assertEqual([row["wait_seconds"] / 60 for row in plausible], [12.0, 14.0])
        self.assertEqual(len(high), 1)
        self.assertEqual(len(low), 1)

    def test_reports_are_kept_when_no_traffic_reference_exists(self):
        rows = self._fake_report_rows([12.0, 240.0])
        plausible, high, low = server.filter_plausible_reports(rows, traffic_minutes=None)
        self.assertEqual(len(plausible), 2)
        self.assertEqual((high, low), ([], []))

    def test_repeated_high_outliers_flag_a_queue_beyond_the_route_origin(self):
        observed = server.utc_now()
        server.store_traffic_snapshot("nisqually", observed, 900, 600, 8500, "google-routes", {})
        completed = server.iso(observed)
        with server.database() as conn:
            for index in range(3):
                conn.execute(
                    """
                    insert into wait_reports (
                      id, entrance_slug, anonymous_client_hash, device_hash, started_at,
                      completed_at, wait_seconds, confirmation_status, quality_score,
                      created_at, updated_at
                    ) values (?, 'nisqually', ?, ?, ?, ?, ?, 'completed', 80, ?, ?)
                    """,
                    (
                        f"outlier-{index}", f"client-{index}", f"device-{index}",
                        completed, completed, 70 * 60, completed, completed,
                    ),
                )
        estimate = server.compute_estimate("nisqually")
        self.assertTrue(estimate.basis["possible_queue_beyond_route_origin"])
        self.assertEqual(estimate.basis["community_reports_far_above_traffic_signal"], 3)
        self.assertEqual(estimate.basis["community_report_count"], 0)
        self.assertEqual(estimate.basis["calibration_status"], "uncalibrated")

    def test_public_health_view_hides_operational_detail(self):
        public = server.health_payload(detailed=False)
        for hidden in ("diskFreeMegabytes", "database", "poller", "lastBackupAt", "databaseError"):
            self.assertNotIn(hidden, public)
        self.assertIn("status", public)
        self.assertIn("nisqually", public["entrances"])
        self.assertEqual(set(public["entrances"]["nisqually"]), {"freshness", "ageMinutes", "entranceClosed"})

    def test_no_inline_style_attributes_under_a_strict_csp(self):
        """Inline style attributes are silently dropped by the CSP.

        This is not a theoretical concern: the planning chart set bar heights
        with style="height:NNpx", and adding the policy flattened every bar to
        its 6px minimum while the numbers above them stayed correct. Server
        tests cannot see rendering, so the guard lives here instead.
        """
        policy = server.CONTENT_SECURITY_POLICY
        self.assertIn("style-src 'self'", policy)
        self.assertNotIn("unsafe-inline", policy)
        offenders = []
        for name in sorted(server.PUBLIC_STATIC_FILES):
            path = ROOT / name
            if path.suffix not in {".html", ".js"} or not path.is_file():
                continue
            for number, line in enumerate(path.read_text().splitlines(), start=1):
                if 'style="' in line or "style='" in line:
                    offenders.append(f"{name}:{number}")
        self.assertEqual(offenders, [], f"inline style attributes will be blocked: {offenders}")

    def test_retention_clears_every_report_identifier(self):
        """The device hash is a new identifier and must expire with the others."""
        old = server.iso(server.utc_now() - timedelta(days=server.REPORT_IDENTIFIER_RETENTION_DAYS + 1))
        with server.database() as conn:
            conn.execute(
                """
                insert into wait_reports (
                  id, entrance_slug, anonymous_client_hash, report_secret_hash, device_hash,
                  started_at, completed_at, wait_seconds, confirmation_status, quality_score,
                  created_at, updated_at
                ) values ('aged', 'nisqually', 'client', 'secret', 'device',
                          ?, ?, 900, 'completed', 80, ?, ?)
                """,
                (old, old, old, old),
            )
        server.cleanup_old_reports()
        with server.database() as conn:
            row = conn.execute("select * from wait_reports where id='aged'").fetchone()
        self.assertIsNone(row["anonymous_client_hash"])
        self.assertIsNone(row["report_secret_hash"])
        self.assertIsNone(row["device_hash"])
        # The observation itself is retained; only the identifiers are removed.
        self.assertEqual(row["wait_seconds"], 900)

    def test_live_server_head_allowlist_and_headers(self):
        """End-to-end check over a real socket.

        Header and allowlist behaviour cannot be verified by calling the payload
        functions directly, and this is the layer where a public deployment is
        actually exposed.
        """
        import threading
        import urllib.request
        from http.server import ThreadingHTTPServer

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        try:
            # Uptime monitors probe with HEAD.
            request = urllib.request.Request(f"{base}/", method="HEAD")
            with urllib.request.urlopen(request, timeout=10) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.read(), b"")
                self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
                self.assertEqual(response.headers["X-Frame-Options"], "DENY")
                self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")

            with urllib.request.urlopen(f"{base}/", timeout=10) as response:
                self.assertIn(b"Rainier Gate Waits", response.read())

            for private in ("/server.py", "/README.md", "/render.yaml", "/tests/test_server.py"):
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(f"{base}{private}", timeout=10)
                self.assertEqual(caught.exception.code, 404, private)
        finally:
            httpd.shutdown()
            httpd.server_close()

    def _fake_report_rows(self, minutes: list[float]):
        completed = server.iso(server.utc_now())
        with server.database() as conn:
            for index, value in enumerate(minutes):
                conn.execute(
                    """
                    insert into wait_reports (
                      id, entrance_slug, anonymous_client_hash, device_hash, started_at,
                      completed_at, wait_seconds, confirmation_status, quality_score,
                      created_at, updated_at
                    ) values (?, 'nisqually', ?, ?, ?, ?, ?, 'completed', 80, ?, ?)
                    """,
                    (
                        f"fake-{index}", f"client-{index}", f"device-{index}",
                        completed, completed, round(value * 60), completed, completed,
                    ),
                )
            return conn.execute(
                "select * from wait_reports order by cast(substr(id, 6) as integer)"
            ).fetchall()



if __name__ == "__main__":
    unittest.main()
