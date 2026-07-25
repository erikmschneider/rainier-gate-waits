# Pre-launch hardening — v0.7.0

Changes made in response to the pre-launch review. Grouped by the risk each one addresses.

## 1. The project directory is no longer browsable

`serve_static` previously blocked dotfiles and `.sqlite3`/`.sql` suffixes and served everything else in the application root. `GET /server.py` returned the entire backend, and `/README.md`, `/render.yaml`, `/Dockerfile`, `/PUBLIC_DEPLOYMENT.md`, and `/tests/test_server.py` were all publicly readable.

- Replaced the blocklist with the explicit `PUBLIC_STATIC_FILES` allowlist.
- Any path outside the allowlist returns 404, including traversal attempts and files in subdirectories.
- Resolved paths must be direct children of the application root.

Adding a new public page now requires adding its filename to `PUBLIC_STATIC_FILES` in `server.py`. This is deliberate.

## 2. The published band no longer claims accuracy the model has not demonstrated

The score reached 100 with three agreeing reports, because `incident_points` awarded a flat 15 and `history_points` awarded 10 whenever recent snapshots existed. The site could therefore display "High confidence" for a route geometry that has never been compared against a measured gate wait.

- The card metric is now labeled **Signal strength**, not Confidence. The score measures available input, and the new name says so.
- `confidence_label()` caps the published band at `Medium` until `ESTIMATOR_FIELD_CALIBRATED=true`.
- Set that variable only after completing the paired field observations in `PUBLIC_DEPLOYMENT.md`.
- `methodology.html` documents the ceiling and the reason for it.

## 3. The timer no longer asks drivers to break the law

Washington's RCW 46.61.672 prohibits handheld device use while driving, and the statute's definition of driving includes a vehicle temporarily stationary because of traffic. A driver operating the timer in the entrance line commits an infraction.

- Timer instructions now describe a passenger performing the action.
- A warning block sits directly above the timer controls and cites the statute.
- Copy no longer implies the driver should interact with the phone at any point.

## 4. Community reports are keyed to the browser, not the network

`client_hash(ip, user_agent)` was the key for both the report rate limit and the estimator's one-report-per-client deduplication. Visitors queued at an entrance share a small number of carrier addresses with near-identical mobile user agents, so genuine reports from separate vehicles collapsed into a single client and legitimate reporters were rejected.

- The browser generates a random `deviceId` in `localStorage` and sends it with `POST /api/v1/reports/start`.
- The server stores only `sha256(HASH_SECRET | device | deviceId)` in the new `wait_reports.device_hash` column.
- `DEVICE_REPORT_LIMIT_PER_HOUR` (default 5) is the real control.
- `NETWORK_REPORT_LIMIT_PER_HOUR` (default 60) is a wide abuse backstop. Browsers that send no device identifier still fall back to the strict per-network limit.
- `get_recent_reports` deduplicates on the device hash, falling back to the network hash for legacy rows.
- The migration adds the column in place; existing rows are unaffected.

## 5. Implausible reports cannot move the estimate

Community timers carried 30–50% weight with only a duration sanity check, so one mistimed or deliberately false report moved the published number.

- `filter_plausible_reports()` keeps a report only when it falls within `REPORT_DIVERGENCE_FACTOR` (3.0) of the measured traffic delay, with `REPORT_DIVERGENCE_FLOOR_MINUTES` (10) as an absolute allowance for booth processing in low-delay conditions.
- Excluded reports are counted in the estimate basis rather than silently dropped.
- **Two or more reports far above the traffic signal set `possible_queue_beyond_route_origin` and subtract 25 from the score.** That pattern is the signature of a queue starting upstream of the fixed route origin — the estimator's known blind spot — so it now lowers the published band and leaves a record for field calibration instead of being invisible.

This trade-off is documented honestly in `methodology.html`: the filter suppresses reports in exactly the case where the traffic signal is least trustworthy. Watch the flag during calibration; it is the most useful signal for deciding whether to move the origin upstream.

## 6. Transport and response hardening

- Security headers on every response: `Content-Security-Policy`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, `Permissions-Policy`, and `Strict-Transport-Security` when `ENABLE_HSTS=true`.
- The CSP has no `unsafe-inline`. The inline script in `methodology.html` moved to `methodology.js`.
- 500 responses return `"Server error"`; the traceback goes to the application log through `redact_secrets`.
- Query parameters are parsed and clamped by `query_int()`, so malformed input no longer returns interpreter text.
- `protocol_version = "HTTP/1.1"` enables keep-alive.
- Static responses are gzipped when the client accepts it; the homepage drops from roughly 19 KB to 5.8 KB.
- The server banner no longer advertises the Python version.

## 7. Public health endpoint trimmed

`/api/v1/health` is linked in the site footer and returned disk space, the database filename, poller error strings, and backup timestamps.

- The public response now carries status, version, polling window, freshness thresholds, and per-entrance freshness only.
- Send `X-Admin-Token` to receive the full operational payload.
- Render's health check still passes on the public response.

## 8. Client and content

- The homepage refresh interval moved from 60 seconds to 5 minutes, is skipped when the tab is hidden, and refreshes on return to the tab. The server only polls every 15 minutes, so the old cadence spent battery and cellular data in a queued vehicle for no new data.
- Added Open Graph and Twitter card metadata, `favicon.svg`, `og-image.png`, canonical URL, and `robots.txt` disallowing `/admin-feedback.html` and `/api/`.
- Added a "What you need at the gate" panel: no timed-entry reservation for the 2026 season, the entrance fee still applies, and parking is actively managed. Verify each season before the site reopens for summer.
- The privacy notice now routes questions and removal requests through the beta feedback form (`index.html?feedback=general`), which preselects the general category and offers an optional contact field. No email address is published, so there is no unmonitored mailbox and nothing for scrapers to harvest.

## Configuration added

| Variable | Default | Purpose |
| --- | --- | --- |
| `ESTIMATOR_FIELD_CALIBRATED` | `false` | Lifts the Medium ceiling on the published band |
| `DEVICE_REPORT_LIMIT_PER_HOUR` | `5` | Per-browser report limit |
| `NETWORK_REPORT_LIMIT_PER_HOUR` | `60` | Shared-network abuse backstop |
| `REPORT_DIVERGENCE_FACTOR` | `3.0` | Report plausibility multiple |
| `REPORT_DIVERGENCE_FLOOR_MINUTES` | `10` | Absolute plausibility allowance |
| `ENABLE_HSTS` | `false` | Set true behind Render's HTTPS proxy |

## Before deploying

1. Watch the feedback queue at `/admin-feedback.html`. The site publishes no email address, so that queue is the only inbound channel for privacy questions and removal requests.
2. Set `ENABLE_HSTS=true` on Render, and leave `ESTIMATOR_FIELD_CALIBRATED=false`.
3. Confirm `GET /server.py` returns 404 on the deployed site.
4. Confirm `GET /api/v1/health` without a token omits `diskFreeMegabytes`.
5. Confirm the social preview renders by pasting the URL into a message before announcing it anywhere.

## Still open

- Field-validated route geometry at both entrances. This remains the blocker for broad promotion; the fixed origin undercounts precisely when the queue is longest.
- Automating the entrance-status override from an authoritative source.
- External alerting for degraded health or consecutive route failures.
- The planning chart remains an uncalibrated seasonal template.
