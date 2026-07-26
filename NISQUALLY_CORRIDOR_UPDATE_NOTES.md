# Nisqually corridor update — v0.8.1

## New default corridor

The Nisqually traffic request now measures the locally identified queue-focused section:

```text
Origin:      46.751415, -121.940160
Destination: 46.740813, -121.915494
Route version: nisqually-queue-v3
Provisional free-flow baseline: 180 seconds
```

The origin is intended to sit just upstream of the maximum usual backup based on local experience. The destination is positioned on the entrance road just beyond the booths.

## Why the route version changed

All prior Nisqually observations used a materially different corridor. The new `nisqually-queue-v3` identifier prevents those rows from influencing the learned free-flow baseline, current trend, queue-boundary scan, or history calculations for this route.

## Deployment

The package and `render.yaml` contain the new defaults. If Render already has manual environment-variable overrides for the old Nisqually values, update or remove those overrides because service-level values can take precedence over Blueprint defaults. Restart the service after saving them.

## Verification

After deployment, the newest Nisqually history row should show:

```text
routeVersion: nisqually-queue-v3
freeFlowBaselineSeconds: 180
```

The distance should be materially shorter than the former roughly 9,928-meter corridor. Compare a quiet-period route duration with the provisional 180-second baseline, then compare peak results with Google Maps and actual entrance waits before marking the estimator field-calibrated.
