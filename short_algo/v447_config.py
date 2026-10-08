"""V4.4.7 Persistent Broken Support Watch.

A confirmed 4H break opens a stateful event that can remain active for up to
7 days. Entry is not tied to a fixed number of hours after the break.

The event is cancelled only by a confirmed 4H reclaim. It becomes SHORT_READY
through either:
  A) a real retest of the broken support that closes back below the zone; or
  B) persistent failure to reclaim for >=24h plus a lower-high structure.

M1-A/M1-B remain unchanged benchmarks.
"""
import os

V447_SCAN_CADENCE_HOURS = int(os.getenv("V447_SCAN_CADENCE_HOURS", "4"))
V447_DAYS = int(os.getenv("V447_DAYS", "60"))

# Full 60d signal window + enough future data for 7d watch and trade outcome.
V447_WATCH_DAYS = int(os.getenv("V447_WATCH_DAYS", "7"))
V447_HOLD_BUFFER_DAYS = int(os.getenv("V447_HOLD_BUFFER_DAYS", "4"))
V447_FUTURE_BUFFER_DAYS = V447_WATCH_DAYS + V447_HOLD_BUFFER_DAYS
V447_COOLDOWN_HOURS = int(os.getenv("V447_COOLDOWN_HOURS", "96"))

# 4H structural break / zone.
V447_BREAK_DETECT_HOURS = int(os.getenv("V447_BREAK_DETECT_HOURS", "8"))
V447_BREAK_BUFFER_ATR = float(os.getenv("V447_BREAK_BUFFER_ATR", "0.05"))
V447_RECLAIM_BUFFER_ATR = float(os.getenv("V447_RECLAIM_BUFFER_ATR", "0.10"))
V447_RECLAIM_CONFIRM_4H = int(os.getenv("V447_RECLAIM_CONFIRM_4H", "2"))
V447_RETEST_TOUCH_ATR = float(os.getenv("V447_RETEST_TOUCH_ATR", "0.20"))
V447_MIN_REJECTION_WICK_RATIO = float(
    os.getenv("V447_MIN_REJECTION_WICK_RATIO", "0.20")
)

# Persistent no-reclaim branch.
V447_PERSIST_MIN_4H_BARS = int(os.getenv("V447_PERSIST_MIN_4H_BARS", "6"))
V447_PERSIST_WINDOW_4H = int(os.getenv("V447_PERSIST_WINDOW_4H", "6"))
V447_PERSIST_MIN_CLOSES_BELOW = int(
    os.getenv("V447_PERSIST_MIN_CLOSES_BELOW", "5")
)
V447_LOWER_HIGH_LOOKBACK_4H = int(
    os.getenv("V447_LOWER_HIGH_LOOKBACK_4H", "6")
)
V447_LOWER_HIGH_BUFFER_ATR = float(
    os.getenv("V447_LOWER_HIGH_BUFFER_ATR", "0.05")
)

# After SHORT_READY, wait briefly for a causal 1H bearish confirmation.
V447_ENTRY_CONFIRM_HOURS = int(os.getenv("V447_ENTRY_CONFIRM_HOURS", "12"))
V447_MAX_ENTRY_BELOW_SUPPORT_ATR = float(
    os.getenv("V447_MAX_ENTRY_BELOW_SUPPORT_ATR", "2.50")
)

# Risk / targets.
V447_STOP_BUFFER_ATR = float(os.getenv("V447_STOP_BUFFER_ATR", "0.15"))
V447_MIN_RISK_ATR = float(os.getenv("V447_MIN_RISK_ATR", "0.50"))
V447_MAX_RISK_ATR = float(os.getenv("V447_MAX_RISK_ATR", "2.50"))
V447_MAX_STOP_PCT = float(os.getenv("V447_MAX_STOP_PCT", "8.0"))
V447_MAX_COST_R = float(os.getenv("V447_MAX_COST_R", "0.25"))
V447_MIN_ROOM_R = float(os.getenv("V447_MIN_ROOM_R", "2.00"))
V447_TP1_R = float(os.getenv("V447_TP1_R", "2.00"))
