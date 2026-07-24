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

Returns active WSDOT conditions when configured, plus manual entrance-status and traffic-data notices. The beta does not currently ingest an NPS alert feed.

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

## Beta feedback

### `POST /api/v1/feedback`

Stores estimate-accuracy reports, methodology comments, and general beta feedback in a table separate from community timers. Accuracy submissions require `entrance` and `actualWaitMinutes`. General and methodology submissions require a message. Optional email addresses are private and used only for requested follow-up. Supported categories include `estimate-accuracy`, `timer-problem`, `website-problem`, `confusing-information`, `feature-suggestion`, `methodology`, and `other`.

Example accuracy submission:

```json
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
  "contactEmail": "optional@example.com",
  "pagePath": "/"
}
```

Submissions are limited per temporary anonymous client identifier. The hidden `website` field is a honeypot and should remain blank. Feedback never changes the live estimate automatically. The public methodology page links to this endpoint with the `methodology` category preselected.

## Private feedback administration

Open `/admin-feedback.html` and enter `RAINIER_ADMIN_TOKEN`, or call the endpoints directly with the token in `X-Admin-Token`.

### `GET /api/v1/admin/feedback`

Optional query parameters: `status`, `limit`, and `offset`. Review statuses are `new`, `reviewed`, `calibration`, `resolved`, and `spam`.

### `POST /api/v1/admin/feedback/:id`

```json
{
  "status": "calibration",
  "resolutionNotes": "Use during route validation."
}
```

### `GET /api/v1/admin/feedback.csv`

Downloads all matching feedback as CSV. An optional `status` query filter is supported. Temporary anonymous client identifiers are never included in the admin response or CSV.

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
