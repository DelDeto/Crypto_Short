"""V4.4.14 M2 execution with causal 24-48h watch-time gate."""
from .v447_execution import _find_break_event
from .v449_m2_execution import _find_1h_entry, _watch_support_flip
from .v4412_m2_execution import _simulate_variant
from .v4414_m2_config import (
    V4414_MAX_WATCH_HOURS,
    V4414_MIN_WATCH_HOURS,
    V4414_STOP_ATR,
)

PERSISTENT = "PERSISTENT_NO_RECLAIM_LOWER_HIGHS"


def evaluate_v4414_m2(features, signal_time, hist4h, future4h, future1h, future15):
    prefix = "v4414_m2"
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
        f"{prefix}_pivot_high_count": None,
        f"{prefix}_bars_below": None,
        f"{prefix}_entry_selection_state": None,
        f"{prefix}_entry_time": None,
        f"{prefix}_entry": None,
        f"{prefix}_entry_below_support_atr": None,
        f"{prefix}_atr_at_entry": None,
        f"{prefix}_watch_gate_pass": 0,
    }

    event = _find_break_event(features, hist4h, future4h, signal_time)
    if event is None:
        return out

    atr = float(event["atr"])
    out.update({
        f"{prefix}_state": "BREAK_CONFIRMED",
        f"{prefix}_break_time": event["break_time"].isoformat(),
        f"{prefix}_support_level": round(float(event["level"]), 10),
        f"{prefix}_support_lower": round(float(event["lower"]), 10),
        f"{prefix}_support_upper": round(float(event["upper"]), 10),
    })

    watch = _watch_support_flip(event, future4h)
    watch_hours = watch.get("watch_hours")
    out.update({
        f"{prefix}_ready_reason": watch.get("ready_reason"),
        f"{prefix}_ready_time": (
            watch["ready_time"].isoformat()
            if watch.get("ready_time") is not None
            else None
        ),
        f"{prefix}_watch_hours": watch_hours,
        f"{prefix}_failed_reclaim_attempts": watch.get("failed_reclaim_attempts"),
        f"{prefix}_retest_attempts": watch.get("retest_attempts"),
        f"{prefix}_pivot_high_count": watch.get("pivot_high_count"),
        f"{prefix}_bars_below": watch.get("bars_below"),
    })

    if watch.get("state") != "CONFIRMED_SUPPORT_FLIP":
        out[f"{prefix}_state"] = watch.get("state") or "WATCH_ENDED"
        return out

    if watch.get("ready_reason") != PERSISTENT:
        out[f"{prefix}_state"] = "SKIP_NON_PERSISTENT_ROUTE"
        return out

    if watch_hours is None:
        out[f"{prefix}_state"] = "SKIP_WATCH_UNKNOWN"
        return out
    if float(watch_hours) < float(V4414_MIN_WATCH_HOURS):
        out[f"{prefix}_state"] = "SKIP_WATCH_TOO_YOUNG"
        return out
    if float(watch_hours) > float(V4414_MAX_WATCH_HOURS):
        out[f"{prefix}_state"] = "SKIP_WATCH_TOO_OLD"
        return out

    out[f"{prefix}_watch_gate_pass"] = 1

    entry_plan = _find_1h_entry(watch, event, future1h, future15)
    out[f"{prefix}_entry_selection_state"] = entry_plan.get("state")
    if entry_plan.get("state") != "ENTRY":
        out[f"{prefix}_state"] = entry_plan.get("state") or "NO_ENTRY"
        return out

    entry_idx = int(entry_plan["entry_idx"])
    entry = float(entry_plan["entry"])
    entry_time = future15.index[entry_idx]

    out.update({
        f"{prefix}_state": "ENTRY",
        f"{prefix}_entry_time": entry_time.isoformat(),
        f"{prefix}_entry": round(entry, 10),
        f"{prefix}_entry_below_support_atr": round(
            float(entry_plan["entry_below_support_atr"]), 5
        ),
        f"{prefix}_atr_at_entry": round(atr, 10),
    })

    sim = _simulate_variant(
        future15,
        entry_idx,
        entry,
        atr,
        float(V4414_STOP_ATR),
    )

    src = "v4412_m2_s1_75"
    dst = "v4414_m2_exec"
    for key, value in sim.items():
        if key.startswith(src):
            out[key.replace(src, dst, 1)] = value
    return out
