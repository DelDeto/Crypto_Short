"""V4.4.1 dual-model research settings.

M1 = Liquidity Reversal, relaxed from V4.4 by replacing the all-or-nothing
confirmation chain with a causal score after a mandatory supply + liquidity
sweep. Demand room remains a hard gate.

M2 = Support Breakdown Continuation (SBC), designed for EDGE/PONS-like moves:
bearish pressure -> important 4H support -> controlled breakdown -> failed
reclaim/retest -> continuation short. Both models are research-only.
"""
import os

from .config import BACKTEST_FEE_BPS_ROUND_TRIP, BACKTEST_SLIPPAGE_BPS_ROUND_TRIP

V441_SCAN_CADENCE_HOURS = int(os.getenv("V441_SCAN_CADENCE_HOURS", "4"))
V441_REQUIRED_FUTURE_HOURS = int(os.getenv("V441_REQUIRED_FUTURE_HOURS", "96"))
V441_HOLD_HOURS = int(os.getenv("V441_HOLD_HOURS", "24"))
V441_COOLDOWN_HOURS = int(os.getenv("V441_COOLDOWN_HOURS", "96"))

# Common execution/risk controls.
V441_STOP_BUFFER_ATR = float(os.getenv("V441_STOP_BUFFER_ATR", "0.18"))
V441_MIN_RISK_ATR = float(os.getenv("V441_MIN_RISK_ATR", "0.35"))
V441_MAX_RISK_ATR = float(os.getenv("V441_MAX_RISK_ATR", "1.80"))
V441_MAX_STOP_PCT = float(os.getenv("V441_MAX_STOP_PCT", "6.0"))
V441_MAX_COST_R = float(os.getenv("V441_MAX_COST_R", "0.25"))
V441_MIN_ROOM_R = float(os.getenv("V441_MIN_ROOM_R", "2.00"))
V441_TP1_R = float(os.getenv("V441_TP1_R", "2.00"))
V441_DEMAND_TARGET_BUFFER_ATR = float(os.getenv("V441_DEMAND_TARGET_BUFFER_ATR", "0.10"))

# Immediate follow-through remains causal execution management, not a
# retrospective entry filter.
V441_FT_WINDOW_BARS = int(os.getenv("V441_FT_WINDOW_BARS", "4"))
V441_FT_MIN_MFE_R = float(os.getenv("V441_FT_MIN_MFE_R", "0.25"))
V441_FT_RECLAIM_BUFFER_ATR = float(os.getenv("V441_FT_RECLAIM_BUFFER_ATR", "0.08"))

# M1 - Liquidity Reversal.
V441_M1_TRIGGER_WAIT_HOURS = int(os.getenv("V441_M1_TRIGGER_WAIT_HOURS", "6"))
V441_M1_CONFIRM_WAIT_BARS = int(os.getenv("V441_M1_CONFIRM_WAIT_BARS", "4"))
V441_M1_LIQ_LOOKBACK_BARS = int(os.getenv("V441_M1_LIQ_LOOKBACK_BARS", "24"))
V441_M1_LIQ_CLUSTER_ATR = float(os.getenv("V441_M1_LIQ_CLUSTER_ATR", "0.12"))
V441_M1_LIQ_MIN_TOUCHES = int(os.getenv("V441_M1_LIQ_MIN_TOUCHES", "2"))
V441_M1_LIQ_MIN_SEPARATION_BARS = int(os.getenv("V441_M1_LIQ_MIN_SEPARATION_BARS", "2"))
V441_M1_LIQ_ZONE_BELOW_ATR = float(os.getenv("V441_M1_LIQ_ZONE_BELOW_ATR", "0.25"))
V441_M1_LIQ_ZONE_ABOVE_ATR = float(os.getenv("V441_M1_LIQ_ZONE_ABOVE_ATR", "0.55"))
V441_M1_SWEEP_BUFFER_ATR = float(os.getenv("V441_M1_SWEEP_BUFFER_ATR", "0.03"))
V441_M1_CLOSE_TOLERANCE_ATR = float(os.getenv("V441_M1_CLOSE_TOLERANCE_ATR", "0.05"))
V441_M1_BOS_LOOKBACK_BARS = int(os.getenv("V441_M1_BOS_LOOKBACK_BARS", "4"))
V441_M1_BREAK_BUFFER_ATR = float(os.getenv("V441_M1_BREAK_BUFFER_ATR", "0.03"))
V441_M1_BODY_MIN_ATR = float(os.getenv("V441_M1_BODY_MIN_ATR", "0.25"))
V441_M1_BODY_MAX_ATR = float(os.getenv("V441_M1_BODY_MAX_ATR", "1.30"))
V441_M1_MIN_REJECTION_WICK_RATIO = float(os.getenv("V441_M1_MIN_REJECTION_WICK_RATIO", "0.15"))
V441_M1_MIN_CONFIRM_SCORE = int(os.getenv("V441_M1_MIN_CONFIRM_SCORE", "3"))
V441_M1_NO_CHASE_ATR = float(os.getenv("V441_M1_NO_CHASE_ATR", "1.10"))

