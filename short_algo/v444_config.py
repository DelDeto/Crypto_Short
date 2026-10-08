"""V4.4.4 60-day research configuration.

M1 remains unchanged as a benchmark.
M2 is rebuilt around support-under-pressure -> breakdown -> failed reclaim.
Trend phase is diagnostic only and is NOT a hard entry gate.
"""
import os

V444_SCAN_CADENCE_HOURS = int(os.getenv("V444_SCAN_CADENCE_HOURS", "4"))
V444_REQUIRED_FUTURE_HOURS = int(os.getenv("V444_REQUIRED_FUTURE_HOURS", "96"))
V444_COOLDOWN_HOURS = int(os.getenv("V444_COOLDOWN_HOURS", "96"))

# M2 support/context.
V444_SUPPORT_LOOKBACK_4H = int(os.getenv("V444_SUPPORT_LOOKBACK_4H", "120"))
V444_SUPPORT_MAX_DISTANCE_ATR = float(os.getenv("V444_SUPPORT_MAX_DISTANCE_ATR", "1.75"))
V444_MIN_PRESSURE_SCORE = int(os.getenv("V444_MIN_PRESSURE_SCORE", "2"))
V444_PRESSURE_LOOKBACK_1H = int(os.getenv("V444_PRESSURE_LOOKBACK_1H", "24"))
V444_NEAR_SUPPORT_ATR = float(os.getenv("V444_NEAR_SUPPORT_ATR", "1.25"))
V444_LOWER_HIGH_BUFFER_ATR = float(os.getenv("V444_LOWER_HIGH_BUFFER_ATR", "0.05"))
V444_COMPRESSION_BUFFER_ATR = float(os.getenv("V444_COMPRESSION_BUFFER_ATR", "0.05"))

# Breakdown / reclaim.
V444_TRIGGER_WAIT_HOURS = int(os.getenv("V444_TRIGGER_WAIT_HOURS", "8"))
V444_BREAK_BUFFER_ATR = float(os.getenv("V444_BREAK_BUFFER_ATR", "0.05"))
V444_BREAK_BODY_MIN_ATR = float(os.getenv("V444_BREAK_BODY_MIN_ATR", "0.25"))
V444_BREAK_BODY_MAX_ATR = float(os.getenv("V444_BREAK_BODY_MAX_ATR", "1.50"))
V444_RETEST_WAIT_BARS = int(os.getenv("V444_RETEST_WAIT_BARS", "12"))
V444_RETEST_TOLERANCE_ATR = float(os.getenv("V444_RETEST_TOLERANCE_ATR", "0.20"))
V444_RECLAIM_INVALIDATION_ATR = float(os.getenv("V444_RECLAIM_INVALIDATION_ATR", "0.30"))
V444_MIN_ACCEPTANCE_BARS = int(os.getenv("V444_MIN_ACCEPTANCE_BARS", "2"))
V444_MIN_CONFIRM_SCORE = int(os.getenv("V444_MIN_CONFIRM_SCORE", "3"))
V444_MAX_ENTRY_BELOW_SUPPORT_ATR = float(
    os.getenv("V444_MAX_ENTRY_BELOW_SUPPORT_ATR", "0.90")
)

# Risk / target.
V444_STOP_BUFFER_ATR = float(os.getenv("V444_STOP_BUFFER_ATR", "0.15"))
V444_MIN_RISK_ATR = float(os.getenv("V444_MIN_RISK_ATR", "0.50"))
V444_MAX_RISK_ATR = float(os.getenv("V444_MAX_RISK_ATR", "1.60"))
V444_MAX_STOP_PCT = float(os.getenv("V444_MAX_STOP_PCT", "6.0"))
V444_MAX_COST_R = float(os.getenv("V444_MAX_COST_R", "0.25"))
V444_MIN_ROOM_R = float(os.getenv("V444_MIN_ROOM_R", "2.20"))
V444_TP1_R = float(os.getenv("V444_TP1_R", "2.00"))
