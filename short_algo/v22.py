"""Crypto Short V2.2 — reversal-specific scoring and 15m execution.

V2.2 remains research-only. It does not alter the V1 live scanner.
"""

import math

from .config import V22_ENTRY_SCORE
from .indicators import atr, bearish_rejection, ema, return_pct, structure_snapshot, volume_ratio


def _bollinger_state(frame, period=20, width=2.0):
    close = frame["close"].astype(float)
    if len(close) < period + 2:
        return {"z": 0.0, "failed_upper": False, "upper": None, "mean": None}
    mean = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    m = float(mean.iloc[-1])
    s = float(std.iloc[-1])
    if not math.isfinite(s) or s <= 0:
        return {"z": 0.0, "failed_upper": False, "upper": None, "mean": m}
    upper = m + width * s
    last_high = float(frame["high"].iloc[-1])
    current = float(close.iloc[-1])
    return {
        "z": (current - m) / s,
        "failed_upper": bool(last_high > upper and current < upper),
        "upper": upper,
        "mean": m,
    }


def _rolling_vwap(frame, bars=24):
    view = frame.tail(max(5, bars))
    vol = view["volume"].astype(float)
    typical = (
        view["high"].astype(float)
        + view["low"].astype(float)
        + view["close"].astype(float)
    ) / 3.0
    denom = float(vol.sum())
    if denom <= 0:
        return float(view["close"].iloc[-1])
    return float((typical * vol).sum() / denom)


def _trigger_15m(frame):
    if frame is None or len(frame) < 40:
        return {
            "score": 0,
            "confirmed": False,
            "close_below_ema20": False,
            "lower_high": False,
            "lower_low": False,
            "breakdown": False,
            "rejection": False,
        }

    snap = structure_snapshot(frame)
    close = frame["close"].astype(float)
    low = frame["low"].astype(float)

    breakdown = False
    if len(frame) >= 10:
        prior_low = float(low.iloc[-9:-1].min())
        breakdown = float(close.iloc[-1]) < prior_low

    rejection = any(
        bearish_rejection(frame.iloc[i])
        for i in range(max(0, len(frame) - 4), len(frame))
    )
    close_below_ema20 = snap["close"] < snap["ema20"]

    score = 0
    if close_below_ema20:
        score += 5
    if snap["lower_high"]:
        score += 5
    if snap["lower_low"]:
        score += 4
    if breakdown:
        score += 4
    if rejection:
        score += 4
    score = min(20, score)

    return {
        "score": score,
        "confirmed": score >= 9 and (breakdown or snap["lower_high"] or rejection),
        "close_below_ema20": close_below_ema20,
        "lower_high": bool(snap["lower_high"]),
        "lower_low": bool(snap["lower_low"]),
        "breakdown": breakdown,
        "rejection": rejection,
    }


def _btc_regime(btc_one):
    if btc_one is None or len(btc_one) < 30:
        return {
            "risk_on": False,
            "bearish_or_neutral": True,
            "return_4h_pct": 0.0,
            "return_24h_pct": 0.0,
            "score_adjustment": 0,
        }

    close = btc_one["close"].astype(float)
    r4 = return_pct(close, 4)
    r24 = return_pct(close, 24)
    e20 = float(ema(close, 20).iloc[-1])
    current = float(close.iloc[-1])

    risk_on = r4 >= 2.0 and r24 >= 4.0 and current > e20
    bearish_or_neutral = r4 <= 0.5 or current <= e20
    adjustment = -10 if risk_on else (6 if bearish_or_neutral else 0)

    return {
        "risk_on": risk_on,
        "bearish_or_neutral": bearish_or_neutral,
        "return_4h_pct": round(r4, 3),
        "return_24h_pct": round(r24, 3),
        "score_adjustment": adjustment,
    }


