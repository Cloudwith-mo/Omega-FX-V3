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

Generate sample sim report
- python scripts/run_sim_report.py --config configs/ftmo_v1.yaml --output reports/sample_sim_report.json

Run unit tests
- pytest -q

Run local sim demo
- python examples/demo_simulation.py

Run paper demo (idempotency + buffers)
- python examples/demo_paper.py

Run with frozen config (run_id + audit)
- python examples/run_with_config.py

Generate a sample forward-test log bundle
- python scripts/generate_sample_logs.py --config configs/ftmo_v1.yaml --output-dir reports/forward_test_bundle
