#!/usr/bin/env python3
"""Rainier Gate Waits local MVP server.

Serves the static prototype, persists traffic snapshots and visitor wait reports in
SQLite, exposes JSON endpoints, and optionally polls Google Routes, NPS alerts,
and WSDOT alerts when API keys are configured.

No third-party Python packages are required.
"""

from __future__ import annotations

import hashlib
import json
import math
import mimetypes
import os
import random
import re
import secrets
import sqlite3
import statistics
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("RAINIER_DB_PATH", ROOT / "rainier_waits.sqlite3"))
HOST = os.environ.get("RAINIER_HOST", "127.0.0.1")
PORT = int(os.environ.get("RAINIER_PORT") or os.environ.get("PORT", "8000"))
POLL_SECONDS = max(60, int(os.environ.get("POLL_INTERVAL_SECONDS", "900")))
POLL_START_HOUR_LOCAL = max(0, min(23, int(os.environ.get("POLL_START_HOUR_LOCAL", "6"))))
POLL_END_HOUR_LOCAL = max(0, min(23, int(os.environ.get("POLL_END_HOUR_LOCAL", "20"))))
ENABLE_BACKGROUND_POLLING = os.environ.get("ENABLE_BACKGROUND_POLLING", "true").lower() not in {"0", "false", "no"}
TRUST_PROXY_HEADERS = os.environ.get("TRUST_PROXY_HEADERS", "false").lower() in {"1", "true", "yes"}
GOOGLE_ROUTES_API_KEY = os.environ.get("GOOGLE_ROUTES_API_KEY", "").strip()
NPS_API_KEY = os.environ.get("NPS_API_KEY", "").strip()
WSDOT_ACCESS_CODE = os.environ.get("WSDOT_ACCESS_CODE", "").strip()
ADMIN_TOKEN = os.environ.get("RAINIER_ADMIN_TOKEN", "").strip()
HASH_SECRET = os.environ.get("RAINIER_HASH_SECRET", secrets.token_hex(16))

UTC = timezone.utc
PACIFIC = ZoneInfo("America/Los_Angeles")

# These coordinates are suitable for a starter prototype, not a survey-grade
# production route definition. Verify each approach segment in the traffic
# provider's route demo before public launch.
ENTRANCES: dict[str, dict[str, Any]] = {
    "nisqually": {
        "slug": "nisqually",
        "name": "Nisqually Entrance",
        "approach": "From Ashford via WA-706",
        "origin": {"latitude": 46.7580, "longitude": -122.0080},
        "destination": {"latitude": 46.7508, "longitude": -121.9175},
        "route": "706",
        "seasonal": False,
    },
    "white-river": {
        "slug": "white-river",
        "name": "White River Entrance",
        "approach": "From Enumclaw via WA-410",
        "origin": {"latitude": 46.9100, "longitude": -121.6040},
        "destination": {"latitude": 46.9023, "longitude": -121.5358},
        "route": "410",
        "seasonal": True,
    },
}

BASE_FORECASTS: dict[str, list[tuple[int, int, int]]] = {
    "nisqually": [
        (6, 0, 5), (7, 0, 8), (8, 5, 15), (9, 10, 25), (10, 25, 45), (11, 40, 65),
        (12, 45, 75), (13, 45, 70), (14, 35, 60), (15, 25, 45), (16, 15, 30), (17, 5, 18),
    ],
    "white-river": [
        (6, 0, 5), (7, 0, 5), (8, 0, 10), (9, 5, 15), (10, 10, 25), (11, 20, 40),
        (12, 25, 45), (13, 25, 45), (14, 20, 35), (15, 12, 25), (16, 5, 15), (17, 0, 10),
    ],
}

SCHEMA_SQL = """
pragma journal_mode = WAL;
pragma foreign_keys = ON;

create table if not exists entrances (
  slug text primary key,
  name text not null,
  approach text not null,
  origin_lat real not null,
  origin_lng real not null,
  destination_lat real not null,
  destination_lng real not null,
  route text,
  seasonal integer not null default 0,
  active integer not null default 1,
  created_at text not null,
  updated_at text not null
);

create table if not exists traffic_snapshots (
  id integer primary key autoincrement,
  entrance_slug text not null references entrances(slug),
  observed_at text not null,
  traffic_duration_seconds integer not null,
  static_duration_seconds integer not null,
  distance_meters integer,
  provider text not null,
  raw_payload text,
  created_at text not null
);
create index if not exists traffic_snapshots_entrance_time_idx
  on traffic_snapshots (entrance_slug, observed_at desc);

create table if not exists condition_events (
  id integer primary key autoincrement,
  entrance_slug text references entrances(slug),
  source text not null,
  source_event_id text,
  severity text not null,
  title text not null,
  detail text,
  url text,
  observed_at text not null,
  starts_at text,
  ends_at text,
  is_active integer not null default 1,
  raw_payload text,
  unique(source, source_event_id)
);

create table if not exists wait_reports (
  id text primary key,
  entrance_slug text not null references entrances(slug),
  anonymous_client_hash text,
  started_at text not null,
  completed_at text,
  wait_seconds integer,
  queue_entry_lat real,
  queue_entry_lng real,
  queue_entry_accuracy_meters real,
  completion_lat real,
  completion_lng real,
  confirmation_status text not null default 'started',
  quality_score integer,
  created_at text not null,
  updated_at text not null
);
create index if not exists wait_reports_entrance_completed_idx
  on wait_reports (entrance_slug, completed_at desc);

create table if not exists wait_estimates (
  id integer primary key autoincrement,
  entrance_slug text not null references entrances(slug),
  estimated_at text not null,
  low_minutes integer not null,
  median_minutes integer not null,
  high_minutes integer not null,
  queue_distance_miles real,
  trend text not null,
  confidence_score integer not null,
  confidence_level text not null,
  recent_report_count integer not null default 0,
  traffic_delay_seconds integer,
  data_mode text not null,
  basis_json text not null,
  model_version text not null
);
create index if not exists wait_estimates_entrance_time_idx
  on wait_estimates (entrance_slug, estimated_at desc);
"""


