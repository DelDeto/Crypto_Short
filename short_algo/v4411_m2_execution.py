"""V4.4.11 M2 execution study.

Entry lifecycle is frozen from V4.4.10/V4.4.9:
  break -> confirmed support flip -> 1H bearish confirmation -> next 15m open.

This module does not alter signal selection. It simulates three predeclared
ATR-stop variants on the same entry and records realized R after costs.
"""
import math

import pandas as pd

from .v441_config import V441_COST_BPS
from .v447_execution import _find_break_event
from .v449_m2_execution import _find_1h_entry, _watch_support_flip
from .v4411_m2_config import (
    V4411_HOLD_HOURS,
    V4411_STOP_ATR_VARIANTS,
    V4411_TP1_R,
    V4411_TP1_WEIGHT,
    V4411_TP2_R,
    V4411_TP2_WEIGHT,
)

STEP = pd.Timedelta(minutes=15)


def _bar_values(bar):
    vals = tuple(float(bar[k]) for k in ("open", "high", "low", "close"))
    return vals if all(math.isfinite(x) for x in vals) else None


def _tag(stop_atr):
    return str(stop_atr).replace(".", "_")


def _finish(out, prefix, state, gross_r, cost_r, bars, exit_time):
    out.update({
        f"{prefix}_state": state,
        f"{prefix}_gross_r": round(float(gross_r), 5),
        f"{prefix}_net_r": round(float(gross_r) - float(cost_r), 5),
        f"{prefix}_hold_bars": int(bars),
        f"{prefix}_exit_time": exit_time.isoformat(),
    })
    return out


def _simulate_variant(future15, entry_idx, entry, atr, stop_atr):
    prefix = f"v4411_m2_s{_tag(stop_atr)}"
    risk = float(stop_atr) * float(atr)
    stop = float(entry) + risk
    tp1 = float(entry) - float(V4411_TP1_R) * risk
    tp2 = float(entry) - float(V4411_TP2_R) * risk
    cost_r = float(V441_COST_BPS) / 10000.0 * float(entry) / risk

    out = {
        f"{prefix}_state": "INVALID",
        f"{prefix}_stop_atr": round(float(stop_atr), 4),
        f"{prefix}_stop": round(stop, 10),
        f"{prefix}_risk_atr": round(float(stop_atr), 4),
        f"{prefix}_risk_pct": round(100.0 * risk / float(entry), 5),
        f"{prefix}_cost_r": round(cost_r, 5),
        f"{prefix}_tp1": round(tp1, 10),
        f"{prefix}_tp2": round(tp2, 10),
        f"{prefix}_tp1_hit": 0,
        f"{prefix}_tp1_time": None,
        f"{prefix}_tp2_hit": 0,
        f"{prefix}_tp2_time": None,
        f"{prefix}_gross_r": None,
        f"{prefix}_net_r": None,
        f"{prefix}_hold_bars": None,
        f"{prefix}_exit_time": None,
    }

    if future15 is None or future15.empty or entry_idx >= len(future15):
        out[f"{prefix}_state"] = "CENSORED_NO_ENTRY_BAR"
        return out

    entry_time = future15.index[int(entry_idx)]
    if float(future15.iloc[int(entry_idx)]["open"]) >= stop:
        out[f"{prefix}_state"] = "GAP_BEYOND_STOP"
        return out

    end_time = entry_time + pd.Timedelta(hours=int(V4411_HOLD_HOURS))
    expected = entry_time
    tp1_hit = False
    tp1_index = None
    bars = 0
    last_close = float(entry)

    for i in range(int(entry_idx), len(future15)):
        t = future15.index[i]
        if t >= end_time:
            break
        if t != expected:
            out[f"{prefix}_state"] = "CENSORED_15M_GAP"
            return out
        expected += STEP
        bars += 1

        vals = _bar_values(future15.iloc[i])
        if vals is None:
            out[f"{prefix}_state"] = "CENSORED_BAD_BAR"
            return out
        o, h, l, c = vals
        last_close = c

        # Conservative same-bar ordering: full SL wins before TP1.
        if not tp1_hit:
            if h >= stop:
                gross = (float(entry) - max(o, stop)) / risk
                return _finish(
                    out, prefix, "SL_FIRST", gross, cost_r, bars, t + STEP
                )
            if l <= tp1:
                tp1_hit = True
                tp1_index = i
                out[f"{prefix}_tp1_hit"] = 1
                out[f"{prefix}_tp1_time"] = (t + STEP).isoformat()
                # If TP2 is also touched in the same bar after TP1, allow it
                # because stop was already checked first.
                if l <= tp2:
                    out[f"{prefix}_tp2_hit"] = 1
                    out[f"{prefix}_tp2_time"] = (t + STEP).isoformat()
                    gross = (
                        float(V4411_TP1_WEIGHT) * float(V4411_TP1_R)
                        + float(V4411_TP2_WEIGHT) * float(V4411_TP2_R)
                    )
                    return _finish(
                        out, prefix, "TP2_FULL", gross, cost_r, bars, t + STEP
                    )
                continue

        # Remaining 50% is protected at BE only from the bar after TP1.
        if tp1_index is not None and i > tp1_index and h >= float(entry):
            gross = float(V4411_TP1_WEIGHT) * float(V4411_TP1_R)
            return _finish(
                out, prefix, "TP1_THEN_BE", gross, cost_r, bars, t + STEP
            )

        if l <= tp2:
            out[f"{prefix}_tp2_hit"] = 1
            out[f"{prefix}_tp2_time"] = (t + STEP).isoformat()
            gross = (
                float(V4411_TP1_WEIGHT) * float(V4411_TP1_R)
                + float(V4411_TP2_WEIGHT) * float(V4411_TP2_R)
            )
            return _finish(
                out, prefix, "TP2_FULL", gross, cost_r, bars, t + STEP
            )

    if expected < end_time:
        out[f"{prefix}_state"] = "CENSORED_INCOMPLETE_HORIZON"
        return out

    current_r = (float(entry) - float(last_close)) / risk
    if tp1_hit:
        gross = (
            float(V4411_TP1_WEIGHT) * float(V4411_TP1_R)
            + float(V4411_TP2_WEIGHT) * current_r
        )
        state = "TP1_TIME_EXIT"
    else:
        gross = current_r
        state = "TIME_EXIT"
    return _finish(out, prefix, state, gross, cost_r, bars, end_time)


