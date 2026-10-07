"""V4.3.1 fixed micro-entry research settings.

One frozen parameter set only. This version compares A0 baseline with three
15m trigger variants and one conditional re-entry per variant. It is research
only and does not modify the live V1 scanner.
"""
import os

from .config import BACKTEST_FEE_BPS_ROUND_TRIP, BACKTEST_SLIPPAGE_BPS_ROUND_TRIP

V431_SCAN_CADENCE_HOURS = int(os.getenv("V431_SCAN_CADENCE_HOURS", "4"))
V431_REQUIRED_FUTURE_HOURS = int(os.getenv("V431_REQUIRED_FUTURE_HOURS", "96"))
V431_HOLD_HOURS = int(os.getenv("V431_HOLD_HOURS", "24"))
V431_TRIGGER_WAIT_HOURS = int(os.getenv("V431_TRIGGER_WAIT_HOURS", "4"))
V431_A3_BREAK_WAIT_BARS = int(os.getenv("V431_A3_BREAK_WAIT_BARS", "4"))

# Fixed micro-timing thresholds. Do not grid-search these on the 60d slice.
V431_TOUCH_TOLERANCE_ATR = float(os.getenv("V431_TOUCH_TOLERANCE_ATR", "0.12"))
V431_SWEEP_BUFFER_ATR = float(os.getenv("V431_SWEEP_BUFFER_ATR", "0.03"))
V431_BREAK_BUFFER_ATR = float(os.getenv("V431_BREAK_BUFFER_ATR", "0.03"))
V431_NO_CHASE_ATR = float(os.getenv("V431_NO_CHASE_ATR", "0.65"))
V431_STOP_BUFFER_ATR = float(os.getenv("V431_STOP_BUFFER_ATR", "0.18"))
V431_MIN_RISK_ATR = float(os.getenv("V431_MIN_RISK_ATR", "0.35"))
V431_MAX_RISK_ATR = float(os.getenv("V431_MAX_RISK_ATR", "1.80"))
V431_MAX_STOP_PCT = float(os.getenv("V431_MAX_STOP_PCT", "6.0"))
V431_MAX_COST_R = float(os.getenv("V431_MAX_COST_R", "0.25"))
V431_FOLLOWTHROUGH_R = float(os.getenv("V431_FOLLOWTHROUGH_R", "0.50"))

# Conditional one-shot re-entry after a realized stop.
V431_C_WAIT_HOURS = int(os.getenv("V431_C_WAIT_HOURS", "36"))
V431_C_RECLAIM_BUFFER_ATR = float(os.getenv("V431_C_RECLAIM_BUFFER_ATR", "0.12"))
V431_C_MIN_BODY_ATR = float(os.getenv("V431_C_MIN_BODY_ATR", "0.12"))
V431_C_MAX_RISK_MULT = float(os.getenv("V431_C_MAX_RISK_MULT", "2.0"))

# Structural support and independence diagnostics.
V431_STRUCTURAL_ROOM_R = float(os.getenv("V431_STRUCTURAL_ROOM_R", "2.20"))
V431_COOLDOWN_HOURS = int(os.getenv("V431_COOLDOWN_HOURS", "96"))

V431_COST_BPS = (
    BACKTEST_FEE_BPS_ROUND_TRIP + BACKTEST_SLIPPAGE_BPS_ROUND_TRIP
)
