# Rainier Gate Waits — public beta

Rainier Gate Waits is an independent, mobile-responsive public beta for estimating vehicle waits at the Nisqually and White River entrances to Mount Rainier National Park.

The Python standard-library service hosts the website and API, polls Google Routes, stores observations and anonymous community timers in SQLite, and suppresses estimates when the underlying data is too old.

## Public-beta safeguards

- Only an explicit allowlist of front-end files is reachable over HTTP; application source, tests, and deployment manifests are not served.
- The published signal-strength band is capped at Medium until `ESTIMATOR_FIELD_CALIBRATED=true` confirms field validation.
- Community reports are rate-limited per browser rather than per network address, so shared carrier addresses at an entrance do not block genuine reporters.
- Reports that diverge sharply from the measured traffic signal are excluded from the estimate and recorded; repeated high outliers flag a possible queue beyond the route origin and lower the score.
- Security headers, including a Content Security Policy without inline script, are sent on every response.
- The public health response omits operational detail; the full payload requires the administrator token.
- Timer instructions are written for passengers, not drivers (RCW 46.61.672).

- No plausible browser fallback waits are displayed when the API is unavailable.
- Synthetic traffic is disabled by default and must be explicitly enabled for local demonstrations.
- Traffic observations up to 30 minutes old are treated as current.
- Observations 31–60 minutes old are visibly labeled stale or last daytime observations.
- Estimates older than 60 minutes are hidden.
- Community timers supplement a recent Google observation but never create an estimate by themselves.
- One recent report per anonymous client contributes to the estimator.
- Community report weight is capped at 30% for one or two distinct reports and 50% for three or more.
- Timer completion uses a random browser-held token instead of depending on an unchanged IP address.
- Report locations are ignored by default until an explicit location-verification feature is enabled.
- A manual `CLOSED_ENTRANCES` override suppresses estimates for a closed or seasonally inaccessible entrance.
- Application request logs use short salted client identifiers rather than raw IP addresses.
- Abandoned timers are deleted after approximately 24 hours; report identifiers are removed after approximately 60 days.
- Rotating SQLite backups are created approximately daily and retained on the persistent disk.
- Public feedback is stored separately from estimator inputs, rate-limited, and reviewable only with the administrator token.

## What is included

- Current estimate cards for Nisqually and White River
- Fresh, stale, last-daytime, and unavailable states
- SQLite persistence for traffic observations, estimates, conditions, and community reports
- Background polling every 15 minutes from 6:00 a.m. through 7:59 p.m. Pacific by default
- Anonymous browser timer with reload and network-change resilience
- Preliminary seasonal planning templates, clearly labeled as experimental
- Health endpoint with per-entrance freshness, database writability, disk space, poll errors, report volume, and backup status
- Privacy notice and links to official NPS conditions and road status
- Estimate-accuracy and general beta-feedback forms
- Private feedback dashboard with review statuses, notes, and CSV export
- Automated Python tests (28)
- No third-party Python packages

## Run locally

Python 3.11 or newer is recommended.

```bash
cd rainier-gate-waits-starter
python3 server.py
```

Then open:

```text
http://127.0.0.1:8000
```

Without a Google Routes key, current waits remain unavailable. To run an explicitly labeled local synthetic demonstration:

```bash
export ALLOW_SYNTHETIC_DATA=true
python3 server.py
```

Do not enable synthetic data on the public deployment.

To manually suppress a closed entrance, set a comma-separated override such as:

```bash
export CLOSED_ENTRANCES="white-river"
```

## Activate live traffic measurements

```bash
export GOOGLE_ROUTES_API_KEY="your-key"
python3 server.py
```

The API key remains on the server. The Google request asks only for traffic-adjusted duration, static duration, and distance.

Before broad promotion, field-test the approach origin and destination coordinates in `server.py`. They remain preliminary and are not survey-grade queue points.

## Optional WSDOT condition feed

```text
WSDOT_ACCESS_CODE=...
```

The public interface links directly to official NPS conditions and road status; it does not currently ingest an NPS alert feed.

## Deploy on Render

The included `render.yaml` creates one Docker web service and a 1 GB persistent disk. See `PUBLIC_DEPLOYMENT.md` for the deployment and validation checklist.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## Important files

- `index.html`, `styles.css`, `app.js` — public interface
- `privacy.html` — public privacy notice
- `admin-feedback.html`, `admin-feedback.js` — token-protected feedback review interface
- `server.py` — API, polling, estimator, health monitoring, retention, backups, and SQLite persistence
- `API.md` — endpoint contract
- `PUBLIC_DEPLOYMENT.md` — Render deployment and beta checklist
- `tests/test_server.py` — backend tests
- `PRELAUNCH_UPDATE_NOTES.md` — v0.7.0 hardening changes and pre-deploy checklist

## Methodological status

The current estimate is a heuristic range based primarily on Google’s added travel time on a fixed approach segment. Recent community timers receive limited, recency-weighted influence. Physical queue length is not shown because it has not yet been measured reliably.

The planning chart is a preliminary seasonal template. It is not a prediction from current traffic and has not yet been validated against a sufficient historical dataset.

## Review beta feedback

Open `/admin-feedback.html` on the deployed site and enter the `RAINIER_ADMIN_TOKEN` value from Render. The token is stored only in the current browser tab. The dashboard can filter submissions, mark them reviewed or useful for calibration, add private notes, and download CSV.

Feedback records live in the same persistent SQLite database and are included in the rotating backups. They never influence wait estimates automatically.

- Public `methodology.html` page documenting the calculation and known limitations.

## Public methodology

The calculation is documented at `/methodology.html`. Visitors can submit calculation-specific comments through the existing private feedback workflow. The page documents model version `beta-heuristic-0.6`; the documentation/site release is v0.7.0. See `PRELAUNCH_UPDATE_NOTES.md` for the pre-launch hardening pass.
