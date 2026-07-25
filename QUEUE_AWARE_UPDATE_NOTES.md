# Queue-aware estimator update — v0.8.0

## Why this release exists

The previous estimator subtracted Google `staticDuration` from current route duration. Google defines `staticDuration` as a duration based on historical traffic, so it could already include expected busy-period congestion and materially understate the entrance delay. The original fixed corridors could also miss a queue that extended upstream of their origins.

## Estimator changes

- Extended both fixed approach corridors, with every coordinate configurable through environment variables.
- Added route-version identifiers so old, shorter-route observations are never mixed into a new corridor's baseline, trend, health, or history.
- Replaced `current duration − Google staticDuration` with:

  `maximum of 0 and (current full-route duration − route-specific free-flow baseline)`

- Added provisional entrance-specific baselines:
  - Nisqually: 720 seconds
  - White River: 630 seconds
- Added conservative baseline learning. After 12 current-route observations, the lower decile of recent durations may lower—but never raise—the configured baseline.
- Retained Google `staticDuration` for private diagnostics only.
- Bumped persisted estimate model version to `beta-heuristic-0.8`.

## Hourly queue-boundary scan

- Added a separate hourly Routes API request using `TRAFFIC_ON_POLYLINE`.
- Requests a high-quality encoded polyline and route-level speed intervals.
- Decodes `NORMAL`, `SLOW`, and `TRAFFIC_JAM` intervals.
- Works backward from the entrance to find congestion connected to the gate.
- Allows a short normal-flow gap within a congestion block.
- Ignores isolated upstream congestion separated from the gate by a substantial normal segment.
- Stores approximate queue-start coordinates, queue distance, slow distance, jam distance, interval indexes, and timestamps.
- Does not convert colored-segment length into wait time. Wait continues to come from the duration-minus-free-flow calculation.
- A polyline failure does not block the independent 15-minute duration request.

## Public display

Entrance cards can now say that traffic categories suggest congestion begins approximately a given distance before the entrance. This is explicitly labeled approximate. When no connected slowdown is identified, the card says so rather than inventing a queue length.

The footer now includes the required Google attribution for displayed route-derived information.

## Database migration

Startup automatically adds nullable `route_version`, `free_flow_baseline_seconds`, and `derived_delay_seconds` columns to the existing `traffic_snapshots` table and creates `traffic_polyline_snapshots`. Existing data and reports are retained. Old traffic rows remain available on disk but are excluded from current-route calculations.

## New Render settings

```text
ENABLE_TRAFFIC_POLYLINE=true
TRAFFIC_POLYLINE_INTERVAL_SECONDS=3600
TRAFFIC_POLYLINE_MAX_AGE_MINUTES=90
TRAFFIC_POLYLINE_GATE_CONNECTION_METERS=800
TRAFFIC_POLYLINE_NORMAL_GAP_METERS=300

NISQUALLY_ROUTE_ORIGIN_LAT=46.7580
NISQUALLY_ROUTE_ORIGIN_LNG=-122.0500
NISQUALLY_ROUTE_DESTINATION_LAT=46.7508
NISQUALLY_ROUTE_DESTINATION_LNG=-121.9175
NISQUALLY_ROUTE_VERSION=nisqually-extended-v1
NISQUALLY_FREE_FLOW_SECONDS=720

WHITE_RIVER_ROUTE_ORIGIN_LAT=46.9160
WHITE_RIVER_ROUTE_ORIGIN_LNG=-121.6500
WHITE_RIVER_ROUTE_DESTINATION_LAT=46.9023
WHITE_RIVER_ROUTE_DESTINATION_LNG=-121.5358
WHITE_RIVER_ROUTE_VERSION=white-river-extended-v1
WHITE_RIVER_FREE_FLOW_SECONDS=630

FREE_FLOW_LEARNING_DAYS=30
FREE_FLOW_LEARNING_MIN_SAMPLES=12
```

The coordinates and baselines are provisional. After changing route geometry, increment the corresponding route version.

## Verification after deployment

1. Confirm the authenticated health endpoint shows route version `*-extended-v1` for both entrances.
2. Confirm each entrance gets a new route-version-matched duration observation.
3. Confirm `derivedDelaySeconds` equals current route duration minus the active free-flow baseline.
4. Confirm Google historical duration is shown only as a diagnostic.
5. Confirm a traffic-polyline observation appears within the first hour.
6. Compare its queue-start coordinate and distance against Google Maps and an actual field observation.
7. Keep `ESTIMATOR_FIELD_CALIBRATED=false` until paired observations support the route and baseline assumptions.
