"""Simple baselines used to challenge the V2/V2.1 rules.

A complex setup should beat a transparent baseline before being promoted.
"""

import math

from .indicators import atr, return_pct


def bollinger_reversal_short(frame):
    """Return a simple Bollinger failed-extension Short plan or None.

    Rule:
    - positive 24h context;
    - current candle trades above the 20-period upper 2-sigma band;
    - candle closes back below that upper band;
    - stop above the signal high with ATR buffer;
    - TP1 fixed at 2R.

    This deliberately avoids SMC/supply/liquidity concepts so it can act as a
    clean benchmark for the more complex Liquidity Reversal model.
    """
    if frame is None or len(frame) < 35:
        return None

    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    mean20 = close.rolling(20).mean()
    std20 = close.rolling(20).std(ddof=0)
    upper = mean20 + 2.0 * std20

    upper_now = float(upper.iloc[-1])
    if not math.isfinite(upper_now) or upper_now <= 0:
        return None

    current = float(close.iloc[-1])
    signal_high = float(high.iloc[-1])
    ret24 = return_pct(close, 24)
    failed_extension = signal_high > upper_now and current < upper_now

    if ret24 <= 0.0 or not failed_extension:
        return None

    a = float(atr(frame).iloc[-1])
    if not math.isfinite(a) or a <= 0:
        return None

    stop = max(signal_high + 0.15 * a, current + 0.8 * a)
    risk = stop - current
    if risk <= 0:
        return None

    stop_pct = risk / max(current, 1e-12) * 100.0
    if stop_pct > 8.0:
        return None

    return {
        "model": "BOLLINGER_MEAN_REVERSION",
        "strategy_family": "BOLLINGER_BASELINE",
        "status": "BASELINE",
        "score": None,
        "top_gainer_context": ret24 >= 5.0,
        "return_24h_pct": round(ret24, 3),
        "entry": current,
        "stop": stop,
        "stop_pct": round(stop_pct, 3),
        "tp1": current - 2.0 * risk,
        "tp2": current - 3.0 * risk,
        "runner": current - 5.0 * risk,
        "risk_per_unit": risk,
        "support_room_r": None,
        "supply_distance_atr": None,
        "atr_pct_1h": round(a / max(current, 1e-12) * 100.0, 3),
        "reasons": ["upper Bollinger extension failed back inside band"],
        "filters": {},
        "v21_status": "BASELINE",
        "v21_priority": "NORMAL",
    }
