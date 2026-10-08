"""V4.4.6 M2 Retest Window execution.

A structural support break opens an event, but the model does not short the
break candle. It waits from 1h to 3h after the break for a failed reclaim near
broken support. If price already extends too far before the retest, the event
is skipped rather than chased.

R1 balanced:
- >=2 consecutive closes accepted below support
- pre-retest extension <=1.25 ATR
- next-open entry <=0.30 ATR below support

R2 strict:
- >=3 consecutive closes accepted below support
- pre-retest extension <=0.90 ATR
- next-open entry <=0.20 ATR below support

Every trade decision is causal. No 24h future label is used for entry.
"""
import math

from .v441_execution import (
    _empty,
    _next_bar,
    _next_demand_below,
    _simulate_staged,
)
from .v445_execution import _detect_m2_break, _plan_reason
from .v446_config import (
    V446_HARD_RECLAIM_ATR,
    V446_MAX_COST_R,
    V446_MAX_RISK_ATR,
    V446_MAX_STOP_PCT,
    V446_MIN_RISK_ATR,
    V446_MIN_ROOM_R,
    V446_REJECTION_WICK_RATIO,
    V446_RETEST_END_BARS,
    V446_RETEST_START_BARS,
    V446_RETEST_TOUCH_ATR,
    V446_R1_MAX_ENTRY_BELOW_ATR,
    V446_R1_MAX_PRE_EXTENSION_ATR,
    V446_R1_MIN_ACCEPT_CLOSES,
    V446_R2_MAX_ENTRY_BELOW_ATR,
    V446_R2_MAX_PRE_EXTENSION_ATR,
    V446_R2_MIN_ACCEPT_CLOSES,
    V446_STOP_BUFFER_ATR,
    V446_TP1_R,
)


def _variant_params(mode):
    if mode == "R1":
        return {
            "min_accept": int(V446_R1_MIN_ACCEPT_CLOSES),
            "max_pre_extension": float(V446_R1_MAX_PRE_EXTENSION_ATR),
            "max_entry_below": float(V446_R1_MAX_ENTRY_BELOW_ATR),
        }
    if mode == "R2":
        return {
            "min_accept": int(V446_R2_MIN_ACCEPT_CLOSES),
            "max_pre_extension": float(V446_R2_MAX_PRE_EXTENSION_ATR),
            "max_entry_below": float(V446_R2_MAX_ENTRY_BELOW_ATR),
        }
    raise ValueError(f"Unknown V4.4.6 mode: {mode}")


def _select_retest_entry(event, mode):
    """Find the first causal failed-reclaim entry in the fixed 1-3h window."""
    p = _variant_params(mode)
    frame = event["frame"]
    i0 = int(event["break_idx"])
    level = float(event["level"])
    atr = float(event["atr"])

    start_idx = i0 + int(V446_RETEST_START_BARS)
    end_idx = min(
        len(frame) - 2,
        i0 + int(V446_RETEST_END_BARS),
    )
    if start_idx > end_idx:
        return {"state": "NO_RETEST_WINDOW"}

    consecutive_below = 0
    min_low = float("inf")
    early_retest = 0

    for j in range(i0, end_idx + 1):
        bar = frame.iloc[j]
        prev = frame.iloc[j - 1] if j > i0 else None
        o, h, l, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
        if not all(math.isfinite(x) for x in (o, h, l, c)):
            continue

        min_low = min(min_low, l)

        if c > level + float(V446_HARD_RECLAIM_ATR) * atr:
            return {
                "state": "HARD_RECLAIM_INVALIDATED",
                "early_retest": early_retest,
            }

        if c < level:
            consecutive_below += 1
        else:
            consecutive_below = 0

        touched = h >= level - float(V446_RETEST_TOUCH_ATR) * atr
        if touched and j < start_idx:
            early_retest = 1

        if j < start_idx:
            continue

        pre_extension_atr = max(0.0, (level - min_low) / atr)
        if pre_extension_atr > float(p["max_pre_extension"]):
            return {
                "state": "TOO_EXTENDED_BEFORE_RETEST",
                "early_retest": early_retest,
                "pre_extension_atr": pre_extension_atr,
            }

        if not touched:
            continue

        rng = max(h - l, 1e-12)
        upper_wick = h - max(o, c)
        wick_ratio = upper_wick / rng
        bearish_rejection = bool(
            c < level
            and c < o
            and (
                wick_ratio >= float(V446_REJECTION_WICK_RATIO)
                or (prev is not None and c < float(prev["close"]))
            )
        )
        if not bearish_rejection:
            continue

        if consecutive_below < int(p["min_accept"]):
            continue

        if not _next_bar(frame, j):
            return {
                "state": "NO_NEXT_OPEN",
                "early_retest": early_retest,
            }

        entry = float(frame.iloc[j + 1]["open"])
        entry_below_atr = max(0.0, (level - entry) / atr)
        if entry_below_atr > float(p["max_entry_below"]):
            continue

        return {
            "state": "ENTRY",
            "trigger_idx": j,
            "entry_idx": j + 1,
            "retest_bars_after_break": j - i0,
            "acceptance_closes": consecutive_below,
            "pre_extension_atr": pre_extension_atr,
            "entry_below_support_atr": entry_below_atr,
            "retest_high": h,
            "wick_ratio": wick_ratio,
            "early_retest": early_retest,
        }

    return {
        "state": "NO_VALID_RETEST_1H_3H",
        "early_retest": early_retest,
        "pre_extension_atr": (
            None if not math.isfinite(min_low) else max(0.0, (level - min_low) / atr)
        ),
    }


