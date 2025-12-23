FTMO Bot v3 Flight Test Checklist (v1)

Preflight
- Freeze config and verify lock: scripts/freeze_config.py configs/ftmo_v1.yaml
- Generate run_id and confirm audit log path is writable
- Confirm stage/timezone/buffers match the attempt (challenge/verification/funded)
- Confirm throttle limits and request pacing are active

Red Team Scenarios
- Floating loss across Prague midnight triggers day reset correctly
- DST/UTC offset does not shift Prague day boundary
- Risk governor blocks near-buffer entries and respects reduce-only/flatten policy
- Restart does not duplicate orders (journal idempotency)
- Rejected/partial orders remain consistent in journal and logs
- Broker disconnect triggers alerts and trading halt

Forward Test Run
- Zero rule breaches and zero buffer breaches
- Stable behavior in slow/volatile markets
- No order-modification spam
- Audit log can replay decisions end-to-end

Postflight Review
- Review audit log for policy decisions and any near-breaches
- Confirm runtime HUD shows correct day-start equity and headroom
- Archive run artifacts with config hash
