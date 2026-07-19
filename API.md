# MVP API contract

All endpoints are served from the same origin as the website. JSON responses use `Cache-Control: no-store`.

## Health

### `GET /api/v1/health`

Returns database and integration status.

```json
{
  "status": "ok",
  "time": "2026-07-17T18:00:00Z",
  "googleRoutesConfigured": false,
  "npsConfigured": false,
  "wsdotConfigured": false,
  "pollIntervalSeconds": 900,
  "pollingWindowLocal": {"startHour": 6, "endHour": 20},
  "pollingActiveNow": true
}
```

## Current entrance estimates

### `GET /api/v1/entrances/current`

Returns estimates for the two pilot entrances—Nisqually and White River—and the basis for each estimate.

Important fields:

- `min`, `median`, `max` — displayed wait range in minutes
- `queueMiles` — coarse delay-footprint proxy in the MVP
- `confidenceScore` — 0–100
- `dataMode` — `live`, `live+reports`, `demo`, or `demo+reports`
- `basis` — traffic age, provider, raw delay, and report summary

## Conditions

### `GET /api/v1/conditions`

Returns active NPS and WSDOT conditions plus setup notices when feeds are not connected.

## Forecast

### `GET /api/v1/entrances/:slug/forecast`

Query parameters:

- `date=YYYY-MM-DD`
- `dayType=weekday|weekend|holiday`

The current response is marked `seasonal-template`. A future model should replace it with back-tested quantile forecasts.

## History

### `GET /api/v1/entrances/:slug/history?hours=24`

Returns up to seven days of archived approach observations, including traffic-aware duration, traffic-free duration, delay, and provider.

## Visitor timer

### `POST /api/v1/reports/start`

```json
{
  "entrance": "nisqually"
}
```

Optional location fields are supported but the current frontend does not request them:

```json
{
  "entrance": "nisqually",
  "latitude": 46.751,
  "longitude": -121.918,
  "accuracyMeters": 25
}
```

Coordinates are rounded to three decimal places before storage.

### `POST /api/v1/reports/complete`

```json
{
  "reportId": "UUID returned by the start endpoint"
}
```

Timers shorter than two minutes are stored but assigned low confidence and do not influence public estimates. Timers longer than four hours are rejected.

## Manual poll

### `POST /api/v1/admin/poll`

Disabled unless `RAINIER_ADMIN_TOKEN` is configured. Supply the token in the `X-Admin-Token` header.

## Error format

```json
{
  "error": "Human-readable explanation",
  "status": 400
}
```
