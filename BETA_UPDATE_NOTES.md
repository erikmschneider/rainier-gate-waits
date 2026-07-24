# Beta hardening update notes — v0.5

## What changed

### Public estimate safety

- Removed all plausible browser fallback wait values.
- Synthetic observations are disabled by default.
- A recent Google Routes observation is required before a public estimate is shown.
- Observations are labeled current through 30 minutes, stale from 31–60 minutes, and hidden after 60 minutes.
- Outside daytime polling, a recent observation is labeled as the last daytime observation rather than live.
- Physical queue mileage is no longer displayed.
- Added a manual `CLOSED_ENTRANCES` override.

### Community timer safety

- Replaced IP-continuity ownership with a random browser-held completion token.
- Stores only a one-way hash of that token in SQLite.
- Deduplicates estimator input to one recent report per anonymous client.
- Caps community weighting at 30% for one or two reports and 50% for three or more.
- Gives newer reports more influence than older reports.
- Community reports cannot create an estimate without recent live traffic.
- Report locations are ignored unless `ACCEPT_REPORT_LOCATIONS=true` is intentionally enabled.

### Privacy and retention

- Application request logs now show a short salted client identifier, not a raw IP address.
- Added `privacy.html` and linked it from the homepage.
- Abandoned timer starts are deleted after approximately 24 hours.
- Client identifiers and timer-token hashes are removed from completed reports after approximately 60 days.

### Reliability

- Added detailed per-entrance freshness to `/api/v1/health`.
- Added database writability, disk space, poll failures, consecutive failed cycles, report volume, and backup status.
- Added rotating SQLite backups, approximately daily, retaining seven by default.
- Added official NPS conditions and road-status links without an NPS API feed.
- Expanded the backend tests from 7 to 13.

## Database migration

The existing persistent SQLite database can be retained. On startup, the server adds the nullable `report_secret_hash` column if it is missing. Existing observations, estimates, and completed reports remain intact.

Active timers started before this update can still use the legacy same-client completion check. New timers use the private token flow.

## Deploy

1. Replace the repository files with this package.
2. Do not upload a SQLite database, `.env`, API key, or backup file.
3. Commit and push to the branch connected to Render.
4. Confirm the persistent disk remains mounted at `/data`.
5. Confirm these Render values after deployment:

```text
ALLOW_SYNTHETIC_DATA=false
ACCEPT_REPORT_LOCATIONS=false
CURRENT_MAX_AGE_MINUTES=30
STALE_MAX_AGE_MINUTES=60
RAINIER_BACKUP_DIR=/data/backups
BACKUP_INTERVAL_HOURS=24
BACKUP_RETENTION_COUNT=7
TRUST_PROXY_HEADERS=true
```

Use `CLOSED_ENTRANCES=white-river` when White River should be manually suppressed, and clear it when official access resumes.

## Verify

- `/api/v1/health` reports `databaseWritable: true`.
- The site shows `Unavailable`, never sample numbers, when live observations are absent.
- A timer survives page reload and a Wi-Fi-to-cellular switch.
- Render request logs show `client=<12-character identifier>` rather than a raw IP.
- `/privacy.html` loads.
- `/data/backups` contains a recent SQLite backup.

## v0.5.1 adjustment

- Removed the optional NPS alert-feed integration and its credential configuration for now.
- Existing stored NPS-feed records are excluded from the public conditions response.
- Direct links to official NPS conditions and road status remain available.

## v0.6 feedback tools

- Added “Report an inaccurate estimate” to each entrance card.
- Added a general “Send beta feedback” form in the footer.
- Added `POST /api/v1/feedback` with validation, a honeypot, and anonymous rate limiting.
- Added a separate `feedback_submissions` SQLite table; feedback never alters estimates automatically.
- Added `/admin-feedback.html`, protected at the data layer by `RAINIER_ADMIN_TOKEN`.
- Added review statuses, private notes, filtering, and CSV export.
- Added feedback retention controls and privacy-notice language.
- Added health metrics for recent and unreviewed feedback.
- Expanded the backend suite to 19 tests.

## v0.6.1 methodology transparency

- Added a public `methodology.html` page with the exact current calculation, freshness rules, uncertainty logic, confidence caveats, planning-chart multipliers, and known limitations.
- Added homepage and footer links to the complete methodology.
- Added a shareable copy-link control.
- Added a methodology-specific feedback category throughout the public form, backend, private dashboard, and CSV export.
- Methodology feedback remains separate from community timers and does not automatically affect estimates.
- The estimator itself remains `beta-heuristic-0.6`.
