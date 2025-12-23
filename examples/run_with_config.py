from pathlib import Path

from ftmo_bot.config import freeze_config, load_config, verify_config_lock
from ftmo_bot.execution import ExecutionEngine, OrderJournal, PaperBroker, RequestThrottle
from ftmo_bot.monitoring import AuditLog, LogNotifier, Monitor
from ftmo_bot.risk import RiskGovernor
from ftmo_bot.rule_engine import RuleEngine
from ftmo_bot.runtime import create_run_context


config_path = Path("configs") / "ftmo_v1.yaml"
config = load_config(config_path)
lock_path = freeze_config(config_path)
assert verify_config_lock(config_path, lock_path)

context = create_run_context(config_path, config.run_id_prefix)

monitor = Monitor(LogNotifier())
audit = AuditLog(
    Path(config.monitoring.audit_log_path),
    run_id=context.run_id,
    config_hash=context.config_hash,
)
audit.log("run_start", {"config": str(config_path), "lock": str(lock_path)})

engine = RuleEngine(config.rule_spec)
risk = RiskGovernor(engine, audit_log=audit, monitor=monitor)

throttle_config = config.execution.throttle
throttle = RequestThrottle(
    max_requests_per_day=int(throttle_config.get("max_requests_per_day", 1500)),
    max_modifications_per_minute=int(throttle_config.get("max_modifications_per_minute", 30)),
    min_seconds_between_requests=int(throttle_config.get("min_seconds_between_requests", 0)),
    timezone=config.rule_spec.timezone,
)

journal_path = Path("runtime") / f"journal-{context.run_id}.db"
journal = OrderJournal(journal_path)
executor = ExecutionEngine(
    PaperBroker(fill_on_place=True),
    journal,
    throttle=throttle,
    audit_log=audit,
    monitor=monitor,
)

print("Run ready:", context.run_id)
