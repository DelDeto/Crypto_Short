"""M3 V1 — Intraday Bearish Pullback Continuation research defaults."""
import os

M3_DAYS = int(os.getenv("M3_DAYS", "60"))
M3_HOLD_HOURS = int(os.getenv("M3_HOLD_HOURS", "24"))
M3_COOLDOWN_HOURS = int(os.getenv("M3_COOLDOWN_HOURS", "6"))

M3_MIN_4H_BEAR_SCORE = int(os.getenv("M3_MIN_4H_BEAR_SCORE", "2"))
M3_IMPULSE_LOOKBACK_1H = int(os.getenv("M3_IMPULSE_LOOKBACK_1H", "14"))
M3_MIN_IMPULSE_ATR = float(os.getenv("M3_MIN_IMPULSE_ATR", "1.20"))
M3_MIN_PULLBACK_RETRACE = float(os.getenv("M3_MIN_PULLBACK_RETRACE", "0.18"))
M3_MAX_PULLBACK_RETRACE = float(os.getenv("M3_MAX_PULLBACK_RETRACE", "0.72"))
M3_MAX_RESISTANCE_DISTANCE_ATR = float(
    os.getenv("M3_MAX_RESISTANCE_DISTANCE_ATR", "0.65")
)
M3_MAX_EMA20_DISTANCE_ATR = float(
    os.getenv("M3_MAX_EMA20_DISTANCE_ATR", "2.50")
)

M3_CONFIRM_WINDOW_MINUTES = int(os.getenv("M3_CONFIRM_WINDOW_MINUTES", "120"))
M3_STOP_BUFFER_ATR = float(os.getenv("M3_STOP_BUFFER_ATR", "0.20"))
M3_MIN_RISK_ATR = float(os.getenv("M3_MIN_RISK_ATR", "0.60"))
M3_MAX_RISK_ATR = float(os.getenv("M3_MAX_RISK_ATR", "2.50"))

M3_TARGET_ATR_VARIANTS = tuple(
    float(x.strip())
    for x in os.getenv("M3_TARGET_ATR_VARIANTS", "1.0,1.5,2.0").split(",")
    if x.strip()
)
