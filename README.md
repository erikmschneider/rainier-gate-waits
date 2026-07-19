# Rainier Gate Waits — local MVP

A mobile-responsive prototype and runnable local backend for estimating vehicle waits at Mount Rainier National Park entrance gates.

The project now works in two modes:

- **Transparent demo mode:** runs immediately with synthetic traffic observations clearly labeled as demo data.
- **Live-feed mode:** polls Google Routes for traffic-aware approach travel times and can retrieve NPS and WSDOT alerts when API credentials are supplied.

## What is included

- Current-wait cards for Nisqually and White River
- SQLite persistence for traffic snapshots, estimates, conditions, and visitor wait reports
- Background polling every 15 minutes from 6:00 a.m. through 7:59 p.m. Pacific by default
- Browser timer connected to anonymous report start/complete API endpoints
- Hourly planning forecasts served by the backend
- Current estimate, history, conditions, health, forecast, and reporting endpoints
- Static fallback behavior when `index.html` is opened without the backend
- Automated Python tests
- No third-party Python packages

## Start the MVP

Python 3.11 or newer is recommended.

```bash
cd rainier-gate-waits-starter
python3 server.py
```

On Windows PowerShell, this will often be:

```powershell
cd rainier-gate-waits-starter
py server.py
```

Alternatively, double-click `start_windows.bat` on Windows or run `./start_mac_linux.sh` on macOS/Linux.

Then open:

```text
http://127.0.0.1:8000
```

The first run creates `rainier_waits.sqlite3`. The database is ignored by Git.

## Publish as one public service

The project includes `render.yaml`, which deploys the site, API, background poller, and persistent SQLite database as one Render web service. See `PUBLIC_DEPLOYMENT.md` for the full process.

The public pilot uses only Nisqually and White River, with 15-minute polling from 6:00 a.m. through 7:59 p.m. Pacific. This is approximately 3,360 Google route requests in a 30-day month.

## Run with Docker

```bash
docker compose up --build
```

The Compose configuration persists SQLite data in a named volume and passes optional API credentials from your shell environment.

## Run the tests

```bash
python3 -m unittest discover -s tests -v
```

## Activate live traffic measurements

Google Routes is the core live signal. Set an API key in the environment before starting the server.

macOS or Linux:

```bash
export GOOGLE_ROUTES_API_KEY="your-key"
python3 server.py
```

Windows PowerShell:

```powershell
$env:GOOGLE_ROUTES_API_KEY="your-key"
py server.py
```

The server requests traffic-aware and traffic-free durations for each fixed approach segment. API keys remain on the server and are never sent to `app.js`.

Before public deployment, verify every approach origin and gate destination in `server.py`. The included coordinates are starter route definitions, not survey-grade entrance or queue points.

## Connect official condition feeds

Optional environment variables:

```text
NPS_API_KEY=...
WSDOT_ACCESS_CODE=...
```

The NPS API provides authoritative park alerts, but its alert feed may lag the park website. The WSDOT integration filters statewide alerts for SR 706 and SR 410.

See `.env.example` for all settings. The standard-library server does not automatically load `.env`; set the variables in your shell or use your hosting platform’s environment settings.

## Important files

- `index.html`, `styles.css`, `app.js` — public website
- `server.py` — static server, API, polling, estimator, and SQLite persistence
- `API.md` — endpoint contract
- `ARCHITECTURE.md` — production architecture and development sequence
- `DEPLOYMENT.md` — deployment and operational checklist
- `schema.sql` — future PostgreSQL/PostGIS production schema
- `tests/test_server.py` — backend tests

## Current methodological status

The backend estimator is deliberately simple:

1. Calculate traffic delay as traffic-aware duration minus traffic-free duration.
2. Blend that delay with recent qualifying visitor timers.
3. Widen the displayed range when observations are stale or visitor reports disagree.
4. Calculate a confidence score from feed freshness, report volume, agreement, and history.

The planning forecast is still a seasonal template. It should not be described as predictive until enough verified wait reports and archived traffic snapshots are available for back-testing.

## Public-use cautions

- The application is independent and is not an official NPS source.
- Demo values must remain visibly labeled.
- Live traffic delay can include construction, incidents, or slow-moving vehicles unrelated to the entrance booth.
- The displayed queue mileage is currently a coarse delay proxy. It should eventually be replaced with a detected or reported queue-start location.
- Seasonal entrance closure logic must be strengthened before public launch.
