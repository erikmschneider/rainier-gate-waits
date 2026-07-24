# Public beta deployment — Render

The Render Blueprint publishes the website, API, poller, SQLite database, retention cleanup, and rotating backups as one service.

## Included deployment controls

- One Docker-based Starter web service
- One 1 GB persistent disk mounted at `/data`
- SQLite at `/data/rainier_waits.sqlite3`
- Daily rotating backups under `/data/backups`
- Health check at `/api/v1/health`
- Automatic deploys from the connected GitHub repository
- Generated hash and administrator secrets
- Synthetic traffic explicitly disabled
- Google Routes polling every 15 minutes from 6:00 a.m. through 7:59 p.m. Pacific
- Current threshold of 30 minutes and display cutoff of 60 minutes

At two Google route requests every 15 minutes for 14 hours per day, the theoretical maximum is about 3,360 scheduled requests in a 30-day month. Restarts and manual polls can change actual usage.

## Deploy the update

1. Replace the repository files with this package.
2. Confirm that `.env`, API keys, SQLite files, and backup files are not committed.
3. Commit and push.
4. Let Render redeploy automatically.
5. Confirm that the existing persistent disk remains attached at `/data`.

The database initializer performs in-place migrations for timer tokens and the feedback table. Existing traffic history and completed reports remain intact.

## Required Render settings

- `GOOGLE_ROUTES_API_KEY` — required for public estimates
- `RAINIER_HASH_SECRET` — generated and persistent
- `RAINIER_ADMIN_TOKEN` — generated and persistent
- `ALLOW_SYNTHETIC_DATA=false`
- `ACCEPT_REPORT_LOCATIONS=false` until location verification is intentionally launched
- `TRUST_PROXY_HEADERS=true`
- `FEEDBACK_RATE_LIMIT_PER_HOUR=5`
- `FEEDBACK_IDENTIFIER_RETENTION_DAYS=30`
- `FEEDBACK_RETENTION_DAYS=365`

Set `CLOSED_ENTRANCES=white-river` or `CLOSED_ENTRANCES=nisqually,white-river` whenever an official closure should suppress estimates. Clear the value after official reopening.

The optional `WSDOT_ACCESS_CODE` can be added later. The beta currently uses direct links—not an API feed—for official NPS conditions and road status.

## Google Routes configuration

1. Use the Google Cloud project with active billing.
2. Enable Routes API.
3. Restrict the dedicated key to Routes API.
4. Store the key only in Render.
5. Set conservative quotas and billing alerts.

The current request uses traffic-adjusted duration, static duration, and distance without `TRAFFIC_ON_POLYLINE`.

## Verify after deployment

Check:

```text
/
/privacy.html
/admin-feedback.html
/api/v1/health
/api/v1/entrances/current
/api/v1/conditions
```

During daytime polling, `/api/v1/health` should show:

- `databaseWritable: true`
- `googleRoutesConfigured: true`
- each entrance at `current` freshness after a successful poll
- `consecutiveFailedCycles: 0`
- a non-null `lastBackupAt` after the first scheduled backup

The homepage must show `Unavailable` rather than sample numbers whenever no recent observation exists. Confirm that a 31–60 minute observation is labeled stale, and that values disappear after 60 minutes. Submit one test feedback item, then open `/admin-feedback.html` using `RAINIER_ADMIN_TOKEN`, review it, and download the CSV.

## Timer validation

On a phone:

1. Start a timer on Wi-Fi.
2. Switch to cellular.
3. Reload the page.
4. Confirm that the timer resumes.
5. Complete it and confirm the report saves.
6. Confirm that the application logs show a short `client=` identifier rather than a raw IP address.

## Field validation before broad promotion

The route coordinates remain preliminary. For both entrances:

1. Record the queue-end location and actual gate wait.
2. Compare the observed wait with Google’s added travel time.
3. Test no-queue, moderate, and heavy conditions.
4. Move the origin upstream if a long queue can extend beyond it.
5. Ensure the destination is beyond the booth but before unrelated internal congestion.
6. Document any entrance-specific correction factor.

A small closed beta can begin before full calibration, but broad public promotion should wait for preliminary paired field observations.

## Remaining beta work

- Closed-entrance and seasonal-status overrides
- Automating the currently manual entrance-status override from an authoritative source
- External alerting for degraded health or consecutive route failures
- Email or external alerting for especially important feedback, if later needed
- Field-calibrated route geometry and estimator adjustments
- Optional location verification for community timers
- A public version history or change log beyond the current methodology-page version label