@dataclass(frozen=True)
class Estimate:
    low: int
    median: int
    high: int
    queue_distance_miles: float | None
    trend: str
    confidence_score: int
    confidence_level: str
    recent_report_count: int
    traffic_delay_seconds: int | None
    data_mode: str
    basis: dict[str, Any]


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def iso(dt: datetime | None = None) -> str:
    return (dt or utc_now()).astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def within_polling_window(at: datetime | None = None) -> bool:
    """Return whether scheduled polling should run at the given local hour.

    Equal start and end hours mean all-day polling. The window may also wrap
    across midnight, though the public pilot uses a daytime window.
    """
    hour = (at or utc_now()).astimezone(PACIFIC).hour
    if POLL_START_HOUR_LOCAL == POLL_END_HOUR_LOCAL:
        return True
    if POLL_START_HOUR_LOCAL < POLL_END_HOUR_LOCAL:
        return POLL_START_HOUR_LOCAL <= hour < POLL_END_HOUR_LOCAL
    return hour >= POLL_START_HOUR_LOCAL or hour < POLL_END_HOUR_LOCAL


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = ON")
    return conn


@contextmanager
def database():
    """Provide a transactional SQLite connection and always close it."""
    conn = connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def initialize_database() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    now = iso()
    with database() as conn:
        conn.executescript(SCHEMA_SQL)
        conn.execute("update entrances set active=0, updated_at=?", (now,))
        for entry in ENTRANCES.values():
            conn.execute(
                """
                insert into entrances (
                  slug, name, approach, origin_lat, origin_lng,
                  destination_lat, destination_lng, route, seasonal,
                  active, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                on conflict(slug) do update set
                  name=excluded.name,
                  approach=excluded.approach,
                  origin_lat=excluded.origin_lat,
                  origin_lng=excluded.origin_lng,
                  destination_lat=excluded.destination_lat,
                  destination_lng=excluded.destination_lng,
                  route=excluded.route,
                  seasonal=excluded.seasonal,
                  active=1,
                  updated_at=excluded.updated_at
                """,
                (
                    entry["slug"], entry["name"], entry["approach"],
                    entry["origin"]["latitude"], entry["origin"]["longitude"],
                    entry["destination"]["latitude"], entry["destination"]["longitude"],
                    entry["route"], int(entry["seasonal"]), now, now,
                ),
            )


def parse_google_duration(value: str | None) -> int:
    if not value or not value.endswith("s"):
        raise ValueError(f"Invalid Google duration: {value!r}")
    return max(0, round(float(value[:-1])))


HTTP_ERROR_BODY_LIMIT = 4000


def redact_secrets(text: str, sensitive_values: list[str] | tuple[str, ...] = ()) -> str:
    '''Remove credentials from diagnostic text before it reaches application logs.'''
    redacted = text
    known_values = {
        value for value in (
            *sensitive_values,
            GOOGLE_ROUTES_API_KEY,
            NPS_API_KEY,
            WSDOT_ACCESS_CODE,
            ADMIN_TOKEN,
        ) if value and len(value) >= 4
    }
    for value in sorted(known_values, key=len, reverse=True):
        redacted = redacted.replace(value, '[REDACTED]')

    # Defense in depth for Google-style API keys and credentials echoed as fields.
    redacted = re.sub(r'AIza[0-9A-Za-z_-]{20,}', '[REDACTED_GOOGLE_API_KEY]', redacted)
    redacted = re.sub(
        r'''(?ix)(["']?(?:api[_-]?key|access[_-]?code|authorization|token|secret)["']?\s*[:=]\s*["']?)([^"'\s&,}]+)''',
        r'\1[REDACTED]',
        redacted,
    )
    return redacted


