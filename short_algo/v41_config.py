"""V4.1 entry-quality research configuration."""

import os

V41_ENTRY_WAIT_HOURS = int(os.getenv("V41_ENTRY_WAIT_HOURS", "8"))
V41_ZONE_BUFFER_ATR = float(os.getenv("V41_ZONE_BUFFER_ATR", "0.18"))
V41_STOP_BUFFER_ATR = float(os.getenv("V41_STOP_BUFFER_ATR", "0.12"))
V41_MAX_CHASE_ATR = float(os.getenv("V41_MAX_CHASE_ATR", "0.30"))
V41_MIN_SUPPORT_ROOM_R = float(os.getenv("V41_MIN_SUPPORT_ROOM_R", "2.0"))
V41_MAX_STOP_PCT = float(os.getenv("V41_MAX_STOP_PCT", "6.0"))
V41_CONFIRM_MIN_SCORE = int(os.getenv("V41_CONFIRM_MIN_SCORE", "2"))

V41_POST_SL_HOURS = int(os.getenv("V41_POST_SL_HOURS", "72"))
V41_FOLLOWTHROUGH_HOURS = (1, 4, 12, 24)
