import math

import numpy as np
import pandas as pd


def safe_float(value, default=None):
    try:
        if value is None:
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def ema(series, span):
    return series.astype(float).ewm(span=span, adjust=False).mean()


def atr(frame, period=14):
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    close = frame["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=max(5, period // 2)).mean()


def return_pct(series, bars):
    values = series.astype(float)
    if len(values) <= bars:
        return 0.0
    start = float(values.iloc[-bars - 1])
    end = float(values.iloc[-1])
    return 0.0 if start == 0 else (end / start - 1.0) * 100.0


def volume_ratio(frame, lookback=20):
    volume = frame["volume"].astype(float)
    if len(volume) < lookback + 1:
        return 1.0
    baseline = float(volume.iloc[-lookback - 1:-1].median())
    return float(volume.iloc[-1]) / max(baseline, 1e-12)


def swing_points(frame, left=2, right=2):
    highs = frame["high"].astype(float).to_numpy()
    lows = frame["low"].astype(float).to_numpy()
    idx = frame.index
    swing_highs, swing_lows = [], []

    for i in range(left, len(frame) - right):
        h = highs[i]
        l = lows[i]
        if h >= np.max(highs[i - left:i + right + 1]):
            swing_highs.append({"pos": i, "price": float(h), "time": idx[i]})
        if l <= np.min(lows[i - left:i + right + 1]):
            swing_lows.append({"pos": i, "price": float(l), "time": idx[i]})

    return swing_highs, swing_lows


def structure_snapshot(frame):
    close = frame["close"].astype(float)
    e20 = ema(close, 20)
    e50 = ema(close, 50)
    e100 = ema(close, 100) if len(close) >= 100 else e50
    current = float(close.iloc[-1])
    a = float(atr(frame).iloc[-1])
    highs, lows = swing_points(frame)

    lower_high = False
    lower_low = False
    if len(highs) >= 2:
        lower_high = highs[-1]["price"] < highs[-2]["price"]
    if len(lows) >= 2:
        lower_low = lows[-1]["price"] < lows[-2]["price"]

    ema_bear = current < float(e20.iloc[-1]) < float(e50.iloc[-1])
    macro_bear = float(e50.iloc[-1]) <= float(e100.iloc[-1]) or current < float(e100.iloc[-1])

    return {
        "close": current,
        "atr": a,
        "atr_pct": a / max(current, 1e-12) * 100.0,
        "ema20": float(e20.iloc[-1]),
        "ema50": float(e50.iloc[-1]),
        "ema100": float(e100.iloc[-1]),
        "ema_bear": ema_bear,
        "macro_bear": macro_bear,
        "lower_high": lower_high,
        "lower_low": lower_low,
        "swing_highs": highs,
        "swing_lows": lows,
    }


def bearish_rejection(last_row):
    o = float(last_row["open"])
    h = float(last_row["high"])
    l = float(last_row["low"])
    c = float(last_row["close"])
    candle_range = max(h - l, 1e-12)
    upper_wick = h - max(o, c)
    body = abs(c - o)
    return c < o and upper_wick / candle_range >= 0.35 and upper_wick >= body * 0.8