def score_v22(result, one_hour, fifteen_minute, btc_one=None):
    """Score a reversal setup on a 0-100 scale and build a 15m trade plan."""
    current = float(one_hour["close"].iloc[-1])
    one_atr = float(atr(one_hour).iloc[-1])
    if not math.isfinite(one_atr) or one_atr <= 0:
        one_atr = max(current * 0.01, 1e-12)

    ret24 = float(result.get("return_24h_pct") or return_pct(one_hour["close"], 24))
    ema20_distance = float(result.get("ema20_distance_atr") or 0.0)
    extension_atr = max(0.0, -ema20_distance)

    bb = _bollinger_state(one_hour)
    vwap = _rolling_vwap(one_hour, 24)
    vwap_extension_atr = max(0.0, (current - vwap) / one_atr)

    sweep = result.get("liquidity_sweep") or {}
    supply_distance = result.get("supply_distance_atr")
    rejection_1h = bool(result.get("bearish_rejection"))
    vol_ratio = volume_ratio(one_hour)
    trigger15 = _trigger_15m(fifteen_minute)
    btc = _btc_regime(btc_one)

    pump_points = 0
    if ret24 >= 15:
        pump_points += 12
    elif ret24 >= 8:
        pump_points += 10
    elif ret24 >= 5:
        pump_points += 8
    elif ret24 > 0:
        pump_points += 4

    if extension_atr >= 3.0:
        pump_points += 8
    elif extension_atr >= 2.0:
        pump_points += 6
    elif extension_atr >= 1.2:
        pump_points += 3

    if bb["z"] >= 2.0:
        pump_points += 4
    if vwap_extension_atr >= 2.0:
        pump_points += 3
    pump_points = min(25, pump_points)

    liquidity_points = 0
    if sweep.get("detected"):
        liquidity_points += 15
        bars_ago = sweep.get("bars_ago")
        if bars_ago is not None and int(bars_ago) <= 2:
            liquidity_points += 4
    if supply_distance is not None:
        d = float(supply_distance)
        if d <= 0.35:
            liquidity_points += 8
        elif d <= 0.75:
            liquidity_points += 6
        elif d <= 1.0:
            liquidity_points += 3
    liquidity_points = min(25, liquidity_points)

    exhaustion_points = 0
    if rejection_1h:
        exhaustion_points += 7
    if bb["failed_upper"]:
        exhaustion_points += 6
    if vol_ratio >= 2.0:
        exhaustion_points += 5
    elif vol_ratio >= 1.4:
        exhaustion_points += 3
    if ret24 >= 5 and (rejection_1h or bb["failed_upper"]):
        exhaustion_points += 2
    exhaustion_points = min(20, exhaustion_points)

    trigger_points = int(trigger15["score"])
    market_points = 5 + int(btc["score_adjustment"])
    market_points = max(-5, min(10, market_points))

    raw_score = pump_points + liquidity_points + exhaustion_points + trigger_points + market_points
    score = max(0.0, min(100.0, float(raw_score)))

    # 15m execution plan. A tighter micro stop is used only for V2.2 research.
    if fifteen_minute is not None and len(fifteen_minute) >= 20:
        entry = float(fifteen_minute["close"].iloc[-1])
        a15 = float(atr(fifteen_minute).iloc[-1])
        if not math.isfinite(a15) or a15 <= 0:
            a15 = max(entry * 0.0025, 1e-12)
        recent_high = float(fifteen_minute["high"].iloc[-16:].max())
        risk = max(recent_high + 0.10 * a15 - entry, 0.9 * a15)
    else:
        entry = float(result.get("entry") or current)
        risk = float(result.get("risk_per_unit") or max(current * 0.01, 1e-12))

    stop = entry + risk
    stop_pct = risk / max(entry, 1e-12) * 100.0
    nearest_support = result.get("nearest_support")
    if nearest_support is not None and float(nearest_support) < entry:
        support_room_r = (entry - float(nearest_support)) / max(risk, 1e-12)
    else:
        support_room_r = 5.0

    risk_ok = stop_pct <= 5.5 and support_room_r >= 1.7
    context_ok = bool(sweep.get("detected")) and ret24 > 0.0
    confirmation_ok = bool(trigger15["confirmed"])
    location_ok = (
        supply_distance is not None and float(supply_distance) <= 1.0
    ) or rejection_1h or bb["failed_upper"]

    entry_ready = bool(
        score >= V22_ENTRY_SCORE
        and context_ok
        and confirmation_ok
        and location_ok
        and risk_ok
        and not btc["risk_on"]
    )
    developing = bool(
        score >= 58
        and context_ok
        and location_ok
        and risk_ok
    )

    status = "ENTRY_READY" if entry_ready else ("DEVELOPING" if developing else "IGNORE")

    return {
        "v22_status": status,
        "v22_score": round(score, 2),
        "v22_priority": "HIGH" if entry_ready and ret24 >= 5.0 else "NORMAL",
        "v22_components": {
            "pump_extension": pump_points,
            "liquidity_location": liquidity_points,
            "exhaustion": exhaustion_points,
            "trigger_15m": trigger_points,
            "market_regime": market_points,
        },
        "v22_features": {
            "extension_atr": round(extension_atr, 3),
            "bollinger_z": round(float(bb["z"]), 3),
            "bollinger_failed_upper": bool(bb["failed_upper"]),
            "vwap_extension_atr": round(vwap_extension_atr, 3),
            "volume_ratio_1h": round(float(vol_ratio), 3),
            "trigger_15m": trigger15,
            "btc_regime": btc,
        },
        "v22_gate": {
            "context_ok": context_ok,
            "confirmation_15m_ok": confirmation_ok,
            "location_ok": location_ok,
            "risk_ok": risk_ok,
            "btc_risk_on_block": bool(btc["risk_on"]),
        },
        "v22_entry": entry,
        "v22_stop": stop,
        "v22_stop_pct": round(stop_pct, 3),
        "v22_tp1": entry - 2.0 * risk,
        "v22_tp2": entry - 3.0 * risk,
        "v22_runner": entry - 5.0 * risk,
        "v22_support_room_r": round(support_room_r, 3),
    }
