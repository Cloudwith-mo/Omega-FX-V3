FTMO Bot v3 — Release Notes

v0.2.0 — Simulator v2
- Equity-based mark-to-market using worst-case OHLC (with optional close mode).
- Fees model per symbol (commission round-trip, swap per day) included in headroom logic.
- Prague midnight reset handling and regression coverage for floating-loss trap.
- Simulation output includes min headroom, breach events, and updated report format.

v0.3.0 — Strategy + Sizer v1
- Mean reversion strategy (Bollinger + RSI + ATR stops) with trading window and position caps.
- Risk-based sizing shared via Sizer with per-trade risk cap.
- OrderIntent carries stop/TP and strategy_id for audit visibility.
- Strategy and simulator tests added for sizing and v2 behaviors.
