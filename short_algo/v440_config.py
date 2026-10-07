"""V4.4 structural short-entry research settings.

V4.4 is a fixed, causal rule set built from the V4.3.1 findings:
real liquidity pool -> sweep/failed auction -> controlled micro BOS ->
next-open entry -> demand-aware room gate -> causal follow-through management.

Research only. It does not modify the live V1 scanner.
"""
import os

from .config import BACKTEST_FEE_BPS_ROUND_TRIP, BACKTEST_SLIPPAGE_BPS_ROUND_TRIP

V440_SCAN_CADENCE_HOURS = int(os.getenv("V440_SCAN_CADENCE_HOURS", "4"))
V440_REQUIRED_FUTURE_HOURS = int(os.getenv("V440_REQUIRED_FUTURE_HOURS", "96"))
V440_HOLD_HOURS = int(os.getenv("V440_HOLD_HOURS", "24"))
V440_TRIGGER_WAIT_HOURS = int(os.getenv("V440_TRIGGER_WAIT_HOURS", "6"))

# Real buy-side liquidity pool: repeated highs known before the sweep.
V440_LIQ_LOOKBACK_BARS = int(os.getenv("V440_LIQ_LOOKBACK_BARS", "24"))
V440_LIQ_CLUSTER_ATR = float(os.getenv("V440_LIQ_CLUSTER_ATR", "0.12"))
V440_LIQ_MIN_TOUCHES = int(os.getenv("V440_LIQ_MIN_TOUCHES", "2"))
V440_LIQ_MIN_SEPARATION_BARS = int(os.getenv("V440_LIQ_MIN_SEPARATION_BARS", "2"))
V440_LIQ_ZONE_BELOW_ATR = float(os.getenv("V440_LIQ_ZONE_BELOW_ATR", "0.20"))
V440_LIQ_ZONE_ABOVE_ATR = float(os.getenv("V440_LIQ_ZONE_ABOVE_ATR", "0.45"))

# Sweep / failed-auction confirmation.
V440_SWEEP_BUFFER_ATR = float(os.getenv("V440_SWEEP_BUFFER_ATR", "0.03"))
V440_MIN_SWEEP_UPPER_WICK_RATIO = float(os.getenv("V440_MIN_SWEEP_UPPER_WICK_RATIO", "0.20"))
V440_SWEEP_RECLAIM_BUFFER_ATR = float(os.getenv("V440_SWEEP_RECLAIM_BUFFER_ATR", "0.12"))

# Controlled bearish break after the sweep. Fixed from the V4.3.1 decomposition.
V440_BOS_LOOKBACK_BARS = int(os.getenv("V440_BOS_LOOKBACK_BARS", "4"))
V440_BOS_WAIT_BARS = int(os.getenv("V440_BOS_WAIT_BARS", "4"))
V440_BREAK_BUFFER_ATR = float(os.getenv("V440_BREAK_BUFFER_ATR", "0.03"))
V440_BREAK_BODY_MIN_ATR = float(os.getenv("V440_BREAK_BODY_MIN_ATR", "0.70"))
V440_BREAK_BODY_MAX_ATR = float(os.getenv("V440_BREAK_BODY_MAX_ATR", "1.00"))
V440_NO_CHASE_ATR = float(os.getenv("V440_NO_CHASE_ATR", "1.10"))

# Structural stop and cost controls.
V440_STOP_BUFFER_ATR = float(os.getenv("V440_STOP_BUFFER_ATR", "0.18"))
V440_MIN_RISK_ATR = float(os.getenv("V440_MIN_RISK_ATR", "0.35"))
V440_MAX_RISK_ATR = float(os.getenv("V440_MAX_RISK_ATR", "1.80"))
V440_MAX_STOP_PCT = float(os.getenv("V440_MAX_STOP_PCT", "6.0"))
V440_MAX_COST_R = float(os.getenv("V440_MAX_COST_R", "0.25"))

# Demand is a hard room-to-target gate, not just a diagnostic.
V440_DEMAND_4H_BARS = int(os.getenv("V440_DEMAND_4H_BARS", "90"))
V440_DEMAND_1H_BARS = int(os.getenv("V440_DEMAND_1H_BARS", "160"))
V440_DEMAND_CLUSTER_ATR = float(os.getenv("V440_DEMAND_CLUSTER_ATR", "0.35"))
V440_DEMAND_BROKEN_ATR = float(os.getenv("V440_DEMAND_BROKEN_ATR", "0.20"))
V440_DEMAND_4H_WIDTH_ATR = float(os.getenv("V440_DEMAND_4H_WIDTH_ATR", "0.60"))
V440_DEMAND_1H_WIDTH_ATR = float(os.getenv("V440_DEMAND_1H_WIDTH_ATR", "0.45"))
V440_DEMAND_TARGET_BUFFER_ATR = float(os.getenv("V440_DEMAND_TARGET_BUFFER_ATR", "0.10"))
V440_MIN_ROOM_R = float(os.getenv("V440_MIN_ROOM_R", "2.20"))
V440_TP1_R = float(os.getenv("V440_TP1_R", "2.00"))

# Immediate follow-through is causal: if the trade cannot prove itself within
# the first hour, V4.4 exits early instead of retrospectively filtering it.
V440_FT_WINDOW_BARS = int(os.getenv("V440_FT_WINDOW_BARS", "4"))
V440_FT_MIN_MFE_R = float(os.getenv("V440_FT_MIN_MFE_R", "0.25"))
V440_FT_RECLAIM_BUFFER_ATR = float(os.getenv("V440_FT_RECLAIM_BUFFER_ATR", "0.05"))

V440_COOLDOWN_HOURS = int(os.getenv("V440_COOLDOWN_HOURS", "96"))

V440_COST_BPS = (
    BACKTEST_FEE_BPS_ROUND_TRIP + BACKTEST_SLIPPAGE_BPS_ROUND_TRIP
)
