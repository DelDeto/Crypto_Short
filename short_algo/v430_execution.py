"""Timestamp-safe execution-policy simulator for V4.3.0.

All decisions consume *closed* 15m candles and enter at the next 15m open.
Support levels are frozen from completed 1h/4h candles at signal time.
A: next open after confirmation; B: pullback + rejection + next open;
C: at most one short re-entry after A stopped and bearish invalidation reclaim.
No future best-price optimisation, no martingale, no widening old stops.
"""
import math
from collections import defaultdict

import pandas as pd

from .v430_config import (
    V430_B_MAX_RISK_MULT, V430_B_MIN_PULLBACK_ATR, V430_B_WAIT_HOURS,
    V430_C_MAX_RISK_MULT, V430_C_WAIT_HOURS, V430_COST_BPS,
    V430_HOLD_HOURS, V430_MAX_STOP_PCT, V430_RECLAIM_BUFFER_ATR,
    V430_RECLAIM_MIN_BODY_ATR, V430_STOP_BUFFER_ATR,
    V430_STRUCTURAL_ROOM_R,
)

STEP = pd.Timedelta(minutes=15)


def _number(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _pivots(frame, bars, left=2, right=2):
    """Pivot is known only after 'right' subsequently CLOSED bars."""
    if frame is None or len(frame) < left + right + 2:
        return []
    view = frame.tail(bars)
    lows = view["low"].astype(float).to_numpy()
    closes = view["close"].astype(float).to_numpy()
    out = []
    for i in range(left, len(lows) - right):
        x = float(lows[i])
        if x <= 0 or not math.isfinite(x):
            continue
        if any(x >= float(lows[j]) for j in range(i - left, i)):
            continue
        if any(x > float(lows[j]) for j in range(i + 1, i + right + 1)):
            continue
        out.append((i, x, closes))
    return out


def classify_support(one_closed, four_closed, features):
    """Three tiers, not an optimistic infinite-room default.

    STRUCTURAL: unbroken confirmed 4h pivot low.
    INTERMEDIATE: two or more separated 1h swing-low reactions.
    MINOR: nearest remaining 1h swing or scanner's nearest support.
    The higher-tier existence/room is explicit even when a nearer minor tier
    exists; minor support never pretends to be a structural hard floor.
    """
    entry = _number(features.get("v428_confirm_entry_reference"))
    risk = _number(features.get("v428_confirm_risk"))
    atr = _number(features.get("atr_1h"))
    result = {
        "v430_support_minor": None,
        "v430_support_intermediate": None,
        "v430_support_structural": None,
        "v430_structural_room_r": None,
        "v430_minor_room_r": None,
        "v430_support_class": "UNKNOWN",
        "v430_support_pass": 0,
        "v430_1h_pivot_count": 0,
        "v430_4h_pivot_count": 0,
    }
    if entry is None or risk is None or risk <= 0 or atr is None or atr <= 0:
        return result

    p4 = _pivots(four_closed, 90)
    p1 = _pivots(one_closed, 160)
    structural = []
    for i, price, closes in p4:
        if price >= entry:
            continue
        # A structurally broken pivot is resistance, not presumed support.
        later = closes[i + 3 :]
        if len(later) and bool((later < price - 0.20 * atr).any()):
            continue
        structural.append(price)
    result["v430_4h_pivot_count"] = len(structural)

    pivot_minor = [p for _, p, _ in p1 if p < entry]
    minor = list(pivot_minor)
    result["v430_1h_pivot_count"] = len(pivot_minor)
    reference_distance = _number(features.get("support_distance_atr"))
    if reference_distance is not None and reference_distance > 0:
        x = entry - reference_distance * atr
        if x > 0 and x < entry:
            minor.append(x)

    intermediate = []
    # Scanner support may be the *same* pivot; never count it as an
    # independent second reaction when classifying INTERMEDIATE support.
    sorted_low = sorted(pivot_minor)
    clusters = []
    # 0.35 ATR clusters with multiple separated pivot lows.
    for p in sorted_low:
        if clusters and abs(p - clusters[-1][-1]) <= 0.35 * atr:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    for group in clusters:
        if len(group) >= 2:
            intermediate.append(sum(group) / len(group))

    if minor:
        result["v430_support_minor"] = round(max(minor), 8)
        result["v430_minor_room_r"] = round((entry - max(minor)) / risk, 4)
        result["v430_support_class"] = "MINOR"
    if intermediate:
        result["v430_support_intermediate"] = round(max(intermediate), 8)
        result["v430_support_class"] = "INTERMEDIATE"
    if structural:
        nearest = max(structural)
        result["v430_support_structural"] = round(nearest, 8)
        result["v430_structural_room_r"] = round((entry - nearest) / risk, 4)
        result["v430_support_class"] = "STRUCTURAL"
        result["v430_support_pass"] = int(
            (entry - nearest) / risk >= float(V430_STRUCTURAL_ROOM_R)
        )
    return result


def _empty(reason, mode):
    return {
        f"v430_{mode}_state": reason,
        f"v430_{mode}_entry_time": None,
        f"v430_{mode}_entry": None,
        f"v430_{mode}_stop": None,
        f"v430_{mode}_tp2": None,
        f"v430_{mode}_risk_pct": None,
        f"v430_{mode}_gross_r": None,
        f"v430_{mode}_cost_r": None,
        f"v430_{mode}_net_r": None,
        f"v430_{mode}_hold_bars": None,
        f"v430_{mode}_exit_time": None,
        f"v430_{mode}_exit_bar_index": None,
        f"v430_{mode}_wait_bars": None,
    }


def _can_fill(entry, stop):
    if not all(math.isfinite(x) for x in (entry, stop)):
        return False
    if entry <= 0 or stop <= entry:
        return False
    return 100.0 * (stop - entry) / entry <= float(V430_MAX_STOP_PCT)


def _simulate_exit(future15, start_idx, entry, stop, mode, wait_bars=0):
    out = _empty("INVALID_PLAN", mode)
    if not _can_fill(entry, stop):
        return out
    if start_idx >= len(future15):
        out[f"v430_{mode}_state"] = "NO_NEXT_OPEN"
        return out

    entry_time = future15.index[start_idx]
    risk = stop - entry
    tp = entry - 2.0 * risk
    if tp <= 0:
        return out
    if float(future15.iloc[start_idx]["open"]) >= stop:
        out[f"v430_{mode}_state"] = "GAP_BEYOND_STOP"
        return out

    out.update({
        f"v430_{mode}_entry_time": entry_time.isoformat(),
        f"v430_{mode}_entry": round(entry, 10),
        f"v430_{mode}_stop": round(stop, 10),
        f"v430_{mode}_tp2": round(tp, 10),
        f"v430_{mode}_risk_pct": round(100.0 * risk / entry, 4),
        f"v430_{mode}_wait_bars": int(wait_bars),
    })
    cost_r = float(V430_COST_BPS) / 10000.0 * entry / risk
    end_time = entry_time + pd.Timedelta(hours=int(V430_HOLD_HOURS))
    expected = entry_time
    last_close = None
    bar_count = 0

    for i in range(start_idx, len(future15)):
        t = future15.index[i]
        if t >= end_time:
            break
        if t != expected:
            out[f"v430_{mode}_state"] = "CENSORED_15M_GAP"
            return out
        bar = future15.iloc[i]
        o = float(bar["open"])
        h = float(bar["high"])
        l = float(bar["low"])
        c = float(bar["close"])
        if not all(math.isfinite(x) for x in (o, h, l, c)):
            out[f"v430_{mode}_state"] = "CENSORED_BAD_BAR"
            return out
        expected += STEP
        bar_count += 1
        last_close = c

        hit_sl = h >= stop
        hit_tp = l <= tp
        if hit_sl:  # stop wins same-bar collision, open gap is worse.
            exit_price = max(o, stop)
            gross = (entry - exit_price) / risk
            state = "SL_SAME_BAR" if hit_tp else "SL_FIRST"
        elif hit_tp:
            gross = 2.0  # do not take optimistic price improvement
            state = "TP2R_FIRST"
        else:
            continue

        out.update({
            f"v430_{mode}_state": state,
            f"v430_{mode}_gross_r": round(gross, 5),
            f"v430_{mode}_cost_r": round(cost_r, 5),
            f"v430_{mode}_net_r": round(gross - cost_r, 5),
            f"v430_{mode}_hold_bars": bar_count,
            f"v430_{mode}_exit_time": (t + STEP).isoformat(),
            f"v430_{mode}_exit_bar_index": i,
        })
        return out

    if expected < end_time or last_close is None:
        out[f"v430_{mode}_state"] = "CENSORED_INCOMPLETE_HORIZON"
        return out

    gross = (entry - last_close) / risk
    out.update({
        f"v430_{mode}_state": "TIME_EXIT",
        f"v430_{mode}_gross_r": round(gross, 5),
        f"v430_{mode}_cost_r": round(cost_r, 5),
        f"v430_{mode}_net_r": round(gross - cost_r, 5),
        f"v430_{mode}_hold_bars": bar_count,
        f"v430_{mode}_exit_time": end_time.isoformat(),
        f"v430_{mode}_exit_bar_index": start_idx + bar_count - 1,
    })
    return out


def _next_bar(future15, i):
    return (
        i + 1 < len(future15)
        and future15.index[i + 1] == future15.index[i] + STEP
    )


def _bearish_rejection15(bar, previous_close, level=None):
    o, h, l, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
    if not (c < o and c < previous_close and h > l):
        return False
    if c > l + 0.50 * (h - l):
        return False
    if level is not None and c >= level:
        return False
    return True


def _simulate_b(features, future15, a_result):
    out = _empty("NO_PULLBACK_CONFIRMATION", "B")
    atr = float(features["atr_1h"])
    original_entry = _number(features.get("v428_confirm_entry_reference"))
    original_stop = _number(features.get("v428_confirm_stop_reference"))
    zone_upper = _number(features.get("preferred_zone_upper"))
    zone_lower = _number(features.get("preferred_zone_lower"))
    if any(x is None for x in (original_entry, original_stop, zone_upper, zone_lower)):
        return _empty("INVALID_PLAN", "B")

    old_risk = original_stop - original_entry
    if old_risk <= 0:
        return _empty("INVALID_PLAN", "B")

    # Micro-supply is the signal-time zone midpoint, not the best future high.
    midpoint = (zone_lower + zone_upper) / 2.0
    target = max(original_entry + float(V430_B_MIN_PULLBACK_ATR) * atr, midpoint)
    out["v430_B_pullback_level"] = round(target, 10)
    deadline = future15.index[0] + pd.Timedelta(hours=int(V430_B_WAIT_HOURS))
    highs = []
    for i in range(1, len(future15) - 1):
        t = future15.index[i]
        if t >= deadline:
            break
        previous = future15.iloc[i - 1]
        bar = future15.iloc[i]
        highs.append(float(bar["high"]))
        # B is an unfilled plan: cancel if the original zone is reclaimed or
        # the first 2R move already happened before the proposed pullback.
        if float(bar["close"]) > zone_upper + 0.12 * atr:
            out["v430_B_state"] = "CANCEL_ZONE_RECLAIMED"
            break
        if float(bar["low"]) <= original_entry - 2.0 * old_risk:
            out["v430_B_state"] = "CANCEL_SETUP_ALREADY_COMPLETED"
            break
        if not _next_bar(future15, i):
            continue
        touched = float(bar["high"]) >= target and float(bar["low"]) <= zone_upper + 0.12 * atr
        if not touched or not _bearish_rejection15(bar, float(previous["close"]), target):
            continue

        entry = float(future15.iloc[i + 1]["open"])
        if entry < original_entry - 0.15 * atr:
            out["v430_B_state"] = "SKIP_CHASE_AFTER_REJECTION"
            continue
        stop = max(zone_upper, max(highs)) + float(V430_STOP_BUFFER_ATR) * atr
        if stop - entry > float(V430_B_MAX_RISK_MULT) * old_risk:
            out["v430_B_state"] = "SKIP_STOP_TOO_WIDE"
            continue
        return {
            **_simulate_exit(future15, i + 1, entry, stop, "B", i + 1),
            "v430_B_pullback_level": round(target, 10),
        }
    return out


def _simulate_c(features, future15, a_result):
    state = a_result.get("v430_A_state")
    if state not in ("SL_FIRST", "SL_SAME_BAR"):
        return _empty("A_NOT_STOPPED", "C")
    stop_idx = a_result.get("v430_A_exit_bar_index")
    if stop_idx is None:
        return _empty("NO_A_STOP_INDEX", "C")

    atr = float(features["atr_1h"])
    old_stop = _number(a_result.get("v430_A_stop"))
    old_entry = _number(a_result.get("v430_A_entry"))
    if old_stop is None or old_entry is None:
        return _empty("INVALID_PLAN", "C")
    old_risk = old_stop - old_entry
    if old_risk <= 0:
        return _empty("INVALID_PLAN", "C")

    invalidation = old_stop - float(V430_RECLAIM_BUFFER_ATR) * atr
    deadline = future15.index[int(stop_idx)] + pd.Timedelta(hours=int(V430_C_WAIT_HOURS))
    out = _empty("NO_RECLAIM_CONFIRMATION", "C")
    out["v430_C_reclaim_level"] = round(invalidation, 10)

    # Only bars *after* the realized stop can produce a re-entry.
    highs = [float(future15.iloc[int(stop_idx)]["high"])]
    for i in range(int(stop_idx) + 1, len(future15) - 1):
        t = future15.index[i]
        if t >= deadline:
            break
        bar = future15.iloc[i]
        prev = future15.iloc[i - 1]
        highs.append(float(bar["high"]))
        if not _next_bar(future15, i):
            continue
        if not (
            float(prev["close"]) >= invalidation
            and float(bar["close"]) < invalidation
        ):
            continue
        if float(bar["open"]) - float(bar["close"]) < float(V430_RECLAIM_MIN_BODY_ATR) * atr:
            continue
        if not _bearish_rejection15(bar, float(prev["close"]), invalidation):
            continue

        entry = float(future15.iloc[i + 1]["open"])
        if entry < old_entry - 0.20 * atr:
            out["v430_C_state"] = "SKIP_REENTRY_CHASE"
            continue
        stop = max(old_stop, max(highs)) + float(V430_STOP_BUFFER_ATR) * atr
        if stop - entry > float(V430_C_MAX_RISK_MULT) * old_risk:
            out["v430_C_state"] = "SKIP_REENTRY_STOP_TOO_WIDE"
            continue
        return {
            **_simulate_exit(future15, i + 1, entry, stop, "C", i - int(stop_idx)),
            "v430_C_reclaim_level": round(invalidation, 10),
        }
    return out


def evaluate_execution_policies(features, future15):
    """Independent A vs B, and optional sequential A+C, on the same setup."""
    result = {
        "v430_AplusC_net_r": None,
        "v430_AplusC_trades": 0,
        "v430_AplusC_state": "NO_CONFIRMATION",
    }
    if int(features.get("v428_entry_confirmed") or 0) != 1:
        result.update(_empty("NO_CONFIRMATION", "A"))
        result.update(_empty("NO_CONFIRMATION", "B"))
        result.update(_empty("NO_CONFIRMATION", "C"))
        return result

    if future15 is None or len(future15) < 4:
        result.update(_empty("NO_FUTURE_15M", "A"))
        result.update(_empty("NO_FUTURE_15M", "B"))
        result.update(_empty("NO_FUTURE_15M", "C"))
        return result

    future15 = future15.sort_index()
    entry = _number(future15.iloc[0]["open"])
    stop = _number(features.get("v428_confirm_stop_reference"))
    if entry is None or stop is None:
        a = _empty("INVALID_PLAN", "A")
    else:
        a = _simulate_exit(future15, 0, entry, stop, "A")
    b = _simulate_b(features, future15, a)
    c = _simulate_c(features, future15, a)
    result.update(a)
    result.update(b)
    result.update(c)

    a_net = _number(a.get("v430_A_net_r"))
    c_net = _number(c.get("v430_C_net_r"))
    if a_net is not None:
        result["v430_AplusC_net_r"] = round(a_net + (c_net or 0.0), 5)
        result["v430_AplusC_trades"] = 1 + int(c_net is not None)
        result["v430_AplusC_state"] = (
            "A_WITH_C_REENTRY" if c_net is not None else "A_ONLY"
        )
    return result
