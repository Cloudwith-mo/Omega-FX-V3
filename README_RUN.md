FTMO Bot v3 - Runbook (v1)

Requirements
- Python 3.11+
- pip

Setup
- python -m venv .venv
- source .venv/bin/activate
- python -m pip install -e .[dev]

Freeze config
- python scripts/freeze_config.py configs/ftmo_v1.yaml

Generate sample sim report (v2)
- python scripts/run_sim_report.py --config configs/ftmo_v1.yaml --output reports/sample_sim_report_v2.json

Run unit tests
- pytest -q

Run local sim demo
- python examples/demo_simulation.py

Run paper demo (idempotency + buffers)
- python examples/demo_paper.py

Run with frozen config (run_id + audit)
- python examples/run_with_config.py

Run service loop (reconcile + health checks)
- python scripts/run_service_loop.py --config configs/ftmo_v1.yaml
- note: status updates are written when runtime/state_snapshot.json is available

Run service loop with MT5 (requires MetaTrader5)
- python -m pip install MetaTrader5
- update configs/ftmo_v1.yaml: execution.broker: mt5
- export MT5_LOGIN=123456 MT5_PASSWORD=secret MT5_SERVER=Broker-Server
- export MT5_PATH=/path/to/terminal64.exe  # optional
- python scripts/run_service_loop.py --config configs/ftmo_v1.yaml --resume

Generate a daily bundle (manual)
- python scripts/generate_daily_bundle.py --config configs/ftmo_v1.yaml --output-dir reports/daily_bundles

Run Streamlit HUD (reads runtime/status.json by default)
- python -m pip install -e .[hud]
- streamlit run apps/hud_streamlit.py

Generate a sample forward-test log bundle
- python scripts/generate_sample_logs.py --config configs/ftmo_v1.yaml --output-dir reports/forward_test_bundle