def format_http_error(
    exc: urllib.error.HTTPError,
    *,
    sensitive_values: list[str] | tuple[str, ...] = (),
) -> str:
    '''Return a single-line, size-limited, credential-safe HTTP error message.'''
    try:
        raw = exc.read(HTTP_ERROR_BODY_LIMIT + 1)
    except Exception:
        raw = b''
    truncated = len(raw) > HTTP_ERROR_BODY_LIMIT
    raw = raw[:HTTP_ERROR_BODY_LIMIT]
    body_text = raw.decode('utf-8', errors='replace').strip()

    if body_text:
        try:
            body_text = json.dumps(
                json.loads(body_text),
                ensure_ascii=False,
                separators=(',', ':'),
            )
        except json.JSONDecodeError:
            body_text = ' '.join(body_text.split())
        body_text = redact_secrets(body_text, sensitive_values)
        if truncated:
            body_text += ' …[truncated]'
    else:
        body_text = 'no response body'

    reason = str(exc.reason or 'HTTP error')
    return f'HTTP {exc.code} {reason}: {body_text}'


def http_json(
    url: str,
    *,
    method: str = 'GET',
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout: int = 20,
) -> Any:
    payload = None if body is None else json.dumps(body).encode('utf-8')
    request = urllib.request.Request(url, data=payload, method=method)
    request.add_header('User-Agent', 'RainierGateWaits/0.4 (+public pilot)')
    if body is not None:
        request.add_header('Content-Type', 'application/json')
    request_headers = headers or {}
    for key, value in request_headers.items():
        request.add_header(key, value)

    sensitive_values = [
        value for key, value in request_headers.items()
        if any(marker in key.lower() for marker in ('key', 'token', 'authorization', 'secret', 'code'))
    ]
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(format_http_error(exc, sensitive_values=sensitive_values)) from exc


