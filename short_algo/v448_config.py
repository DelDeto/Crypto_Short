"""V4.4.8 parallel M2 execution research.

Both models reuse the V4.4.7 Persistent Broken Support state machine.

M2-A (MAJOR_4H_DEMAND)
- tactical stop above the latest confirmed lower-high/reclaim structure;
- only 4H demand is used as the structural destination;
- TP1 = 2R, TP2 = major 4H demand;
- requires at least 2R room to that major demand.

M2-B (OPEN_SPACE_RISK_LADDER)
- same persistent state machine and tactical stop;
- requires no nearby major 4H demand (none found, or demand >=4R away);
- TP1 = 2R on 50%;
- TP2 = 4R on 25%;
- final 25% runner targets major 4H demand when available, otherwise is held
  until the long-horizon timeout with a protective profit stop.

The two workflows are independent and can run in parallel.
"""
import os

V448_HOLD_HOURS = int(os.getenv("V448_HOLD_HOURS", "96"))

V448_STOP_BUFFER_ATR = float(os.getenv("V448_STOP_BUFFER_ATR", "0.12"))
V448_MIN_RISK_ATR = float(os.getenv("V448_MIN_RISK_ATR", "0.50"))
V448_MAX_RISK_ATR = float(os.getenv("V448_MAX_RISK_ATR", "2.50"))
V448_MAX_STOP_PCT = float(os.getenv("V448_MAX_STOP_PCT", "8.0"))
V448_MAX_COST_R = float(os.getenv("V448_MAX_COST_R", "0.25"))

V448_TP1_R = float(os.getenv("V448_TP1_R", "2.00"))
V448_B_TP2_R = float(os.getenv("V448_B_TP2_R", "4.00"))

V448_A_MIN_MAJOR_ROOM_R = float(
    os.getenv("V448_A_MIN_MAJOR_ROOM_R", "2.00")
)
V448_OPEN_SPACE_MIN_MAJOR_ROOM_R = float(
    os.getenv("V448_OPEN_SPACE_MIN_MAJOR_ROOM_R", "4.00")
)
V448_MAJOR_DEMAND_TARGET_BUFFER_ATR = float(
    os.getenv("V448_MAJOR_DEMAND_TARGET_BUFFER_ATR", "0.10")
)
