"""V4.1 zone-based Short entry engine.

The rule engines identify *what* may be shortable. This module decides *where*
and *when* to enter. It never uses future bars to construct the zone; future
15m bars are used only to simulate the subsequent retest/confirmation.
"""

import math

import pandas as pd

from .indicators import atr, ema
from .v41_config import (
    V41_CONFIRM_MIN_SCORE,
    V41_ENTRY_WAIT_HOURS,
    V41_MAX_CHASE_ATR,
    V41_MAX_STOP_PCT,
    V41_MIN_SUPPORT_ROOM_R,
    V41_STOP_BUFFER_ATR,
    V41_ZONE_BUFFER_ATR,
)


def _zone(lower, upper, source, priority):
    lower, upper = sorted((float(lower), float(upper)))
    return {
        "lower": lower,
        "upper": upper,
        "mid": (lower + upper) / 2.0,
        "source": source,
        "priority": int(priority),
    }


def build_short_entry_zone(candidate, base, one):
    """Build an engine-aware zone using only information at signal time."""
    if one is None or len(one) < 30:
        return None

    current = float(one["close"].iloc[-1])
    a1 = float(atr(one).iloc[-1])
    if not math.isfinite(a1) or a1 <= 0:
        return None

    engine = str(candidate.get("v3_engine") or "")
    zones = []

    supply1 = base.get("supply_1h") or {}
    supply4 = base.get("supply_4h") or {}
    breakdown = base.get("breakdown_retest") or {}
    sweep = base.get("liquidity_sweep") or {}

    if supply1.get("lower") is not None and supply1.get("upper") is not None:
        zones.append(_zone(
            supply1["lower"], supply1["upper"], "SUPPLY_1H",
            1 if engine in ("FAILED_BREAKOUT_SUPPLY_FADE", "EXHAUSTION_REVERSAL") else 3,
        ))
    if supply4.get("lower") is not None and supply4.get("upper") is not None:
        zones.append(_zone(
            supply4["lower"], supply4["upper"], "SUPPLY_4H",
            2,
        ))

    level = breakdown.get("level")
    if level is not None:
        zones.append(_zone(
            float(level) - 0.10 * a1,
            float(level) + V41_ZONE_BUFFER_ATR * a1,
            "BREAKDOWN_RETEST",
            1 if engine == "BREAKDOWN_RETEST" else 4,
        ))

    sweep_level = sweep.get("level")
    if sweep_level is not None:
        zones.append(_zone(
            float(sweep_level) - 0.08 * a1,
            float(sweep_level) + 0.30 * a1,
            "SWEEP_RETEST",
            1 if engine in ("EXTREME_PUMP_REVERSAL", "FAILED_BREAKOUT_SUPPLY_FADE") else 4,
        ))

    e20 = float(ema(one["close"].astype(float), 20).iloc[-1])
    zones.append(_zone(
        e20 - 0.08 * a1,
        e20 + 0.18 * a1,
        "EMA20_PULLBACK",
        2 if engine in ("RELATIVE_WEAKNESS", "BREAKDOWN_RETEST") else 5,
    ))

    # Short entries should be at/above current price or only slightly below it.
    # A zone far below the signal is a chase location, not a better entry.
    usable = [
        z for z in zones
        if z["upper"] >= current - V41_MAX_CHASE_ATR * a1
    ]
    if not usable:
        return None

    for z in usable:
        if z["lower"] <= current <= z["upper"]:
            distance = 0.0
        elif current < z["lower"]:
            distance = (z["lower"] - current) / a1
        else:
            distance = (current - z["upper"]) / a1
        z["distance_atr"] = float(distance)

    usable.sort(key=lambda z: (z["priority"], z["distance_atr"]))
    chosen = dict(usable[0])
    chosen["signal_price"] = current
    chosen["atr_1h"] = a1
    chosen["ideal_entry"] = (
        chosen["lower"] * 0.35 + chosen["upper"] * 0.65
    )
    return chosen


def _confirmation_score(row, prev, zone):
    o = float(row["open"])
    h = float(row["high"])
    l = float(row["low"])
    c = float(row["close"])
    candle_range = max(h - l, 1e-12)
    upper_wick = h - max(o, c)

    score = 0
    if c < o:
        score += 1
    if c < zone["mid"]:
        score += 1
    if upper_wick / candle_range >= 0.35:
        score += 1
    if prev is not None and c < float(prev["close"]):
        score += 1
    return score


def simulate_confirmed_retest(zone, fifteen_future, nearest_support=None):
    """Wait for a retest and bearish confirmation, then return an entry plan."""
    if zone is None or fifteen_future is None or fifteen_future.empty:
        return None

    a1 = float(zone["atr_1h"])
    signal_price = float(zone["signal_price"])
    max_bars = max(1, int(V41_ENTRY_WAIT_HOURS) * 4)
    view = fifteen_future.head(max_bars)

    prev = None
    touched_at = None
    for bars, (ts, row) in enumerate(view.iterrows(), start=1):
        high = float(row["high"])
        low = float(row["low"])
        touched = high >= zone["lower"] and low <= zone["upper"]
        if touched and touched_at is None:
            touched_at = ts

        if touched_at is not None:
            score = _confirmation_score(row, prev, zone)
            close = float(row["close"])
            if (
                score >= V41_CONFIRM_MIN_SCORE
                and close <= zone["upper"]
                and close >= signal_price - V41_MAX_CHASE_ATR * a1
            ):
                entry = close
                recent_high = max(
                    float(zone["upper"]),
                    float(row["high"]),
                )
                risk = recent_high + V41_STOP_BUFFER_ATR * a1 - entry
                if risk <= 0:
                    prev = row
                    continue

                stop = entry + risk
                stop_pct = risk / max(entry, 1e-12) * 100.0
                support_room_r = (
                    (entry - float(nearest_support)) / risk
                    if nearest_support is not None and float(nearest_support) < entry
                    else 5.0
                )
                if (
                    stop_pct > V41_MAX_STOP_PCT
                    or support_room_r < V41_MIN_SUPPORT_ROOM_R
                ):
                    prev = row
                    continue

                return {
                    "entry_time": (pd.Timestamp(ts) + pd.Timedelta(minutes=15)).isoformat(),
                    "entry_bar": bars,
                    "entry": entry,
                    "stop": stop,
                    "risk": risk,
                    "stop_pct": round(stop_pct, 4),
                    "tp1": entry - 2.0 * risk,
                    "tp2": entry - 3.0 * risk,
                    "runner": entry - 5.0 * risk,
                    "support_room_r": round(support_room_r, 4),
                    "zone_source": zone["source"],
                    "zone_lower": zone["lower"],
                    "zone_upper": zone["upper"],
                    "zone_mid": zone["mid"],
                    "ideal_entry": zone["ideal_entry"],
                    "signal_price": signal_price,
                    "entry_improvement_atr": round(
                        (entry - signal_price) / max(a1, 1e-12), 4
                    ),
                    "confirmation_score": score,
                    "wait_bars_15m": bars,
                }

        prev = row

    return None
