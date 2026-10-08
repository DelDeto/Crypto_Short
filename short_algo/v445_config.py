"""V4.4.5 60-day execution research.

M1 keeps setup detection unchanged and tests alternative causal entry timing.
M2 treats structural support breaks as events, records a 24h path for research,
and separately tests causal acceptance/retest entries. 24h path labels are never
used to decide an entry in the same replay.
"""
import os

V445_SCAN_CADENCE_HOURS = int(os.getenv("V445_SCAN_CADENCE_HOURS", "4"))
V445_REQUIRED_FUTURE_HOURS = int(os.getenv("V445_REQUIRED_FUTURE_HOURS", "96"))
V445_COOLDOWN_HOURS = int(os.getenv("V445_COOLDOWN_HOURS", "96"))

# M1 entry lab.
V445_M1_E1_WAIT_BARS = int(os.getenv("V445_M1_E1_WAIT_BARS", "8"))   # 2h
V445_M1_E2_WAIT_BARS = int(os.getenv("V445_M1_E2_WAIT_BARS", "16"))  # 4h
V445_M1_E1_RETRACE = float(os.getenv("V445_M1_E1_RETRACE", "0.50"))
V445_M1_E2_RETRACE = float(os.getenv("V445_M1_E2_RETRACE", "0.65"))
V445_M1_STOP_BUFFER_ATR = float(os.getenv("V445_M1_STOP_BUFFER_ATR", "0.18"))
V445_M1_MIN_RISK_ATR = float(os.getenv("V445_M1_MIN_RISK_ATR", "0.35"))
V445_M1_MAX_RISK_ATR = float(os.getenv("V445_M1_MAX_RISK_ATR", "1.80"))
V445_M1_MAX_STOP_PCT = float(os.getenv("V445_M1_MAX_STOP_PCT", "6.0"))
V445_M1_MAX_COST_R = float(os.getenv("V445_M1_MAX_COST_R", "0.25"))
V445_M1_MIN_ROOM_R = float(os.getenv("V445_M1_MIN_ROOM_R", "2.20"))
V445_M1_TP1_R = float(os.getenv("V445_M1_TP1_R", "2.00"))

# M2 event study and causal variants.
V445_M2_TRIGGER_WAIT_HOURS = int(os.getenv("V445_M2_TRIGGER_WAIT_HOURS", "8"))
V445_M2_EVENT_HOURS = int(os.getenv("V445_M2_EVENT_HOURS", "24"))
V445_M2_BREAK_BUFFER_ATR = float(os.getenv("V445_M2_BREAK_BUFFER_ATR", "0.05"))
V445_M2_HARD_RECLAIM_ATR = float(os.getenv("V445_M2_HARD_RECLAIM_ATR", "0.30"))
V445_M2_RETEST_TOLERANCE_ATR = float(os.getenv("V445_M2_RETEST_TOLERANCE_ATR", "0.20"))
V445_M2_ACCEPTANCE_CLOSES = int(os.getenv("V445_M2_ACCEPTANCE_CLOSES", "3"))
V445_M2_MAX_CHASE_ATR = float(os.getenv("V445_M2_MAX_CHASE_ATR", "0.90"))
V445_M2_NEAR_ENTRY_ATR = float(os.getenv("V445_M2_NEAR_ENTRY_ATR", "0.20"))
V445_M2_STOP_BUFFER_ATR = float(os.getenv("V445_M2_STOP_BUFFER_ATR", "0.15"))
V445_M2_MIN_RISK_ATR = float(os.getenv("V445_M2_MIN_RISK_ATR", "0.50"))
V445_M2_MAX_RISK_ATR = float(os.getenv("V445_M2_MAX_RISK_ATR", "1.60"))
V445_M2_MAX_STOP_PCT = float(os.getenv("V445_M2_MAX_STOP_PCT", "6.0"))
V445_M2_MAX_COST_R = float(os.getenv("V445_M2_MAX_COST_R", "0.25"))
V445_M2_MIN_ROOM_R = float(os.getenv("V445_M2_MIN_ROOM_R", "2.20"))
V445_M2_TP1_R = float(os.getenv("V445_M2_TP1_R", "2.00"))