def _execute_variant(prefix, event, one_closed, four_closed, mode):
    out = _empty(prefix, "NO_BREAK_EVENT")
    out.update({
        f"{prefix}_mode": mode,
        f"{prefix}_break_time": event["break_time"].isoformat(),
        f"{prefix}_support_level": round(float(event["level"]), 10),
        f"{prefix}_selection_state": None,
        f"{prefix}_early_retest": None,
        f"{prefix}_retest_bars_after_break": None,
        f"{prefix}_acceptance_closes": None,
        f"{prefix}_pre_extension_atr": None,
        f"{prefix}_entry_below_support_atr": None,
        f"{prefix}_rejection_wick_ratio": None,
    })

    selection = _select_retest_entry(event, mode)
    out[f"{prefix}_selection_state"] = selection.get("state")
    out[f"{prefix}_early_retest"] = selection.get("early_retest")
    out[f"{prefix}_pre_extension_atr"] = (
        None
        if selection.get("pre_extension_atr") is None
        else round(float(selection["pre_extension_atr"]), 4)
    )
    if selection.get("state") != "ENTRY":
        out[f"{prefix}_state"] = selection.get("state") or "NO_ENTRY"
        return out

    frame = event["frame"]
    atr = float(event["atr"])
    level = float(event["level"])
    entry_idx = int(selection["entry_idx"])
    trigger_idx = int(selection["trigger_idx"])
    entry = float(frame.iloc[entry_idx]["open"])

    stop = max(
        float(selection["retest_high"]) + float(V446_STOP_BUFFER_ATR) * atr,
        level + float(V446_STOP_BUFFER_ATR) * atr,
        entry + float(V446_MIN_RISK_ATR) * atr,
    )
    reason = _plan_reason(
        entry,
        stop,
        atr,
        V446_MAX_RISK_ATR,
        V446_MAX_STOP_PCT,
        V446_MAX_COST_R,
    )
    if reason:
        out[f"{prefix}_state"] = reason
        return out

    demand = _next_demand_below(
        one_closed,
        four_closed,
        entry,
        atr,
        level,
    )
    if demand is None:
        out[f"{prefix}_state"] = "NO_NEXT_DEMAND"
        return out

    risk = stop - entry
    target = float(demand["upper"]) + 0.10 * atr
    room_r = (entry - target) / risk
    if target <= 0 or target >= entry or room_r < float(V446_MIN_ROOM_R):
        out[f"{prefix}_state"] = "SKIP_ROOM_TO_DEMAND"
        return out

    tp1 = entry - float(V446_TP1_R) * risk
    seed = _empty(prefix, "PLANNED")
    seed.update({
        f"{prefix}_context_ok": 1,
        f"{prefix}_mode": mode,
        f"{prefix}_break_time": event["break_time"].isoformat(),
        f"{prefix}_support_level": round(level, 10),
        f"{prefix}_support_touches": int(event["support"]["touches"]),
        f"{prefix}_pressure_score": int(event["pressure"].get("score") or 0),
        f"{prefix}_selection_state": "ENTRY",
        f"{prefix}_early_retest": int(selection.get("early_retest") or 0),
        f"{prefix}_retest_time": frame.index[trigger_idx].isoformat(),
        f"{prefix}_retest_bars_after_break": int(selection["retest_bars_after_break"]),
        f"{prefix}_acceptance_closes": int(selection["acceptance_closes"]),
        f"{prefix}_pre_extension_atr": round(float(selection["pre_extension_atr"]), 4),
        f"{prefix}_entry_below_support_atr": round(
            float(selection["entry_below_support_atr"]), 4
        ),
        f"{prefix}_rejection_wick_ratio": round(float(selection["wick_ratio"]), 4),
        f"{prefix}_demand_source": demand["source"],
        f"{prefix}_demand_lower": round(float(demand["lower"]), 10),
        f"{prefix}_demand_upper": round(float(demand["upper"]), 10),
        f"{prefix}_demand_target": round(target, 10),
        f"{prefix}_room_r": round(room_r, 4),
        f"{prefix}_room_pass": 1,
    })
    return _simulate_staged(
        prefix,
        frame,
        entry_idx,
        entry,
        stop,
        atr,
        tp1,
        target,
        room_r,
        level,
        seed,
    )


def evaluate_v446_m2(features, future15, one_closed, four_closed):
    out = {
        "v446_m2_event_found": 0,
        "v446_m2_event_break_time": None,
        "v446_m2_event_support": None,
        "v446_m2_event_support_touches": None,
        "v446_m2_event_pressure_score": None,
        "v446_m2_event_break_body_atr": None,
    }
    out.update(_empty("v446_m2_r1", "NO_BREAK_EVENT"))
    out.update(_empty("v446_m2_r2", "NO_BREAK_EVENT"))

    event = _detect_m2_break(features, future15, one_closed, four_closed)
    if event is None:
        return out

    out.update({
        "v446_m2_event_found": 1,
        "v446_m2_event_break_time": event["break_time"].isoformat(),
        "v446_m2_event_support": round(float(event["level"]), 10),
        "v446_m2_event_support_touches": int(event["support"]["touches"]),
        "v446_m2_event_pressure_score": int(event["pressure"].get("score") or 0),
        "v446_m2_event_break_body_atr": round(float(event["break_body_atr"]), 4),
    })
    out.update(_execute_variant(
        "v446_m2_r1", event, one_closed, four_closed, "R1"
    ))
    out.update(_execute_variant(
        "v446_m2_r2", event, one_closed, four_closed, "R2"
    ))
    return out
