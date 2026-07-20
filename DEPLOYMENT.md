# Deployment and operations checklist

## Recommended first deployment

For a small pilot, deploy the Python service as a single persistent process with a mounted volume for SQLite. Suitable categories include a small virtual machine, container service with persistent disk, or a platform that supports a continuously running Python web process.

Do not deploy this exact SQLite configuration to a serverless function environment. Scheduled polling, local persistence, and the background thread require a persistent process.

## Required configuration

- `GOOGLE_ROUTES_API_KEY`
- `RAINIER_HASH_SECRET`
- `RAINIER_ADMIN_TOKEN`
- Persistent storage for `RAINIER_DB_PATH`
- HTTPS at the reverse proxy or hosting platform

Recommended optional configuration:

- `WSDOT_ACCESS_CODE`
- `POLL_INTERVAL_SECONDS=900`
- `POLL_START_HOUR_LOCAL=6`
- `POLL_END_HOUR_LOCAL=20`
- `RAINIER_HOST=0.0.0.0`
- `ALLOW_SYNTHETIC_DATA=false`
- `CURRENT_MAX_AGE_MINUTES=30`
- `STALE_MAX_AGE_MINUTES=60`
- `RAINIER_BACKUP_DIR=/data/backups`
- `FEEDBACK_RATE_LIMIT_PER_HOUR=5`
- `FEEDBACK_IDENTIFIER_RETENTION_DAYS=30`
- `FEEDBACK_RETENTION_DAYS=365`

## Traffic-provider controls

- Restrict the Google API key to the Routes API.
- Add server/IP restrictions where the hosting environment permits them.
- Set a daily quota and billing alert.
- Poll only Nisqually and White River during the pilot.
- Request only duration, static duration, and distance; do not enable `TRAFFIC_ON_POLYLINE`.
- Cache one result per entrance per polling interval; do not call the routing API separately for each site visitor.
- Validate each route segment in the provider’s route demo and test whether queued traffic is represented consistently.

## Privacy and abuse controls

The MVP already:

- Requires no account
- Stores a daily salted client hash rather than a raw IP address
- Rounds optional coordinates
- Limits report starts to five per anonymous client per hour
- Excludes very short timers from the public estimate
- Uses a private timer-completion token instead of requiring an unchanged IP address
- Deduplicates recent estimator input by anonymous client
- Publishes a privacy notice and retention schedule
- Deletes abandoned timers and removes old client/token identifiers automatically
- Uses hashed client identifiers in application request logs

The beta now includes an administrative feedback review interface at `/admin-feedback.html`. Keep `RAINIER_ADMIN_TOKEN` private and rotate it if exposed.

Still recommended before a broader public launch:

- Reverse-proxy request limits
- Stronger duplicate and impossible-travel detection

## Reliability controls

- Run the server behind a process supervisor.
- Verify the built-in rotating database backups on the persistent disk.
- Monitor `/api/v1/health`.
- Add an external alert when health reports degraded data or repeated polling failures.
- Record API latency, failures, quota errors, and estimate freshness.
- Suppress or clearly downgrade estimates when an entrance is closed.

## Migration to production architecture

SQLite is appropriate for a local MVP and limited pilot. Migrate to PostgreSQL/PostGIS before adding high-volume public reporting, queue geometry, multiple application instances, or a moderation console. The proposed production tables are in `schema.sql`.

## Highest-priority field validation

1. Drive each approach with the polling system active.
2. Record the actual point where entrance queues begin.
3. Compare Google’s added travel time with stopwatch wait time.
4. Repeat during no-queue, moderate, and heavy-queue periods.
5. Test whether roadwork and ordinary slow traffic create false waits.
6. Adjust approach segments and estimator calibration by entrance.
