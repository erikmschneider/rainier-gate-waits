# Rainier Gate Waits v0.6.1 — methodology transparency

## Added

- Public `methodology.html` page documenting the current calculation in plain language and technical detail.
- Exact traffic-delay baseline and community-report blending rules.
- Report recency weights, uncertainty-range rules, freshness thresholds, confidence explanation, and planning-chart multipliers.
- Known limitations and open calibration questions.
- Shareable methodology URL with a copy-link control.
- Methodology-specific feedback entry points from the methodology page and homepage.
- `methodology` feedback category in the visitor form, backend validation, admin dashboard, and CSV export.

## Unchanged

- The wait calculation itself remains `beta-heuristic-0.6`.
- Methodology comments are stored privately and do not automatically alter estimates.
- Existing SQLite data can be retained without migration changes.
