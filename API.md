# Public beta API contract

All endpoints are served from the same origin as the website. JSON responses use `Cache-Control: no-store`.

## Health

### `GET /api/v1/health`

Returns process, storage, polling, backup, and per-entrance data freshness information. Important fields include:

- `status` — `ok`, `degraded`, or `error`
- `databaseWritable`
- `diskFreeMegabytes`
- `pollingActiveNow`
- `entrances.<slug>.freshness` — `current`, `stale`, or `unavailable`
- `poller.consecutiveFailedCycles`
- `poller.lastErrors`
- `completedReportsLast24Hours`
- `lastBackupAt`

An internal database failure returns HTTP 503. Stale traffic during polling hours returns `status: degraded` with HTTP 200 so the service remains reachable while external monitoring can inspect the JSON state.

## Current entrance estimates

### `GET /api/v1/entrances/current`

Returns Nisqually and White River. Important fields:

- `min`, `median`, `max` — wait range in minutes, or `null` when unavailable
- `displayable` — whether a public estimate may be shown
- `freshnessStatus` — `current`, `stale`, `last-daytime`, or `unavailable`
- `updatedMinutes`
- `confidenceScore` — 0–100
- `reports` — distinct recent community reports considered
- `dataMode` — `live`, `live+reports`, `demo`, `demo+reports`, or `unavailable`
- `basis` — provider, age, traffic delay, community report summary, and limitations

`queueMiles` is currently always `null`; the beta does not claim a measured physical queue length.

## Conditions

### `GET /api/v1/conditions`

Returns active NPS and WSDOT conditions when configured, plus setup or data-availability notices.

## Planning template

### `GET /api/v1/entrances/:slug/forecast`

Query parameters:

- `date=YYYY-MM-DD`
- `dayType=weekday|weekend|holiday`

The response is marked `seasonal-template` and must not be presented as a current-traffic or validated historical prediction.

## History

### `GET /api/v1/entrances/:slug/history?hours=24`

Returns up to seven days of archived approach observations.

## Community timer

### `POST /api/v1/reports/start`

```json
{
  "entrance": "nisqually"
}
```

Response:

```json
{
  "reportId": "UUID",
  "reportToken": "private random token",
  "entrance": "nisqually",
  "startedAt": "2026-07-20T02:00:00Z"
}
```

The browser must keep `reportToken` private. The server stores only its one-way hash.

Optional rounded location fields are supported by the backend, but the current public interface does not request location permission.
They are ignored unless `ACCEPT_REPORT_LOCATIONS=true` is explicitly configured.

### `POST /api/v1/reports/complete`

```json
{
  "reportId": "UUID returned by start",
  "reportToken": "private token returned by start"
}
```

The token allows completion after a Wi-Fi/cellular change. Timers shorter than two minutes are retained as low-confidence records and do not influence public estimates. Timers longer than four hours are rejected.

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
