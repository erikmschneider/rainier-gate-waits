# Proposed production architecture

## Current implemented MVP

The starter now includes a standard-library Python API and SQLite persistence. It serves the frontend, polls traffic and condition feeds, stores observations, calculates heuristic ranges and confidence scores, and accepts anonymous visitor timers. This is an instrumented MVP layer beneath the fuller production architecture described below.

## 1. Product surfaces

### Public website

- `/` — current wait overview
- `/entrance/:slug` — detailed entrance page with current conditions, trend, queue map, and recent observations
- `/plan` — date/hour forecast tool
- `/report` — start and complete a visitor wait report
- Public modal forms — report estimate inaccuracies and send general beta feedback
- `/methodology` — model documentation, data freshness, privacy, and limitations
- `/status` — feed health and incidents affecting estimates

### Administrative console

- Review public beta feedback at `/admin-feedback.html`
- Mark feedback as reviewed, useful for calibration, resolved, or spam
- Add private review notes and export CSV
- Review anomalous visitor reports
- Mark incidents that contaminate a traffic-delay signal
- Override entrance open/closed status
- Inspect feed freshness and model drift
- Export aggregated observations

## 2. Services

### Web application

- Next.js or another server-rendered framework
- Accessible, mobile-first interface
- MapLibre for maps, with no traffic-provider key exposed in the browser

### API service

Suggested endpoints:

- `GET /api/v1/entrances`
- `GET /api/v1/entrances/current`
- `GET /api/v1/entrances/:slug/history`
- `GET /api/v1/entrances/:slug/forecast?date=YYYY-MM-DD`
- `GET /api/v1/conditions`
- `POST /api/v1/reports/start`
- `POST /api/v1/reports/complete`
- `POST /api/v1/reports/:id/confirm`
- `POST /api/v1/feedback`
- `GET /api/v1/admin/feedback`
- `POST /api/v1/admin/feedback/:id`
- `GET /api/v1/admin/feedback.csv`

### Scheduled data collection

For the public pilot, run every 15 minutes from 6:00 a.m. through 7:59 p.m. Pacific:

1. Request traffic-aware travel time for each extended fixed approach corridor every 15 minutes.
2. Store traffic-aware duration, historical static duration for diagnostics, route version, free-flow baseline, derived delay, distance, and vendor timestamp.
3. Once per hour, request a traffic-aware polyline and speed intervals, then derive the SLOW/TRAFFIC_JAM block connected to the gate.
3. Fetch official alerts and road incidents.
4. Calculate an initial delay signal.
5. Blend it conservatively with recent community-submitted visitor reports.
6. Publish a cached current estimate.

### Forecasting worker

Run nightly and after substantial new data:

- Build entrance-specific quantile forecasts.
- Produce P25, median, and P75 waits by future hour.
- Use season, hour, day type, holiday, weather, recent delay, closures, and recent report volume.
- Back-test against held-out completed visitor waits.

## 3. Estimation layers

### Layer A: traffic delay

`approach_delay = max(0, traffic_duration - free_flow_baseline)`

The current implementation starts with a configurable entrance-specific free-flow baseline and, after enough route-version-matched samples, may lower it to the lower decile of recent live durations. Future calibration can expand this to season and time bands.

### Layer B: report calibration

Use completed visitor timers from the past 30–60 minutes to estimate:

- actual queue-entry location
- gate processing delay
- difference between traffic delay and completed wait

Weight reports by recency, location quality, completion quality, and agreement with neighboring reports.

### Layer C: incident adjustment

Reduce confidence or suspend the estimate when:

- a crash or construction delay overlaps the approach segment
- the entrance is closed
- a route is seasonally inaccessible
- traffic data are stale
- reports strongly disagree

### Layer D: displayed estimate

Publish a range, not a point estimate:

- `low_minutes`
- `high_minutes`
- `confidence_level`
- `confidence_score`
- `trend`
- `queue_start_distance_miles`
- `updated_at`
- `basis_summary`

## 4. Confidence model

Example components:

- Traffic feed freshness: 0–25 points
- Number of recent completed reports: 0–30 points
- Agreement among recent reports: 0–20 points
- Incident clarity: 0–15 points
- Historical model performance for that entrance/time: 0–10 points

Suggested display bands:

- 80–100: High
- 55–79: Medium
- Below 55: Limited

## 5. Privacy design

- Generate a random report identifier; do not require an account.
- Generate a separate random completion token and store only its one-way hash server-side.
- Round queue-entry coordinates before long-term storage.
- Delete raw location traces after deriving queue entry, gate crossing, and duration.
- Retain only derived observations needed for the estimate.
- Publish only aggregated observations.
- Add rate limits and device-local duplicate prevention.

## 6. Recommended build sequence

### Phase 1 — instrumented public beta

- Implement Nisqually and White River only.
- Store traffic snapshots and official alerts.
- Display experimental delay ranges and feed freshness.
- Suppress sample waits and estimates older than the public freshness cutoff.

### Phase 2 — stronger visitor ground truth

- Improve the existing start/complete community wait reports.
- Add geofenced suggestions with explicit consent.
- Build basic anomaly detection and moderation.

### Phase 3 — forecasts

- Add hourly ranges for the next seven days.
- Publish model error by entrance and season.
- Add optional alerts such as “Nisqually wait is now below 20 minutes.”

### Phase 4 — broader congestion

- Add parking-capacity estimates for Paradise and Sunrise.
- Add congestion beyond the entry booths.
- Explore an NPS data-sharing partnership.