def evaluate_v4411_m2(
    features,
    signal_time,
    hist4h,
    future4h,
    future1h,
    future15,
):
    prefix = "v4411_m2"
    out = {
        f"{prefix}_state": "NO_STRUCTURAL_BREAK",
        f"{prefix}_break_time": None,
        f"{prefix}_support_level": None,
        f"{prefix}_support_lower": None,
        f"{prefix}_support_upper": None,
        f"{prefix}_ready_reason": None,
        f"{prefix}_ready_time": None,
        f"{prefix}_watch_hours": None,
        f"{prefix}_failed_reclaim_attempts": None,
        f"{prefix}_retest_attempts": None,
        f"{prefix}_entry_selection_state": None,
        f"{prefix}_entry_time": None,
        f"{prefix}_entry": None,
        f"{prefix}_entry_below_support_atr": None,
        f"{prefix}_atr_at_entry": None,
    }

    event = _find_break_event(features, hist4h, future4h, signal_time)
    if event is None:
        return out

    out.update({
        f"{prefix}_state": "BREAK_CONFIRMED",
        f"{prefix}_break_time": event["break_time"].isoformat(),
        f"{prefix}_support_level": round(float(event["level"]), 10),
        f"{prefix}_support_lower": round(float(event["lower"]), 10),
        f"{prefix}_support_upper": round(float(event["upper"]), 10),
    })

    watch = _watch_support_flip(event, future4h)
    out.update({
        f"{prefix}_ready_reason": watch.get("ready_reason"),
        f"{prefix}_ready_time": (
            watch["ready_time"].isoformat()
            if watch.get("ready_time") is not None
            else None
        ),
        f"{prefix}_watch_hours": watch.get("watch_hours"),
        f"{prefix}_failed_reclaim_attempts": watch.get("failed_reclaim_attempts"),
        f"{prefix}_retest_attempts": watch.get("retest_attempts"),
    })
    if watch.get("state") != "CONFIRMED_SUPPORT_FLIP":
        out[f"{prefix}_state"] = watch.get("state") or "WATCH_ENDED"
        return out

    entry_plan = _find_1h_entry(watch, event, future1h, future15)
    out[f"{prefix}_entry_selection_state"] = entry_plan.get("state")
    if entry_plan.get("state") != "ENTRY":
        out[f"{prefix}_state"] = entry_plan.get("state") or "NO_ENTRY"
        return out

    entry_idx = int(entry_plan["entry_idx"])
    entry = float(entry_plan["entry"])
    atr = float(event["atr"])
    entry_time = future15.index[entry_idx]

    out.update({
        f"{prefix}_state": "ENTRY",
        f"{prefix}_entry_time": entry_time.isoformat(),
        f"{prefix}_entry": round(entry, 10),
        f"{prefix}_entry_below_support_atr": round(
            float(entry_plan["entry_below_support_atr"]), 4
        ),
        f"{prefix}_atr_at_entry": round(atr, 10),
    })

    for stop_atr in V4411_STOP_ATR_VARIANTS:
        out.update(
            _simulate_variant(
                future15,
                entry_idx,
                entry,
                atr,
                float(stop_atr),
            )
        )
    return out
