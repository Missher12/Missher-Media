# Troubleshooting

Use the structured preflight or collection status before taking action.

## Missing engine or interpreter

Confirm the configured root contains `scripts/scrape_all.py` and executable `engine/.venv/bin/python`. Correct the external path; do not copy the engine into this skill or build a virtual environment inside it.

## CDP unavailable

Confirm the user's existing Chrome debugging session and configured CDP URL. Do not start, restart, or terminate Chrome automatically. Do not replace its profile or cookies.

## Logged out

Ask the user to restore the platform session manually in the existing browser. Do not capture credentials, import cookies, bypass a captcha, or switch accounts automatically.

## Platform page unavailable

If the external runtime reports that a requested platform page is missing, ask the user to open the configured creator page in the existing debugging-enabled Chrome session, then rerun preflight and retry that platform at most once. Do not open or navigate a browser page without explicit authorization.

## Timeout

Keep the failed run directory as evidence. Inspect redacted stderr and the platform status. Fix a concrete non-risk cause, rerun preflight, and retry at most once. Do not increase concurrency or create overlapping runs.

## Lock or cooldown

Return `risk-stopped`. Do not delete a lock, checkpoint, cache, report, or risk-state file. Wait for the external runtime's cooldown policy or ask the user to decide later.

## Risk response

Treat `403`, `429`, `461`, `471`, `999`, `risk`, and `locked` as stop signals. Do not rotate accounts, perform proxy rotation, use a proxy pool, add retries, or attempt platform-control evasion.

## Partial output

Read the validation errors and current-run evidence. Report the exact count and missing completeness checks. Never fill an unknown date or engagement metric with zero.
