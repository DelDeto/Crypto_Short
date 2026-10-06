"""Timestamp-safe regime routing for V4.

The router intentionally uses only candles closed at the signal timestamp.
"""

from .indicators import atr, return_pct, structure_snapshot


def _leg(frame):
    if frame is None or len(frame) < 60:
        return None
    snap = structure_snapshot(frame)
    close = frame["close"].astype(float)
    current = float(close.iloc[-1])
    a = float(atr(frame).iloc[-1])
    atr_pct = a / max(current, 1e-12) * 100.0
    return {
        "r4": float(return_pct(close, 4)),
        "r24": float(return_pct(close, 24)),
        "atr_pct": atr_pct,
        "above_ema20": bool(current > float(snap["ema20"])),
        "below_ema20": bool(current < float(snap["ema20"])),
        "ema_bear": bool(snap["ema_bear"]),
        "lower_high": bool(snap["lower_high"]),
        "lower_low": bool(snap["lower_low"]),
    }


def route_v4_regime(btc_one, eth_one, coin_one):
    btc = _leg(btc_one)
    eth = _leg(eth_one)
    coin = _leg(coin_one)

    if btc is None or eth is None:
        return {
            "risk_state": "UNKNOWN",
            "trend_state": "UNKNOWN",
            "vol_state": "UNKNOWN",
            "local_vol_state": "UNKNOWN",
            "regime_key": "UNKNOWN",
            "market_r4": 0.0,
            "market_r24": 0.0,
            "market_atr_pct": 0.0,
        }

    market_r4 = (btc["r4"] + eth["r4"]) / 2.0
    market_r24 = (btc["r24"] + eth["r24"]) / 2.0
    market_atr_pct = (btc["atr_pct"] + eth["atr_pct"]) / 2.0

    both_above = btc["above_ema20"] and eth["above_ema20"]
    both_below = btc["below_ema20"] and eth["below_ema20"]

    if market_r4 >= 1.0 and market_r24 >= 2.0 and both_above:
        risk_state = "RISK_ON"
    elif market_r4 <= -0.8 and market_r24 <= 0.0 and both_below:
        risk_state = "RISK_OFF"
    else:
        risk_state = "NEUTRAL"

    if both_below and (btc["ema_bear"] or eth["ema_bear"]):
        trend_state = "BEAR"
    elif both_above and market_r24 > 1.0:
        trend_state = "BULL"
    else:
        trend_state = "RANGE"

    if market_atr_pct < 0.8:
        vol_state = "LOW_VOL"
    elif market_atr_pct < 2.0:
        vol_state = "NORMAL_VOL"
    else:
        vol_state = "HIGH_VOL"

    local_atr = float((coin or {}).get("atr_pct") or 0.0)
    if coin is None:
        local_vol_state = "UNKNOWN"
    elif local_atr < 1.0:
        local_vol_state = "LOW_VOL"
    elif local_atr < 3.0:
        local_vol_state = "NORMAL_VOL"
    else:
        local_vol_state = "HIGH_VOL"

    return {
        "risk_state": risk_state,
        "trend_state": trend_state,
        "vol_state": vol_state,
        "local_vol_state": local_vol_state,
        "regime_key": f"{risk_state}|{trend_state}|{vol_state}",
        "market_r4": round(market_r4, 4),
        "market_r24": round(market_r24, 4),
        "market_atr_pct": round(market_atr_pct, 4),
        "coin_atr_pct": round(local_atr, 4),
        "btc": btc,
        "eth": eth,
    }
