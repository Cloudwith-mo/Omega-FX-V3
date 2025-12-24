Gate Run Checklist (5-Day Paper-Live)

Pre-Run
- MT5 demo connected and account credentials are in the environment (not in files).
- configs/ftmo_v1.yaml is frozen and matches configs/ftmo_v1.yaml.lock.json.
- Service loop is running (systemd preferred) and shows no errors in journald.
- Symbol specs loaded from broker (audit log contains "symbol_specs" event).
- Bundles are appearing in reports/daily_bundles/<run_id>/YYYY-MM-DD/.
- HUD shows headroom, Prague day start, and safe-mode status correctly.

Smoke Test (30–60 minutes)
- bundles exist for the day and include status.json + state_snapshot.json.
- daily_metrics.json is populated.
- audit.log includes at least one state_check event.
- scripts/analyze_bundles.py --last 1 produces summary.json + summary_table.csv.

Daily Review
- run scripts/gate_daily_check.sh once per day.
- confirm passes_policy_1, passes_policy_2, and go_no_go fields.
- verify daily_buffer_stop_count and headroom minima are within expectations.

Chaos Schedule (execute during the 5 days)
- 3 planned restarts: mid-session, near Prague midnight, and during an open position (if possible).
- 1 simulated disconnect for 3–5 minutes using /tmp/ftmo_force_disconnect (or --simulate-disconnect-path).
- verify bundles show reconnect/restart counts and no duplicates/unresolved drift.

Acceptance Criteria
- breaches == 0, unresolved_drift_events == 0, duplicate_order_events == 0.
- daily buffer stops <= 1 across 5 days.
- stable trade frequency each day (no bursts beyond caps).

Where to Find Go/No-Go
- reports/bundle_summary/summary.json -> go_no_go, passes_policy_1, passes_policy_2.
- reports/bundle_summary/summary_table.csv -> per-day line items.
