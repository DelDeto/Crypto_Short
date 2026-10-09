"""M3 V3.2 live candidate engine.

Goal: produce more short-side opportunities than M2 while preserving a strict,
causal pattern:
4H bearish regime -> 1H bearish impulse -> pullback into resistance ->
failed reclaim/rejection -> optional 15m bearish confirmation.

This module emits research/live-observation candidates only. It never places
orders and does not record whether the user traded a signal.
"""
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .mexc import get_closed_klines

MODEL = "M3_V3.2"
MAX_SIGNAL_AGE_MIN = int(os.getenv("M3_LIVE_MAX_SIGNAL_AGE_MIN", "90"))
MAX_HOLD_HOURS = 24
COOLDOWN_HOURS = int(os.getenv("M3_SIGNAL_COOLDOWN_HOURS", "12"))

ATR_LEN = 14
EMA_FAST = 20
EMA_SLOW = 50
IMPULSE_LOOKBACK = 12
MIN_IMPULSE_ATR = float(os.getenv("M3_MIN_IMPULSE_ATR", "1.20"))
MAX_CHASE_ATR = float(os.getenv("M3_MAX_CHASE_ATR", "2.50"))
MAX_RETRACE = float(os.getenv("M3_MAX_RETRACE", "0.75"))
MIN_RETRACE = float(os.getenv("M3_MIN_RETRACE", "0.15"))
ZONE_TOL_ATR = float(os.getenv("M3_ZONE_TOL_ATR", "0.35"))
STOP_BUFFER_ATR = float(os.getenv("M3_STOP_BUFFER_ATR", "0.20"))
TP1_ATR = float(os.getenv("M3_TP1_ATR", "1.0"))
TP2_ATR = float(os.getenv("M3_TP2_ATR", "2.0"))


def _as_utc(value):
    t = pd.Timestamp(value)
    if t.tzinfo is None:
        return t.tz_localize("UTC")
    return t.tz_convert("UTC")


def _ema(series, span):
    return series.ewm(span=span, adjust=False).mean()


