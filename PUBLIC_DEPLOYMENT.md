# Public pilot deployment — Render

This configuration publishes the project as one continuously running web service. The same process serves the website, exposes the API, polls traffic and official conditions, and stores observations in SQLite on a persistent disk.

Visitors use one HTTPS address. There is no separately managed frontend or backend.

## What the included `render.yaml` creates

- One Docker-based Render web service
- Starter compute instance
- Health check at `/api/v1/health`
- One persistent disk mounted at `/data`
- SQLite database at `/data/rainier_waits.sqlite3`
- Automatic deployment after commits to the connected repository
- Generated privacy and administrator secrets
- Prompts for Google, NPS, and WSDOT credentials
- Traffic polling every 15 minutes from 6:00 a.m. through 7:59 p.m. Pacific

The daytime polling window substantially reduces traffic-API use. At two route requests every 15 minutes for 14 hours per day, the theoretical maximum is about 3,360 requests in a 30-day month. Actual use will vary slightly with restarts, manual polls, and failed requests.

## 1. Put the project in GitHub

1. Create a new private GitHub repository, such as `rainier-gate-waits`.
2. Upload all files in this project folder to the repository root.
3. Confirm that `.env` files, API keys, and `rainier_waits.sqlite3` are not committed.
4. Commit and push the files.

The repository may later be public because credentials live in Render environment variables, not in the source code. Keeping it private during setup reduces accidental exposure.

## 2. Create the Render service

1. Sign in to Render and connect the GitHub account containing the repository.
2. Choose **New > Blueprint**.
3. Select the repository.
4. Render reads `render.yaml` and displays the service and disk it will create.
5. Enter the requested credential values:
   - `GOOGLE_ROUTES_API_KEY`
   - `NPS_API_KEY` — optional but recommended
   - `WSDOT_ACCESS_CODE` — optional but recommended
6. Approve the Blueprint deployment.

When the deployment is healthy, Render assigns an address similar to:

```text
https://rainier-gate-waits.onrender.com
```

## 3. Configure Google Routes

1. Create or select a Google Cloud project.
2. Attach a billing account.
3. Enable **Routes API**.
4. Create a dedicated API key for this application.
5. Restrict the key to **Routes API**.
6. Set a low quota and a billing budget alert before public launch.
7. Add the key to `GOOGLE_ROUTES_API_KEY` in Render, not to a source file.

The request asks only for traffic-aware duration, static duration, and distance. It does not request `TRAFFIC_ON_POLYLINE`, keeping the call in the lower-priced Compute Routes Pro category rather than Enterprise. The two-entrance schedule is designed to remain below the current 5,000-request monthly Pro allowance, but quotas and billing alerts remain essential.

Server-IP restrictions are desirable but can be awkward on hosting plans without dedicated outbound IPs. API restriction to Routes API, tight quotas, secret storage, and monitoring are the minimum controls for the pilot.

## 4. Add official-condition keys

- Request a free NPS developer key and save it as `NPS_API_KEY`.
- Request a WSDOT Traveler Information access code and save it as `WSDOT_ACCESS_CODE`.

Neither key is exposed to the browser.

## 5. Verify the public service

Check these addresses after deployment:

```text
/
/api/v1/health
/api/v1/entrances/current
/api/v1/conditions
```

The health response should report:

- `googleRoutesConfigured: true`
- `pollingActiveNow: true` during the configured daytime window
- database name `rainier_waits.sqlite3`

On the homepage, confirm that values are labeled live rather than demo after the first successful Google poll.

## 6. Validate the entrance segments before promotion

The coordinates in `server.py` remain preliminary. Before advertising the estimates:

1. Drive each entrance approach while recording actual stopwatch wait time.
2. Compare actual wait with API-added travel time.
3. Move the origin far enough upstream to capture the longest plausible queue.
4. Ensure the destination lies beyond the entrance booth but before unrelated internal congestion.
5. Repeat with no queue, moderate queue, and a heavy weekend queue.
6. Adjust the estimator separately for each entrance.

Do not describe the site as accurate or predictive until this validation is completed.

## 7. Add a custom domain

After the pilot works at the Render address:

1. Buy a domain or choose a subdomain.
2. Add it under the Render service's **Custom Domains** settings.
3. Add the DNS records Render provides.
4. Verify the domain.

Render manages the TLS certificate and redirects HTTP requests to HTTPS.

## 8. Minimum public-launch additions

Before broadly sharing the site, add:

- Privacy and methodology pages
- A visible independent/non-NPS disclaimer
- Automatic retention cleanup for old raw report data
- A closed-entrance override and seasonal schedule
- Error monitoring and an alert for stale traffic data
- A lightweight administrative review page
- Field-tested entrance coordinates

## Expected pilot cost

Using current published pricing, the baseline is approximately:

- Render Starter web service: $7 per month
- Render disk: storage billed per GB per month
- Google Routes: expected to remain within the current included Pro request allowance at roughly 3,360 scheduled requests per 30-day month; overage remains possible from manual testing or configuration changes
- Domain: typically an annual registrar charge
- NPS and WSDOT keys: no fee indicated for basic access

Treat these as planning figures rather than guarantees; vendor pricing and usage can change.