def store_traffic_snapshot(
    entrance_slug: str,
    observed_at: datetime,
    traffic_seconds: int,
    static_seconds: int,
    distance_meters: int | None,
    provider: str,
    raw_payload: Any,
) -> None:
    with database() as conn:
        conn.execute(
            """
            insert into traffic_snapshots (
              entrance_slug, observed_at, traffic_duration_seconds,
              static_duration_seconds, distance_meters, provider,
              raw_payload, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entrance_slug, iso(observed_at), traffic_seconds, static_seconds,
                distance_meters, provider, json.dumps(raw_payload, separators=(",", ":")), iso(),
            ),
        )


def poll_google_routes() -> list[str]:
    if not GOOGLE_ROUTES_API_KEY:
        return []
    errors: list[str] = []
    endpoint = "https://routes.googleapis.com/directions/v2:computeRoutes"
    field_mask = "routes.duration,routes.staticDuration,routes.distanceMeters"
    for slug, entry in ENTRANCES.items():
        body = {
            "origin": {"location": {"latLng": entry["origin"]}},
            "destination": {"location": {"latLng": entry["destination"]}},
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE_OPTIMAL",
            "computeAlternativeRoutes": False,
            "languageCode": "en-US",
            "units": "IMPERIAL",
        }
        try:
            data = http_json(
                endpoint,
                method="POST",
                headers={
                    "X-Goog-Api-Key": GOOGLE_ROUTES_API_KEY,
                    "X-Goog-FieldMask": field_mask,
                },
                body=body,
            )
            route = data["routes"][0]
            store_traffic_snapshot(
                slug,
                utc_now(),
                parse_google_duration(route["duration"]),
                parse_google_duration(route["staticDuration"]),
                route.get("distanceMeters"),
                "google-routes",
                data,
            )
        except Exception as exc:  # keep polling the other entrances
            errors.append(f"{slug}: {exc}")
    return errors


def day_type_for(dt: datetime) -> str:
    # Lightweight default. A production system should use a maintained holiday calendar.
    return "weekend" if dt.weekday() >= 5 else "weekday"


def template_wait(slug: str, dt: datetime) -> tuple[int, int]:
    local_hour = dt.astimezone(PACIFIC).hour
    rows = BASE_FORECASTS[slug]
    nearest = min(rows, key=lambda row: abs(row[0] - local_hour))
    multiplier = 0.62 if day_type_for(dt) == "weekday" else 1.0
    seasonal = 1.0 if 5 <= dt.month <= 9 else 0.25
    return round(nearest[1] * multiplier * seasonal), round(nearest[2] * multiplier * seasonal)


def seed_demo_snapshots() -> None:
    """Insert transparent synthetic observations when no Google key is configured."""
    now = utc_now()
    rng = random.Random(int(now.timestamp() // POLL_SECONDS))
    for slug in ENTRANCES:
        low, high = template_wait(slug, now)
        center = (low + high) / 2
        delay_minutes = max(0, center + rng.uniform(-3, 3))
        static_seconds = {"nisqually": 530, "white-river": 430}[slug]
        traffic_seconds = static_seconds + round(delay_minutes * 60)
        distance = {"nisqually": 8500, "white-river": 6200}[slug]
        store_traffic_snapshot(
            slug, now, traffic_seconds, static_seconds, distance,
            "demo-synthetic", {"notice": "Synthetic observation generated by demo mode"},
        )


def upsert_condition(
    *, source: str, source_event_id: str, title: str, detail: str,
    severity: str = "info", entrance_slug: str | None = None,
    url: str | None = None, starts_at: str | None = None,
    ends_at: str | None = None, raw_payload: Any = None,
) -> None:
    with database() as conn:
        conn.execute(
            """
            insert into condition_events (
              entrance_slug, source, source_event_id, severity, title, detail,
              url, observed_at, starts_at, ends_at, is_active, raw_payload
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            on conflict(source, source_event_id) do update set
              entrance_slug=excluded.entrance_slug,
              severity=excluded.severity,
              title=excluded.title,
              detail=excluded.detail,
              url=excluded.url,
              observed_at=excluded.observed_at,
              starts_at=excluded.starts_at,
              ends_at=excluded.ends_at,
              is_active=1,
              raw_payload=excluded.raw_payload
            """,
            (
                entrance_slug, source, source_event_id, severity, title, detail,
                url, iso(), starts_at, ends_at,
                json.dumps(raw_payload, separators=(",", ":")) if raw_payload is not None else None,
            ),
        )


def poll_nps_alerts() -> list[str]:
    if not NPS_API_KEY:
        return []
    try:
        url = "https://developer.nps.gov/api/v1/alerts?parkCode=mora&limit=50"
        data = http_json(url, headers={"Authorization": NPS_API_KEY})
        seen: set[str] = set()
        for item in data.get("data", []):
            event_id = str(item.get("id") or hashlib.sha256((item.get("title", "") + item.get("description", "")).encode()).hexdigest()[:24])
            seen.add(event_id)
            category = str(item.get("category", "Information"))
            severity = "warning" if category.lower() in {"danger", "caution", "closure"} else "info"
            upsert_condition(
                source="nps", source_event_id=event_id,
                title=item.get("title") or "Mount Rainier alert",
                detail=strip_html(item.get("description") or ""),
                severity=severity, url=item.get("url"), raw_payload=item,
            )
        with database() as conn:
            if seen:
                placeholders = ",".join("?" for _ in seen)
                conn.execute(
                    f"update condition_events set is_active=0 where source='nps' and source_event_id not in ({placeholders})",
                    tuple(seen),
                )
        return []
    except Exception as exc:
        return [str(exc)]


def poll_wsdot_alerts() -> list[str]:
    if not WSDOT_ACCESS_CODE:
        return []
    try:
        params = urllib.parse.urlencode({"AccessCode": WSDOT_ACCESS_CODE})
        url = f"https://wsdot.wa.gov/Traffic/api/HighwayAlerts/HighwayAlertsREST.svc/GetAlertsAsJson?{params}"
        data = http_json(url)
        relevant_routes = {entry["route"] for entry in ENTRANCES.values()}
        for item in data if isinstance(data, list) else []:
            locations = [item.get("StartRoadwayLocation") or {}, item.get("EndRoadwayLocation") or {}]
            road_text = " ".join(str(loc.get("RoadName", "")) for loc in locations)
            headline = str(item.get("HeadlineDescription", ""))
            combined = f"{road_text} {headline}"
            matched_route = next((route for route in relevant_routes if re.search(rf"\b(?:SR\s*)?{re.escape(route)}\b", combined, re.I)), None)
            if not matched_route:
                continue
            slug = next((s for s, entry in ENTRANCES.items() if entry["route"] == matched_route), None)
            event_id = str(item.get("AlertID") or hashlib.sha256(combined.encode()).hexdigest()[:24])
            upsert_condition(
                source="wsdot", source_event_id=event_id, entrance_slug=slug,
                title=headline or f"WSDOT alert on SR {matched_route}",
                detail=str(item.get("ExtendedDescription", "")),
                severity="warning", raw_payload=item,
                starts_at=normalize_wsdot_date(item.get("StartTime")),
                ends_at=normalize_wsdot_date(item.get("EndTime")),
            )
        return []
    except Exception as exc:
        return [str(exc)]


def normalize_wsdot_date(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    match = re.search(r"/Date\((\d+)", text)
    if match:
        return iso(datetime.fromtimestamp(int(match.group(1)) / 1000, tz=UTC))
    try:
        return iso(parse_iso(text))
    except Exception:
        return None


def strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", text).strip()


def get_recent_snapshots(conn: sqlite3.Connection, slug: str, minutes: int = 90) -> list[sqlite3.Row]:
    cutoff = iso(utc_now() - timedelta(minutes=minutes))
    return conn.execute(
        """
        select * from traffic_snapshots
        where entrance_slug=? and observed_at>=?
        order by observed_at desc
        limit 36
        """,
        (slug, cutoff),
    ).fetchall()


def get_recent_reports(conn: sqlite3.Connection, slug: str, minutes: int = 60) -> list[sqlite3.Row]:
    cutoff = iso(utc_now() - timedelta(minutes=minutes))
    return conn.execute(
        """
        select * from wait_reports
        where entrance_slug=? and completed_at>=? and quality_score>=50
        order by completed_at desc
        limit 30
        """,
        (slug, cutoff),
    ).fetchall()


def confidence_label(score: int) -> str:
    if score >= 80:
        return "High"
    if score >= 55:
        return "Medium"
    return "Low"


def calculate_trend(snapshots: list[sqlite3.Row]) -> str:
    if len(snapshots) < 3:
        return "Unclear"
    newest = [max(0, row["traffic_duration_seconds"] - row["static_duration_seconds"]) / 60 for row in snapshots[:2]]
    older = [max(0, row["traffic_duration_seconds"] - row["static_duration_seconds"]) / 60 for row in snapshots[-2:]]
    delta = statistics.mean(newest) - statistics.mean(older)
    if delta >= 5:
        return "Rising"
    if delta <= -5:
        return "Falling"
    return "Stable"


def compute_estimate(slug: str) -> Estimate:
    with database() as conn:
        snapshots = get_recent_snapshots(conn, slug)
        reports = get_recent_reports(conn, slug)

    latest = snapshots[0] if snapshots else None
    traffic_delay = None
    traffic_age_minutes = None
    provider = None
    if latest:
        traffic_delay = max(0, latest["traffic_duration_seconds"] - latest["static_duration_seconds"])
        traffic_age_minutes = max(0, int((utc_now() - parse_iso(latest["observed_at"])).total_seconds() / 60))
        provider = latest["provider"]

    report_minutes = [row["wait_seconds"] / 60 for row in reports if row["wait_seconds"] is not None]
    report_median = statistics.median(report_minutes) if report_minutes else None
    traffic_minutes = traffic_delay / 60 if traffic_delay is not None else None

    if report_median is not None and traffic_minutes is not None:
        report_weight = 0.65 if len(report_minutes) >= 3 else 0.45
        center = report_median * report_weight + traffic_minutes * (1 - report_weight)
    elif report_median is not None:
        center = report_median
    elif traffic_minutes is not None:
        center = traffic_minutes
    else:
        low, high = template_wait(slug, utc_now())
        center = (low + high) / 2

    spread = 8.0
    if len(report_minutes) >= 3:
        spread = 4.0
    elif len(report_minutes) >= 1:
        spread = 6.0
    if len(report_minutes) >= 2:
        spread += min(12, statistics.pstdev(report_minutes))
    if traffic_age_minutes is not None and traffic_age_minutes > 10:
        spread += min(12, (traffic_age_minutes - 10) / 2)

    low = max(0, int(math.floor((center - spread) / 5) * 5))
    high = max(low + 5, int(math.ceil((center + spread) / 5) * 5))
    median = max(0, int(round(center / 5) * 5))

    freshness_points = 0
    if traffic_age_minutes is not None:
        freshness_points = max(0, 25 - max(0, traffic_age_minutes - 5) * 2)
    report_points = min(30, len(report_minutes) * 10)
    if len(report_minutes) >= 2:
        disagreement = statistics.pstdev(report_minutes)
        agreement_points = max(0, round(20 - disagreement * 1.5))
    elif len(report_minutes) == 1:
        agreement_points = 10
    else:
        agreement_points = 0
    incident_points = 15  # reduced later when incident-overlap logic becomes spatial
    history_points = 10 if len(snapshots) >= 3 else 4
    score = max(0, min(100, freshness_points + report_points + agreement_points + incident_points + history_points))

    data_mode = "live" if provider == "google-routes" else "demo"
    if provider == "google-routes" and report_minutes:
        data_mode = "live+reports"
    elif provider == "demo-synthetic" and report_minutes:
        data_mode = "demo+reports"

    queue_miles = None
    if traffic_minutes is not None:
        # Coarse display proxy only. Ground-truth queue-start coordinates should replace this.
        queue_miles = round(max(0, traffic_minutes) / 14, 1)

    basis = {
        "traffic_provider": provider,
        "traffic_age_minutes": traffic_age_minutes,
        "traffic_delay_minutes": round(traffic_minutes, 1) if traffic_minutes is not None else None,
        "verified_report_median_minutes": round(report_median, 1) if report_median is not None else None,
        "verified_report_count": len(report_minutes),
        "coordinate_notice": "Starter approach coordinates require field verification before production.",
    }
    return Estimate(
        low=low,
        median=median,
        high=high,
        queue_distance_miles=queue_miles,
        trend=calculate_trend(snapshots),
        confidence_score=score,
        confidence_level=confidence_label(score),
        recent_report_count=len(report_minutes),
        traffic_delay_seconds=traffic_delay,
        data_mode=data_mode,
        basis=basis,
    )


def persist_estimate(slug: str, estimate: Estimate) -> None:
    with database() as conn:
        conn.execute(
            """
            insert into wait_estimates (
              entrance_slug, estimated_at, low_minutes, median_minutes,
              high_minutes, queue_distance_miles, trend, confidence_score,
              confidence_level, recent_report_count, traffic_delay_seconds,
              data_mode, basis_json, model_version
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                slug, iso(), estimate.low, estimate.median, estimate.high,
                estimate.queue_distance_miles, estimate.trend,
                estimate.confidence_score, estimate.confidence_level,
                estimate.recent_report_count, estimate.traffic_delay_seconds,
                estimate.data_mode, json.dumps(estimate.basis, separators=(",", ":")),
                "mvp-heuristic-0.4",
            ),
        )


def poll_all() -> dict[str, Any]:
    started = utc_now()
    errors: dict[str, list[str]] = {}
    if GOOGLE_ROUTES_API_KEY:
        google_errors = poll_google_routes()
        if google_errors:
            errors["google_routes"] = google_errors
    else:
        seed_demo_snapshots()
    nps_errors = poll_nps_alerts()
    if nps_errors:
        errors["nps"] = nps_errors
    wsdot_errors = poll_wsdot_alerts()
    if wsdot_errors:
        errors["wsdot"] = wsdot_errors
    for slug in ENTRANCES:
        persist_estimate(slug, compute_estimate(slug))
    return {"started_at": iso(started), "completed_at": iso(), "errors": errors}


def current_payload() -> dict[str, Any]:
    items = []
    modes = set()
    with database() as conn:
        for slug, entry in ENTRANCES.items():
            estimate = compute_estimate(slug)
            modes.add(estimate.data_mode)
            latest = conn.execute(
                "select observed_at from traffic_snapshots where entrance_slug=? order by observed_at desc limit 1",
                (slug,),
            ).fetchone()
            observed_at = latest["observed_at"] if latest else None
            age_minutes = None
            if observed_at:
                age_minutes = max(0, int((utc_now() - parse_iso(observed_at)).total_seconds() / 60))
            status = "severe" if estimate.high >= 45 else "moderate" if estimate.high >= 20 else "clear"
            items.append({
                "id": slug,
                "name": entry["name"],
                "approach": entry["approach"],
                "min": estimate.low,
                "median": estimate.median,
                "max": estimate.high,
                "queueMiles": estimate.queue_distance_miles,
                "trend": estimate.trend,
                "confidence": estimate.confidence_level,
                "confidenceScore": estimate.confidence_score,
                "reports": estimate.recent_report_count,
                "updatedMinutes": age_minutes,
                "observedAt": observed_at,
                "status": status,
                "statusLabel": {"severe": "Heavy delay", "moderate": "Moderate delay", "clear": "Little delay"}[status],
                "dataMode": estimate.data_mode,
                "basis": estimate.basis,
                "seasonal": entry["seasonal"],
            })
    global_mode = "live" if modes and all(mode.startswith("live") for mode in modes) else "demo" if modes and all(mode.startswith("demo") for mode in modes) else "mixed"
    return {
        "generatedAt": iso(),
        "dataMode": global_mode,
        "pollIntervalSeconds": POLL_SECONDS,
        "entrances": items,
    }


def conditions_payload() -> dict[str, Any]:
    with database() as conn:
        rows = conn.execute(
            """
            select * from condition_events
            where is_active=1
            order by case severity when 'danger' then 0 when 'warning' then 1 else 2 end,
                     observed_at desc
            limit 20
            """
        ).fetchall()
    alerts = [
        {
            "tag": row["source"].upper(),
            "title": row["title"],
            "detail": row["detail"],
            "severity": row["severity"],
            "entrance": row["entrance_slug"],
            "url": row["url"],
            "observedAt": row["observed_at"],
        }
        for row in rows
    ]
    if not GOOGLE_ROUTES_API_KEY:
        alerts.insert(0, {
            "tag": "DEMO MODE",
            "title": "Traffic observations are synthetic",
            "detail": "Add GOOGLE_ROUTES_API_KEY to activate traffic-aware approach measurements.",
            "severity": "info",
            "entrance": None,
            "url": None,
            "observedAt": iso(),
        })
    if not NPS_API_KEY:
        alerts.append({
            "tag": "NPS FEED",
            "title": "Official park alerts are not connected",
            "detail": "Add NPS_API_KEY to retrieve Mount Rainier alerts from the NPS API.",
            "severity": "info",
            "entrance": None,
            "url": None,
            "observedAt": iso(),
        })
    return {"generatedAt": iso(), "alerts": alerts[:20]}


def forecast_payload(slug: str, date_text: str | None, day_type: str | None) -> dict[str, Any]:
    if slug not in ENTRANCES:
        raise KeyError("Unknown entrance")
    try:
        date_value = datetime.strptime(date_text, "%Y-%m-%d") if date_text else utc_now()
    except ValueError as exc:
        raise ValueError("date must use YYYY-MM-DD") from exc
    resolved_day_type = day_type if day_type in {"weekday", "weekend", "holiday"} else day_type_for(date_value)
    multiplier = {"weekday": 0.62, "weekend": 1.0, "holiday": 1.25}[resolved_day_type]
    month_multiplier = 1.0 if 5 <= date_value.month <= 9 else 0.35
    rows = []
    for hour, low, high in BASE_FORECASTS[slug]:
        rows.append({
            "hour": hour,
            "low": round(low * multiplier * month_multiplier),
            "high": round(high * multiplier * month_multiplier),
        })
    return {
        "entrance": slug,
        "date": date_value.strftime("%Y-%m-%d"),
        "dayType": resolved_day_type,
        "forecastMode": "seasonal-template",
        "notice": "Planning ranges are templates until sufficient verified historical waits are collected.",
        "hours": rows,
    }


def history_payload(slug: str, hours: int) -> dict[str, Any]:
    if slug not in ENTRANCES:
        raise KeyError("Unknown entrance")
    hours = min(max(hours, 1), 168)
    cutoff = iso(utc_now() - timedelta(hours=hours))
    with database() as conn:
        rows = conn.execute(
            """
            select observed_at, traffic_duration_seconds, static_duration_seconds,
                   distance_meters, provider
            from traffic_snapshots
            where entrance_slug=? and observed_at>=?
            order by observed_at asc
            """,
            (slug, cutoff),
        ).fetchall()
    return {
        "entrance": slug,
        "hours": hours,
        "observations": [
            {
                "observedAt": row["observed_at"],
                "trafficDurationSeconds": row["traffic_duration_seconds"],
                "staticDurationSeconds": row["static_duration_seconds"],
                "delayMinutes": round(max(0, row["traffic_duration_seconds"] - row["static_duration_seconds"]) / 60, 1),
                "distanceMeters": row["distance_meters"],
                "provider": row["provider"],
            }
            for row in rows
        ],
    }


def client_hash(ip: str, user_agent: str) -> str:
    date_key = utc_now().strftime("%Y-%m-%d")
    raw = f"{HASH_SECRET}|{date_key}|{ip}|{user_agent}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def rounded_coordinate(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    return round(number, 3)


def start_report(payload: dict[str, Any], client: str) -> dict[str, Any]:
    slug = str(payload.get("entrance") or "")
    if slug not in ENTRANCES:
        raise ValueError("Select a valid entrance")
    with database() as conn:
        recent_count = conn.execute(
            "select count(*) as count from wait_reports where anonymous_client_hash=? and created_at>=?",
            (client, iso(utc_now() - timedelta(hours=1))),
        ).fetchone()["count"]
        if recent_count >= 5:
            raise PermissionError("Too many report starts from this device; try again later")
        report_id = str(uuid.uuid4())
        now = iso()
        conn.execute(
            """
            insert into wait_reports (
              id, entrance_slug, anonymous_client_hash, started_at,
              queue_entry_lat, queue_entry_lng, queue_entry_accuracy_meters,
              confirmation_status, created_at, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, 'started', ?, ?)
            """,
            (
                report_id, slug, client, now,
                rounded_coordinate(payload.get("latitude")),
                rounded_coordinate(payload.get("longitude")),
                float(payload["accuracyMeters"]) if payload.get("accuracyMeters") is not None else None,
                now, now,
            ),
        )
    return {"reportId": report_id, "entrance": slug, "startedAt": now}


def complete_report(payload: dict[str, Any], client: str) -> dict[str, Any]:
    report_id = str(payload.get("reportId") or "")
    with database() as conn:
        report = conn.execute("select * from wait_reports where id=?", (report_id,)).fetchone()
        if not report:
            raise KeyError("Report not found")
        if report["anonymous_client_hash"] != client:
            raise PermissionError("This report belongs to a different anonymous session")
        if report["completed_at"]:
            return {
                "reportId": report_id,
                "entrance": report["entrance_slug"],
                "waitSeconds": report["wait_seconds"],
                "qualityScore": report["quality_score"],
                "status": report["confirmation_status"],
            }
        completed = utc_now()
        seconds = max(1, round((completed - parse_iso(report["started_at"])).total_seconds()))
        if seconds > 4 * 60 * 60:
            raise ValueError("Wait timer exceeded four hours and was not saved")
        quality = 80 if 120 <= seconds <= 3 * 60 * 60 else 30
        status = "completed" if quality >= 50 else "completed-low-confidence"
        conn.execute(
            """
            update wait_reports set completed_at=?, wait_seconds=?,
              completion_lat=?, completion_lng=?, confirmation_status=?,
              quality_score=?, updated_at=? where id=?
            """,
            (
                iso(completed), seconds,
                rounded_coordinate(payload.get("latitude")),
                rounded_coordinate(payload.get("longitude")),
                status, quality, iso(completed), report_id,
            ),
        )
    estimate = compute_estimate(report["entrance_slug"])
    persist_estimate(report["entrance_slug"], estimate)
    return {
        "reportId": report_id,
        "entrance": report["entrance_slug"],
        "waitSeconds": seconds,
        "qualityScore": quality,
        "status": status,
        "message": "Saved as a verified candidate" if quality >= 50 else "Saved, but too short to influence public estimates",
    }


class Poller(threading.Thread):
    daemon = True

    def run(self) -> None:
        while True:
            time.sleep(POLL_SECONDS)
            if not within_polling_window():
                continue
            try:
                result = poll_all()
                if result["errors"]:
                    print(f"[poll] completed with errors: {result['errors']}")
                else:
                    print(f"[poll] completed at {result['completed_at']}")
            except Exception:
                traceback.print_exc()


class Handler(BaseHTTPRequestHandler):
    server_version = "RainierGateWaits/0.4"

    def client_ip(self) -> str:
        direct = self.client_address[0]
        if not TRUST_PROXY_HEADERS:
            return direct
        forwarded = self.headers.get("X-Forwarded-For", "")
        candidate = forwarded.split(",", 1)[0].strip() if forwarded else ""
        if not candidate:
            candidate = self.headers.get("X-Real-IP", "").strip()
        # Keep this value only long enough to derive the daily salted hash.
        if candidate and len(candidate) <= 64 and re.fullmatch(r"[0-9a-fA-F:.]+", candidate):
            return candidate
        return direct

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {self.client_ip()} {fmt % args}")

    def send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, status: int, message: str) -> None:
        self.send_json({"error": message, "status": status}, status)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 65536:
            raise ValueError("Request body must be JSON and smaller than 64 KB")
        raw = self.rfile.read(length)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid JSON body") from exc
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if path == "/api/v1/health":
                self.send_json({
                    "status": "ok",
                    "time": iso(),
                    "database": str(DB_PATH.name),
                    "googleRoutesConfigured": bool(GOOGLE_ROUTES_API_KEY),
                    "npsConfigured": bool(NPS_API_KEY),
                    "wsdotConfigured": bool(WSDOT_ACCESS_CODE),
                    "pollIntervalSeconds": POLL_SECONDS,
                    "pollingWindowLocal": {"startHour": POLL_START_HOUR_LOCAL, "endHour": POLL_END_HOUR_LOCAL},
                    "pollingActiveNow": within_polling_window(),
                    "trustProxyHeaders": TRUST_PROXY_HEADERS,
                })
                return
            if path in {"/api/v1/entrances", "/api/v1/entrances/current"}:
                self.send_json(current_payload())
                return
            if path == "/api/v1/conditions":
                self.send_json(conditions_payload())
                return
            match = re.fullmatch(r"/api/v1/entrances/([a-z0-9-]+)/forecast", path)
            if match:
                self.send_json(forecast_payload(match.group(1), first(query, "date"), first(query, "dayType")))
                return
            match = re.fullmatch(r"/api/v1/entrances/([a-z0-9-]+)/history", path)
            if match:
                hours = int(first(query, "hours") or "24")
                self.send_json(history_payload(match.group(1), hours))
                return
            if path.startswith("/api/"):
                self.send_error_json(404, "API endpoint not found")
                return
            self.serve_static(path)
        except KeyError as exc:
            self.send_error_json(404, str(exc).strip("'"))
        except ValueError as exc:
            self.send_error_json(400, str(exc))
        except Exception as exc:
            traceback.print_exc()
            self.send_error_json(500, f"Server error: {exc}")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        try:
            payload = self.read_json()
            client = client_hash(self.client_ip(), self.headers.get("User-Agent", ""))
            if parsed.path == "/api/v1/reports/start":
                self.send_json(start_report(payload, client), 201)
                return
            if parsed.path == "/api/v1/reports/complete":
                self.send_json(complete_report(payload, client))
                return
            if parsed.path == "/api/v1/admin/poll":
                if not ADMIN_TOKEN:
                    self.send_error_json(404, "Manual polling is disabled")
                    return
                if self.headers.get("X-Admin-Token") != ADMIN_TOKEN:
                    self.send_error_json(403, "Invalid admin token")
                    return
                self.send_json(poll_all())
                return
            self.send_error_json(404, "API endpoint not found")
        except PermissionError as exc:
            self.send_error_json(429 if "Too many" in str(exc) else 403, str(exc))
        except KeyError as exc:
            self.send_error_json(404, str(exc).strip("'"))
        except ValueError as exc:
            self.send_error_json(400, str(exc))
        except Exception as exc:
            traceback.print_exc()
            self.send_error_json(500, f"Server error: {exc}")

    def serve_static(self, path: str) -> None:
        relative = "index.html" if path in {"", "/"} else urllib.parse.unquote(path.lstrip("/"))
        candidate = (ROOT / relative).resolve()
        if ROOT not in candidate.parents and candidate != ROOT:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not candidate.is_file() or candidate.name.startswith(".") or candidate.suffix in {".sqlite3", ".sql"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = candidate.read_bytes()
        content_type, _ = mimetypes.guess_type(candidate.name)
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type or 'application/octet-stream'}; charset=utf-8" if (content_type or "").startswith("text/") else content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-cache" if candidate.suffix in {".html", ".js", ".css"} else "public, max-age=3600")
        self.end_headers()
        self.wfile.write(body)


def first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def main() -> None:
    initialize_database()
    # Ensure the first page load has observations even before the poller wakes.
    with database() as conn:
        latest = conn.execute("select max(observed_at) as latest from traffic_snapshots").fetchone()["latest"]
    if within_polling_window() and (not latest or (utc_now() - parse_iso(latest)) > timedelta(minutes=max(10, POLL_SECONDS // 60 * 2))):
        poll_all()
    if ENABLE_BACKGROUND_POLLING:
        Poller(name="rainier-data-poller").start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Rainier Gate Waits running at http://{HOST}:{PORT}")
    print(f"Data mode: {'live traffic' if GOOGLE_ROUTES_API_KEY else 'transparent demo traffic'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
