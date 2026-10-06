"""V4.2 research configuration: fewer setups, stronger confirmation."""

import os

V42_ENTRY_WAIT_HOURS = int(os.getenv("V42_ENTRY_WAIT_HOURS", "10"))
V42_POST_SL_HOURS = int(os.getenv("V42_POST_SL_HOURS", "72"))

# HTF location/setup.
V42_MAX_SUPPLY_DISTANCE_ATR = float(os.getenv("V42_MAX_SUPPLY_DISTANCE_ATR", "0.85"))
V42_MAX_SUPPLY_PRIOR_TOUCHES = int(os.getenv("V42_MAX_SUPPLY_PRIOR_TOUCHES", "1"))
V42_MAX_SWEEP_AGE_1H = int(os.getenv("V42_MAX_SWEEP_AGE_1H", "3"))
V42_MAX_BREAKDOWN_AGE_1H = int(os.getenv("V42_MAX_BREAKDOWN_AGE_1H", "12"))
V42_ZONE_INVALIDATION_ATR1H = float(os.getenv("V42_ZONE_INVALIDATION_ATR1H", "0.15"))

# Meaningful micro structure + displacement.
V42_PIVOT_LEFT = int(os.getenv("V42_PIVOT_LEFT", "2"))
V42_PIVOT_RIGHT = int(os.getenv("V42_PIVOT_RIGHT", "2"))
V42_MAX_PIVOT_AGE_15M = int(os.getenv("V42_MAX_PIVOT_AGE_15M", "20"))
V42_MIN_DISPLACEMENT_BODY_ATR15 = float(os.getenv("V42_MIN_DISPLACEMENT_BODY_ATR15", "0.65"))
V42_MIN_DISPLACEMENT_RANGE_ATR15 = float(os.getenv("V42_MIN_DISPLACEMENT_RANGE_ATR15", "0.90"))
V42_MIN_DISPLACEMENT_VOL_RATIO = float(os.getenv("V42_MIN_DISPLACEMENT_VOL_RATIO", "1.15"))
V42_BOS_BUFFER_ATR15 = float(os.getenv("V42_BOS_BUFFER_ATR15", "0.08"))
V42_RETEST_WINDOW_BARS = int(os.getenv("V42_RETEST_WINDOW_BARS", "8"))
V42_RETEST_TOLERANCE_ATR15 = float(os.getenv("V42_RETEST_TOLERANCE_ATR15", "0.25"))
V42_RECLAIM_INVALIDATION_ATR15 = float(os.getenv("V42_RECLAIM_INVALIDATION_ATR15", "0.30"))

# Execution.
V42_STOP_BUFFER_ATR15 = float(os.getenv("V42_STOP_BUFFER_ATR15", "0.30"))
V42_MAX_STOP_PCT = float(os.getenv("V42_MAX_STOP_PCT", "6.0"))
V42_MIN_SUPPORT_ROOM_R = float(os.getenv("V42_MIN_SUPPORT_ROOM_R", "2.0"))
V42_MAX_COST_R = float(os.getenv("V42_MAX_COST_R", "0.10"))
V42_MAX_CHASE_ATR1H = float(os.getenv("V42_MAX_CHASE_ATR1H", "0.35"))

# Diagnostics.
V42_FOLLOWTHROUGH_HOURS = (1, 4, 12, 24)
