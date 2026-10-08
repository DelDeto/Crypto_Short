"""V4.4.8 M2-only execution configuration.

The V4.4.7 persistent broken-support state machine is retained.
Only post-SHORT_READY execution is changed:
- tactical stop uses recent reclaim/lower-high structure;
- only MAJOR 4H demand can block/anchor a target;
- minor 1H demand is informational, never a hard entry gate;
- open space uses a risk ladder: 2R -> 4R -> runner.
"""
import os

V448_M2_HOLD_HOURS = int(os.getenv("V448_M2_HOLD_HOURS", "96"))

V448_M2_STOP_BUFFER_ATR = float(os.getenv("V448_M2_STOP_BUFFER_ATR", "0.12"))
V448_M2_MIN_RISK_ATR = float(os.getenv("V448_M2_MIN_RISK_ATR", "0.50"))
V448_M2_MAX_RISK_ATR = float(os.getenv("V448_M2_MAX_RISK_ATR", "2.50"))
V448_M2_MAX_STOP_PCT = float(os.getenv("V448_M2_MAX_STOP_PCT", "8.0"))
V448_M2_MAX_COST_R = float(os.getenv("V448_M2_MAX_COST_R", "0.25"))

V448_M2_TP1_R = float(os.getenv("V448_M2_TP1_R", "2.00"))
V448_M2_OPEN_TP2_R = float(os.getenv("V448_M2_OPEN_TP2_R", "4.00"))
V448_M2_MIN_MAJOR_ROOM_R = float(os.getenv("V448_M2_MIN_MAJOR_ROOM_R", "2.00"))
V448_M2_OPEN_SPACE_ROOM_R = float(os.getenv("V448_M2_OPEN_SPACE_ROOM_R", "4.00"))

V448_M2_MAJOR_LOOKBACK_4H = int(os.getenv("V448_M2_MAJOR_LOOKBACK_4H", "360"))
V448_M2_MAJOR_CLUSTER_ATR = float(os.getenv("V448_M2_MAJOR_CLUSTER_ATR", "0.60"))
V448_M2_MAJOR_MIN_SEPARATION_BARS = int(
    os.getenv("V448_M2_MAJOR_MIN_SEPARATION_BARS", "4")
)
V448_M2_MAJOR_DEPARTURE_ATR = float(
    os.getenv("V448_M2_MAJOR_DEPARTURE_ATR", "2.00")
)
V448_M2_MAJOR_WIDTH_ATR = float(os.getenv("V448_M2_MAJOR_WIDTH_ATR", "0.80"))
V448_M2_MAJOR_TARGET_BUFFER_ATR = float(
    os.getenv("V448_M2_MAJOR_TARGET_BUFFER_ATR", "0.10")
)
