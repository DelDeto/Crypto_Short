"""V4.4.7 Persistent Broken Support Watch execution.

State machine:
  BREAK_DETECTED
    -> BREAK_CONFIRMED (4H close below structural support)
    -> RECLAIM_WATCH (up to 7 days)
       -> RECLAIMED -> cancel
       -> FAILED_RECLAIM -> SHORT_READY
       -> PERSISTENT_NO_RECLAIM + LOWER_HIGH -> SHORT_READY
    -> 1H bearish confirmation
    -> next 15m open SHORT

The event remains alive until reclaim, short-ready, or expiry. No fixed "enter
N hours after break" rule is used.
"""
import math

import pandas as pd

from .v441_execution import (
    _empty,
    _next_demand_below,
    _num,
    _simulate_staged,
    _structural_support,
)
from .v445_execution import _plan_reason
from .v447_config import (
    V447_BREAK_BUFFER_ATR,\n    V447_BREAK_DETECT_HOURS,
    V447_ENTRY_CONFIRM_HOURS,
    V447_HARD_RECLAIM_ATR if False else V447_RECLAIM_BUFFER_ATR,
    V447_LOWER_HIGH_BUFFER_ATR,
    V447_LOWER_HIGH_LOOKBACK_4H,
    V447_MAX_COST_R,
    V447_MAX_ENTRY_BELOW_SUPPORT_ATR,
    V447_MAX_RISK_ATR,
    V447_MAX_STOP_PCT,
    V447_MIN_REJECTION_WICK_RATIO,
    V447_MIN_RISK_ATR,
    V447_MIN_ROOM_R,
    V447_PERSIST_MIN_4H_BARS,
    V447_PERSIST_MIN_CLOSES_BELOW,
    V447_PERSIST_WINDOW_4H,
    V447_RECLAIM_BUFFER_ATR,
    V447_RECLAIM_CONFIRM_4H,
    V447_RETEST_TOUCH_ATR,
    V447_STOP_BUFFER_ATR,
    V447_TP1_R,
    V447_WATCH_DAYS,
)


def _closed(frame, close_time, hours):
    if frame is None or frame.empty:
        return frame
    return frame.loc[
        (frame.index + pd.Timedelta(hours=int(hours))) <= close_time
    ]


def _future_closed(frame, signal_time, hours):
    if frame is None or frame.empty:
        return frame
    closes = frame.index + pd.Timedelta(hours=int(hours))
    return frame.loc[closes > signal_time].sort_index()


def _bar_values(bar):
    vals = tuple(float(bar[k]) for k in ("open", "high", "low", "close"))
    return vals if all(math.isfinite(x) for x in vals) else None