# M2 - Support Breakdown Continuation (EDGE-like).
V441_M2_SUPPORT_LOOKBACK_4H = int(os.getenv("V441_M2_SUPPORT_LOOKBACK_4H", "120"))
V441_M2_SUPPORT_CLUSTER_ATR = float(os.getenv("V441_M2_SUPPORT_CLUSTER_ATR", "0.35"))
V441_M2_SUPPORT_MIN_TOUCHES = int(os.getenv("V441_M2_SUPPORT_MIN_TOUCHES", "2"))
V441_M2_SUPPORT_MIN_SEPARATION_BARS = int(os.getenv("V441_M2_SUPPORT_MIN_SEPARATION_BARS", "2"))
V441_M2_MAX_DISTANCE_ATR = float(os.getenv("V441_M2_MAX_DISTANCE_ATR", "1.75"))
V441_M2_MAX_PREBROKEN_ATR = float(os.getenv("V441_M2_MAX_PREBROKEN_ATR", "0.35"))
V441_M2_TRIGGER_WAIT_HOURS = int(os.getenv("V441_M2_TRIGGER_WAIT_HOURS", "8"))
V441_M2_BREAK_BUFFER_ATR = float(os.getenv("V441_M2_BREAK_BUFFER_ATR", "0.05"))
V441_M2_BREAK_BODY_MIN_ATR = float(os.getenv("V441_M2_BREAK_BODY_MIN_ATR", "0.35"))
V441_M2_BREAK_BODY_MAX_ATR = float(os.getenv("V441_M2_BREAK_BODY_MAX_ATR", "1.50"))
V441_M2_RETEST_WAIT_BARS = int(os.getenv("V441_M2_RETEST_WAIT_BARS", "12"))
V441_M2_RETEST_TOLERANCE_ATR = float(os.getenv("V441_M2_RETEST_TOLERANCE_ATR", "0.20"))
V441_M2_RECLAIM_INVALIDATION_ATR = float(os.getenv("V441_M2_RECLAIM_INVALIDATION_ATR", "0.30"))
V441_M2_MIN_CONFIRM_SCORE = int(os.getenv("V441_M2_MIN_CONFIRM_SCORE", "3"))
V441_M2_NO_CHASE_ATR = float(os.getenv("V441_M2_NO_CHASE_ATR", "1.20"))
V441_M2_NEXT_DEMAND_GAP_ATR = float(os.getenv("V441_M2_NEXT_DEMAND_GAP_ATR", "0.25"))

V441_COST_BPS = (
    BACKTEST_FEE_BPS_ROUND_TRIP + BACKTEST_SLIPPAGE_BPS_ROUND_TRIP
)