def _atr(frame, length=ATR_LEN):
    prev_close = frame["close"].shift(1)
    tr = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - prev_close).abs(),
            (frame["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / length, adjust=False).mean()


def _prepare(frame):
    out = frame.copy().sort_index()
    out["ema20"] = _ema(out["close"], EMA_FAST)
    out["ema50"] = _ema(out["close"], EMA_SLOW)
    out["atr"] = _atr(out)
    return out


def _four_hour_regime(four):
    if four is None or len(four) < 60:
        return None
    f = _prepare(four)
    last = f.iloc[-1]
    prev = f.iloc[-2]

    below_ema20 = float(last["close"]) < float(last["ema20"])
    ema_stack = float(last["ema20"]) < float(last["ema50"])
    ema20_down = float(last["ema20"]) < float(prev["ema20"])

    recent = f.iloc[-8:]
    older = f.iloc[-16:-8]
    lower_high = bool(len(older) >= 4 and recent["high"].max() < older["high"].max())
    lower_low = bool(len(older) >= 4 and recent["low"].min() < older["low"].min())
    structure_bear = lower_high and lower_low

    votes = int(below_ema20) + int(ema_stack or ema20_down) + int(structure_bear)
    return {
        "bear_votes": votes,
        "below_ema20": below_ema20,
        "ema_bear": bool(ema_stack or ema20_down),
        "structure_bear": structure_bear,
        "close": float(last["close"]),
        "ema20": float(last["ema20"]),
        "ema50": float(last["ema50"]),
    }


def _find_impulse_and_pullback(one):
    if one is None or len(one) < 70:
        return None
    f = _prepare(one)
    atr_now = float(f["atr"].iloc[-1])
    if not np.isfinite(atr_now) or atr_now <= 0:
        return None

    # Search only completed 1H bars. Breakdown must precede the current
    # rejection bar by at least one full hour.
    end = len(f) - 1
    start = max(12, end - IMPULSE_LOOKBACK)
    best = None

    for i in range(start, end):
        if i < 8:
            continue
        prior_low = float(f["low"].iloc[i - 6:i].min())
        bar = f.iloc[i]
        body_move_atr = max(0.0, (float(bar["open"]) - float(bar["close"])) / atr_now)
        broke_low = float(bar["close"]) < prior_low
        below_ema = float(bar["close"]) < float(bar["ema20"])
        if not below_ema or not (broke_low or body_move_atr >= 0.60):
            continue

        impulse_start_high = float(f["high"].iloc[max(0, i - 4): i + 1].max())
        impulse_low = float(f["low"].iloc[i: min(end + 1, i + 3)].min())
        impulse_atr = (impulse_start_high - impulse_low) / atr_now
        if impulse_atr < MIN_IMPULSE_ATR:
            continue

        after = f.iloc[i + 1: end + 1]
        if after.empty:
            continue
        pullback_high = float(after["high"].max())
        pullback_idx = after["high"].idxmax()

        denom = max(impulse_start_high - impulse_low, 1e-12)
        retrace = (pullback_high - impulse_low) / denom
        if retrace < MIN_RETRACE or retrace > MAX_RETRACE:
            continue

        broken_support = prior_low
        ema20_at_pullback = float(f.loc[pullback_idx, "ema20"])
        resistance = min(
            max(broken_support, impulse_low),
            impulse_start_high,
        )
        # Candidate resistance can be either the broken support or EMA20.
        dist_support = abs(pullback_high - broken_support) / atr_now
        dist_ema = abs(pullback_high - ema20_at_pullback) / atr_now
        zone_type = None
        zone_level = None
        zone_distance_atr = None
        if dist_support <= ZONE_TOL_ATR:
            zone_type = "BROKEN_SUPPORT"
            zone_level = broken_support
            zone_distance_atr = dist_support
        if dist_ema <= ZONE_TOL_ATR and (zone_distance_atr is None or dist_ema < zone_distance_atr):
            zone_type = "EMA20_1H"
            zone_level = ema20_at_pullback
            zone_distance_atr = dist_ema
        if zone_type is None:
            continue

        last = f.iloc[-1]
        prev = f.iloc[-2]
        failed_reclaim = bool(
            float(last["high"]) >= float(zone_level) - ZONE_TOL_ATR * atr_now
            and float(last["close"]) < float(zone_level)
        )
        bearish_rejection = bool(
            float(last["close"]) < float(last["open"])
            and float(last["close"]) < float(prev["close"])
        )
        lower_high = bool(float(last["high"]) < pullback_high + 1e-12)
        if not (failed_reclaim and (bearish_rejection or lower_high)):
            continue

        chase_atr = max(0.0, (float(last["ema20"]) - float(last["close"])) / atr_now)
        if chase_atr > MAX_CHASE_ATR:
            continue

        score = (
            impulse_atr * 2.0
            + (1.0 - retrace) * 2.0
            + (1.0 if failed_reclaim else 0.0)
            + (0.5 if bearish_rejection else 0.0)
            - zone_distance_atr
            - max(0.0, chase_atr - 1.5)
        )
        row = {
            "frame": f,
            "break_idx": i,
            "break_time": f.index[i],
            "prior_low": broken_support,
            "impulse_start_high": impulse_start_high,
            "impulse_low": impulse_low,
            "impulse_atr": float(impulse_atr),
            "pullback_high": pullback_high,
            "pullback_time": pullback_idx,
            "retrace": float(retrace),
            "zone_type": zone_type,
            "zone_level": float(zone_level),
            "zone_distance_atr": float(zone_distance_atr),
            "failed_reclaim": failed_reclaim,
            "bearish_rejection": bearish_rejection,
            "lower_high": lower_high,
            "atr": atr_now,
            "chase_atr": float(chase_atr),
            "score": float(score),
        }
        if best is None or row["score"] > best["score"]:
            best = row

    return best


def _fifteen_confirmation(symbol, one_pattern):
    try:
        fifteen = get_closed_klines(symbol, "15m", 120, 60)
    except Exception:
        return None

    f = _prepare(fifteen)
    last = f.iloc[-1]
    prev6 = f.iloc[-7:-1]
    if prev6.empty:
        return None

    broke_local_low = float(last["close"]) < float(prev6["low"].min())
    below_ema20 = float(last["close"]) < float(last["ema20"])
    bearish_bar = float(last["close"]) < float(last["open"])
    confirm = bool(below_ema20 and (broke_local_low or bearish_bar))

    return {
        "confirmed": confirm,
        "time": f.index[-1] + pd.Timedelta(minutes=15),
        "close": float(last["close"]),
        "broke_local_low": broke_local_low,
        "below_ema20": below_ema20,
        "bearish_bar": bearish_bar,
    }


def _market_state(btc_one, eth_one):
    if btc_one is None or eth_one is None or len(btc_one) < 25 or len(eth_one) < 25:
        return {"state": "UNKNOWN", "risk_on": False, "risk_off": False}

    def one_state(frame):
        f = _prepare(frame)
        last = f.iloc[-1]
        r4 = (float(last["close"]) / float(f["close"].iloc[-5]) - 1.0) * 100.0
        r24 = (float(last["close"]) / float(f["close"].iloc[-25]) - 1.0) * 100.0
        return {
            "r4": r4,
            "r24": r24,
            "above": float(last["close"]) > float(last["ema20"]),
            "below": float(last["close"]) < float(last["ema20"]),
        }

    b = one_state(btc_one)
    e = one_state(eth_one)
    risk_on = bool(b["above"] and e["above"] and (b["r4"] + e["r4"]) / 2.0 >= 0.8)
    risk_off = bool(b["below"] and e["below"] and (b["r4"] + e["r4"]) / 2.0 <= -0.8)
    state = "RISK_ON" if risk_on else ("RISK_OFF" if risk_off else "NEUTRAL")
    return {
        "state": state,
        "risk_on": risk_on,
        "risk_off": risk_off,
        "market_r4_pct": round((b["r4"] + e["r4"]) / 2.0, 3),
        "market_r24_pct": round((b["r24"] + e["r24"]) / 2.0, 3),
    }


def _tier(regime, pattern, confirm, market):
    # Strong risk-on does not completely suppress M3; it caps quality because
    # V3.2 is intended to keep frequency higher than M2.
    votes = int(regime["bear_votes"])
    confirmed = bool(confirm and confirm.get("confirmed"))

    if votes >= 3 and confirmed and not market.get("risk_on"):
        return "A"
    if votes >= 2 and confirmed:
        return "B"
    return "C"


def evaluate_live_symbol(symbol, frames, btc_one=None, eth_one=None, now=None):
    one = (frames or {}).get("1H")
    four = (frames or {}).get("4H")
    if one is None or four is None or one.empty or four.empty:
        return []

    regime = _four_hour_regime(four)
    if regime is None or regime["bear_votes"] < 2:
        return []

    pattern = _find_impulse_and_pullback(one)
    if pattern is None:
        return []

    confirm = _fifteen_confirmation(symbol, pattern)
    market = _market_state(btc_one, eth_one)
    tier = _tier(regime, pattern, confirm, market)

    # C is a developing watch candidate; A/B are confirmed trade candidates.
    signal_time = (
        confirm["time"] if confirm is not None else one.index[-1] + pd.Timedelta(hours=1)
    )
    now_ts = _as_utc(now or datetime.now(timezone.utc))
    age_min = (now_ts - _as_utc(signal_time)).total_seconds() / 60.0
    if age_min < -5 or age_min > MAX_SIGNAL_AGE_MIN:
        return []

    entry = float(confirm["close"] if confirm and confirm.get("confirmed") else one["close"].iloc[-1])
    atr = float(pattern["atr"])
    stop = float(pattern["pullback_high"] + STOP_BUFFER_ATR * atr)
    if stop <= entry:
        return []

    target1 = entry - TP1_ATR * atr
    target2 = entry - TP2_ATR * atr
    risk = stop - entry
    signal_id = f"{MODEL}|{symbol}|{_as_utc(signal_time).isoformat()}"

    return [{
        "signal_id": signal_id,
        "symbol": symbol,
        "model": MODEL,
        "tier": tier,
        "status": "CONFIRMED" if tier in ("A", "B") else "DEVELOPING",
        "signal_time": _as_utc(signal_time).isoformat(),
        "signal_age_minutes": round(age_min, 1),
        "max_hold_hours": MAX_HOLD_HOURS,
        "cooldown_hours": COOLDOWN_HOURS,
        "entry_reference": round(entry, 10),
        "entry_zone_low": round(entry - 0.10 * atr, 10),
        "entry_zone_high": round(entry + 0.10 * atr, 10),
        "invalidation": round(stop, 10),
        "tp1": round(target1, 10),
        "tp2": round(target2, 10),
        "risk_price": round(risk, 10),
        "atr_1h": round(atr, 10),
        "tp1_atr": TP1_ATR,
        "tp2_atr": TP2_ATR,
        "four_hour_bear_votes": regime["bear_votes"],
        "four_hour_below_ema20": regime["below_ema20"],
        "four_hour_ema_bear": regime["ema_bear"],
        "four_hour_structure_bear": regime["structure_bear"],
        "impulse_atr": round(pattern["impulse_atr"], 4),
        "retrace_pct": round(pattern["retrace"] * 100.0, 2),
        "pullback_zone": pattern["zone_type"],
        "pullback_zone_level": round(pattern["zone_level"], 10),
        "pullback_zone_distance_atr": round(pattern["zone_distance_atr"], 4),
        "failed_reclaim": pattern["failed_reclaim"],
        "bearish_rejection": pattern["bearish_rejection"],
        "lower_high": pattern["lower_high"],
        "chase_distance_atr": round(pattern["chase_atr"], 4),
        "confirm_15m": bool(confirm and confirm.get("confirmed")),
        "confirm_15m_break_low": bool(confirm and confirm.get("broke_local_low")),
        "market_state": market.get("state"),
        "market_r4_pct": market.get("market_r4_pct"),
        "market_r24_pct": market.get("market_r24_pct"),
        "break_time": _as_utc(pattern["break_time"]).isoformat(),
        "pullback_time": _as_utc(pattern["pullback_time"]).isoformat(),
        "note": "Manual entry/exit. Prices are research reference levels, not orders.",
    }]