def _lower_high_confirmed(records, atr):
    lookback = int(V447_LOWER_HIGH_LOOKBACK_4H)
    if len(records) < max(4, lookback):
        return False
    view = records[-lookback:]
    half = max(2, len(view) // 2)
    prior = view[:half]
    recent = view[half:]
    if not prior or not recent:
        return False
    prior_high = max(float(x["high"]) for x in prior)
    recent_high = max(float(x["high"]) for x in recent)
    return bool(
        recent_high
        <= prior_high - float(V447_LOWER_HIGH_BUFFER_ATR) * float(atr)
    )


def _find_break_event(features, four_closed, future4h, signal_time):
    atr = _num(features.get("atr_1h"))
    current = _num(features.get("current_price"))
    if atr is None or atr <= 0 or current is None:
        return None

    support = _structural_support(four_closed, current, atr)
    if support is None:
        return None

    level = float(support["level"])
    lower = float(support["lower"])
    upper = float(support["upper"])
    rows = _future_closed(future4h, signal_time, 4)
    if rows is None or rows.empty:
        return None

    for i in range(len(rows)):
        bar = rows.iloc[i]
        vals = _bar_values(bar)
        if vals is None:
            continue
        o, h, l, c = vals
        close_time = rows.index[i] + pd.Timedelta(hours=4)
        if c < lower - float(V447_BREAK_BUFFER_ATR) * atr:
            return {
                "support": support,
                "level": level,
                "lower": lower,
                "upper": upper,
                "atr": atr,
                "break_open_time": rows.index[i],
                "break_time": close_time,
                "break_o": o,
                "break_h": h,
                "break_l": l,
                "break_c": c,
                "break_body_atr": abs(o - c) / atr,
            }
    return None


def _watch_reclaim(event, future4h):
    """Advance the 4H event until reclaim, short-ready, or 7d expiry."""
    atr = float(event["atr"])
    lower = float(event["lower"])
    upper = float(event["upper"])
    break_time = pd.Timestamp(event["break_time"])
    watch_end = break_time + pd.Timedelta(days=int(V447_WATCH_DAYS))

    rows = _future_closed(future4h, break_time, 4)
    if rows is None or rows.empty:
        return {
            "state": "CENSORED_NO_4H_WATCH",
            "ready_reason": None,
            "ready_time": None,
        }

    reclaim_closes = 0
    records = []
    max_reclaim_high = float(event["break_h"])
    retest_attempts = 0
    bars_below = 0

    for i in range(len(rows)):
        open_time = rows.index[i]
        close_time = open_time + pd.Timedelta(hours=4)
        if close_time > watch_end:
            break

        vals = _bar_values(rows.iloc[i])
        if vals is None:
            continue
        o, h, l, c = vals
        max_reclaim_high = max(max_reclaim_high, h)
        record = {
            "open_time": open_time,
            "close_time": close_time,
            "open": o, "high": h, "low": l, "close": c,
        }
        records.append(record)

        reclaim_threshold = upper + float(V447_RECLAIM_BUFFER_ATR) * atr
        if c > reclaim_threshold:
            reclaim_closes += 1
        else:
            reclaim_closes = 0

        if reclaim_closes >= int(V447_RECLAIM_CONFIRM_4H):
            return {
                "state": "RECLAIMED",
                "ready_reason": None,
                "ready_time": None,
                "watch_bars": len(records),
                "watch_hours": len(records) * 4,
                "retest_attempts": retest_attempts,
                "max_reclaim_high": max_reclaim_high,
                "bars_below": bars_below,
            }

        if c < lower:
            bars_below += 1

        touched_zone = h >= lower - float(V447_RETEST_TOUCH_ATR) * atr
        if touched_zone:
            retest_attempts += 1
            rng = max(h - l, 1e-12)
            upper_wick_ratio = (h - max(o, c)) / rng
            failed_reclaim = bool(
                c < lower
                and c < o
                and (
                    upper_wick_ratio >= float(V447_MIN_REJECTION_WICK_RATIO)
                    or (len(records) >= 2 and c < float(records[-2]["close"]))
                )
            )
            if failed_reclaim:
                return {
                    "state": "SHORT_READY",
                    "ready_reason": "FAILED_RECLAIM_TOUCH",
                    "ready_time": close_time,
                    "watch_bars": len(records),
                    "watch_hours": len(records) * 4,
                    "retest_attempts": retest_attempts,
                    "max_reclaim_high": max_reclaim_high,
                    "ready_reclaim_high": h,
                    "bars_below": bars_below,
                    "lower_high_confirmed": int(
                        _lower_high_confirmed(records, atr)
                    ),
                }

        if len(records) >= int(V447_PERSIST_MIN_4H_BARS):
            recent = records[-int(V447_PERSIST_WINDOW_4H):]
            below_count = sum(float(x["close"]) < lower for x in recent)
            lower_high = _lower_high_confirmed(records, atr)
            if (
                below_count >= int(V447_PERSIST_MIN_CLOSES_BELOW)
                and lower_high
                and reclaim_closes == 0
            ):
                return {
                    "state": "SHORT_READY",
                    "ready_reason": "PERSISTENT_NO_RECLAIM_LOWER_HIGH",
                    "ready_time": close_time,
                    "watch_bars": len(records),
                    "watch_hours": len(records) * 4,
                    "retest_attempts": retest_attempts,
                    "max_reclaim_high": max_reclaim_high,
                    "ready_reclaim_high": max(float(x["high"]) for x in recent),
                    "bars_below": bars_below,
                    "lower_high_confirmed": 1,
                }

    return {
        "state": "EXPIRED_NO_SHORT_READY",
        "ready_reason": None,
        "ready_time": None,
        "watch_bars": len(records),
        "watch_hours": len(records) * 4,
        "retest_attempts": retest_attempts,
        "max_reclaim_high": max_reclaim_high,
        "bars_below": bars_below,
    }


def _find_1h_entry(watch, event, future1h, future15):
    ready_time = pd.Timestamp(watch["ready_time"])
    upper = float(event["upper"])
    lower = float(event["lower"])
    atr = float(event["atr"])
    deadline = ready_time + pd.Timedelta(hours=int(V447_ENTRY_CONFIRM_HOURS))

    rows = _future_closed(future1h, ready_time, 1)
    if rows is None or rows.empty:
        return {"state": "NO_1H_CONFIRMATION"}

    recent_highs = []
    for i in range(len(rows)):
        open_time = rows.index[i]
        close_time = open_time + pd.Timedelta(hours=1)
        if close_time > deadline:
            break
        vals = _bar_values(rows.iloc[i])
        if vals is None:
            continue
        o, h, l, c = vals
        recent_highs.append(h)

        prev_close = None
        if i > 0:
            prev_vals = _bar_values(rows.iloc[i - 1])
            if prev_vals is not None:
                prev_close = prev_vals[3]

        bearish_confirm = bool(
            c < o
            and c < lower
            and (prev_close is None or c < prev_close)
            and h <= upper + 0.25 * atr
        )
        if not bearish_confirm:
            continue

        if future15 is None or future15.empty:
            return {"state": "NO_15M_ENTRY_BAR"}
        pos = int(future15.index.searchsorted(close_time, side="left"))
        if pos >= len(future15):
            return {"state": "NO_15M_ENTRY_BAR"}
        if future15.index[pos] < close_time:
            continue

        entry = float(future15.iloc[pos]["open"])
        entry_below_atr = max(0.0, (lower - entry) / atr)
        if entry_below_atr > float(V447_MAX_ENTRY_BELOW_SUPPORT_ATR):
            return {
                "state": "SKIP_CHASE_BELOW_SUPPORT",
                "entry_below_support_atr": entry_below_atr,
            }

        return {
            "state": "ENTRY",
            "confirm_time": close_time,
            "entry_idx": pos,
            "entry": entry,
            "entry_below_support_atr": entry_below_atr,
            "confirm_high": h,
            "confirm_low": l,
            "confirm_close": c,
            "recent_1h_high": max(recent_highs[-6:]),
        }

    return {"state": "NO_1H_CONFIRMATION"}


def evaluate_v447_m2(
    features,
    signal_time,
    hist4h,
    future4h,
    future1h,
    future15,
    one_all,
    four_all,
):
    prefix = "v447_m2"
    out = _empty(prefix, "NO_STRUCTURAL_BREAK")
    out.update({
        f"{prefix}_lifecycle": "NO_EVENT",
        f"{prefix}_break_time": None,
        f"{prefix}_support_level": None,
        f"{prefix}_support_lower": None,
        f"{prefix}_support_upper": None,
        f"{prefix}_support_touches": None,
        f"{prefix}_watch_state": None,
        f"{prefix}_ready_reason": None,
        f"{prefix}_ready_time": None,
        f"{prefix}_watch_hours": None,
        f"{prefix}_retest_attempts": None,
        f"{prefix}_lower_high_confirmed": None,
        f"{prefix}_entry_below_support_atr": None,
    })

    event = _find_break_event(features, hist4h, future4h, signal_time)
    if event is None:
        return out

    out.update({
        f"{prefix}_lifecycle": "BREAK_CONFIRMED",
        f"{prefix}_break_time": event["break_time"].isoformat(),
        f"{prefix}_break_body_atr": round(float(event["break_body_atr"]), 4),
        f"{prefix}_support_level": round(float(event["level"]), 10),
        f"{prefix}_support_lower": round(float(event["lower"]), 10),
        f"{prefix}_support_upper": round(float(event["upper"]), 10),
        f"{prefix}_support_touches": int(event["support"]["touches"]),
    })

    watch = _watch_reclaim(event, future4h)
    out.update({
        f"{prefix}_watch_state": watch.get("state"),
        f"{prefix}_ready_reason": watch.get("ready_reason"),
        f"{prefix}_ready_time": (
            watch["ready_time"].isoformat()
            if watch.get("ready_time") is not None
            else None
        ),
        f"{prefix}_watch_hours": watch.get("watch_hours"),
        f"{prefix}_retest_attempts": watch.get("retest_attempts"),
        f"{prefix}_bars_below": watch.get("bars_below"),
        f"{prefix}_max_reclaim_high": (
            round(float(watch["max_reclaim_high"]), 10)
            if watch.get("max_reclaim_high") is not None
            else None
        ),
        f"{prefix}_lower_high_confirmed": watch.get("lower_high_confirmed"),
    })
    if watch.get("state") != "SHORT_READY":
        out[f"{prefix}_lifecycle"] = watch.get("state") or "WATCH_ENDED"
        out[f"{prefix}_state"] = watch.get("state") or "WATCH_ENDED"
        return out

    out[f"{prefix}_lifecycle"] = "SHORT_READY"
    entry_plan = _find_1h_entry(
        watch, event, future1h, future15
    )
    out[f"{prefix}_entry_selection_state"] = entry_plan.get("state")
    if entry_plan.get("state") != "ENTRY":
        out[f"{prefix}_state"] = entry_plan.get("state") or "NO_ENTRY"
        return out

    atr = float(event["atr"])
    entry = float(entry_plan["entry"])
    anchor = max(
        float(watch.get("ready_reclaim_high") or event["upper"]),
        float(entry_plan.get("recent_1h_high") or event["upper"]),
        float(event["upper"]),
    )
    stop = max(
        anchor + float(V447_STOP_BUFFER_ATR) * atr,
        entry + float(V447_MIN_RISK_ATR) * atr,
    )
    reason = _plan_reason(
        entry,
        stop,
        atr,
        V447_MAX_RISK_ATR,
        V447_MAX_STOP_PCT,
        V447_MAX_COST_R,
    )
    if reason:
        out[f"{prefix}_state"] = reason
        return out

    entry_time = future15.index[int(entry_plan["entry_idx"])]
    one_ctx = _closed(one_all, entry_time, 1)
    four_ctx = _closed(four_all, entry_time, 4)
    demand = _next_demand_below(
        one_ctx,
        four_ctx,
        entry,
        atr,
        float(event["level"]),
    )
    if demand is None:
        out[f"{prefix}_state"] = "NO_NEXT_DEMAND"
        return out

    risk = stop - entry
    target = float(demand["upper"]) + 0.10 * atr
    room_r = (entry - target) / risk
    if target <= 0 or target >= entry or room_r < float(V447_MIN_ROOM_R):
        out[f"{prefix}_state"] = "SKIP_ROOM_TO_DEMAND"
        return out

    tp1 = entry - float(V447_TP1_R) * risk
    seed = dict(out)
    seed.update({
        f"{prefix}_state": "PLANNED",
        f"{prefix}_lifecycle": "ENTRY",
        f"{prefix}_confirm_time": entry_plan["confirm_time"].isoformat(),
        f"{prefix}_entry_below_support_atr": round(
            float(entry_plan["entry_below_support_atr"]), 4
        ),
        f"{prefix}_demand_source": demand["source"],
        f"{prefix}_demand_lower": round(float(demand["lower"]), 10),
        f"{prefix}_demand_upper": round(float(demand["upper"]), 10),
        f"{prefix}_demand_target": round(target, 10),
        f"{prefix}_room_r": round(room_r, 4),
        f"{prefix}_room_pass": 1,
    })

    return _simulate_staged(
        prefix,
        future15,
        int(entry_plan["entry_idx"]),
        entry,
        stop,
        atr,
        tp1,
        target,
        room_r,
        float(event["lower"]),
        seed,
    )
