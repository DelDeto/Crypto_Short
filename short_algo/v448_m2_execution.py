"""V4.4.8 M2-only persistent broken-support execution.

The V4.4.7 lifecycle is retained:
4H support break -> watch up to 7d -> reclaim cancel OR SHORT_READY ->
1H bearish confirmation -> next 15m open.

Post-entry execution is rebuilt for multi-day breakdowns:
- tactical stop above recent reclaim/lower-high structure;
- minor 1H demand never blocks entry;
- nearest MAJOR 4H demand is the structural destination when reasonably near;
- if major demand is far or absent, classify OPEN_SPACE and use 2R -> 4R ->
  25% runner.
"""
import math

import pandas as pd

from .v440_execution import _is_unbroken, _pivot_lows
from .v441_config import V441_COST_BPS
from .v441_execution import _empty
from .v445_execution import _plan_reason as _legacy_plan_reason
from .v447_config import V447_RECLAIM_BUFFER_ATR
from .v447_execution import (
    _closed,
    _find_1h_entry,
    _find_break_event,
    _watch_reclaim,
)
from .v448_m2_config import (
    V448_M2_HOLD_HOURS,
    V448_M2_MAJOR_CLUSTER_ATR,
    V448_M2_MAJOR_DEPARTURE_ATR,
    V448_M2_MAJOR_LOOKBACK_4H,
    V448_M2_MAJOR_MIN_SEPARATION_BARS,
    V448_M2_MAJOR_TARGET_BUFFER_ATR,
    V448_M2_MAJOR_WIDTH_ATR,
    V448_M2_MAX_COST_R,
    V448_M2_MAX_RISK_ATR,
    V448_M2_MAX_STOP_PCT,
    V448_M2_MIN_MAJOR_ROOM_R,
    V448_M2_MIN_RISK_ATR,
    V448_M2_OPEN_SPACE_ROOM_R,
    V448_M2_OPEN_TP2_R,
    V448_M2_STOP_BUFFER_ATR,
    V448_M2_TP1_R,
)

STEP = pd.Timedelta(minutes=15)


def _num(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _major_4h_demand(four_closed, entry, atr):
    """Nearest MAJOR 4H demand known at entry time.

    A zone is major when it has either repeated 4H pivot reactions or a strong
    post-pivot departure. This deliberately ignores small 1H demand clusters.
    """
    pivots = _pivot_lows(four_closed, int(V448_M2_MAJOR_LOOKBACK_4H))
    pivots = [
        p for p in pivots
        if float(p["low"]) < float(entry) and _is_unbroken(p, atr)
    ]
    if not pivots:
        return None

    enriched = []
    for p in pivots:
        view = p["view"]
        pos = int(p["pos"])
        after = view.iloc[pos + 1 : pos + 7]
        departure = 0.0
        if not after.empty:
            departure = (
                float(after["high"].astype(float).max()) - float(p["low"])
            ) / atr
        enriched.append({
            **p,
            "departure_atr": departure,
        })

    enriched.sort(key=lambda x: float(x["low"]))
    groups = []
    for p in enriched:
        if (
            groups
            and abs(float(p["low"]) - float(groups[-1][-1]["low"]))
            <= float(V448_M2_MAJOR_CLUSTER_ATR) * atr
        ):
            groups[-1].append(p)
        else:
            groups.append([p])

    candidates = []
    for group in groups:
        positions = sorted(int(p["pos"]) for p in group)
        repeated = bool(
            len(group) >= 2
            and positions[-1] - positions[0]
            >= int(V448_M2_MAJOR_MIN_SEPARATION_BARS)
        )
        strongest_departure = max(float(p["departure_atr"]) for p in group)
        if (
            not repeated
            and strongest_departure < float(V448_M2_MAJOR_DEPARTURE_ATR)
        ):
            continue

        lower = min(float(p["low"]) for p in group)
        body_top = max(
            max(float(p["open"]), float(p["close"])) for p in group
        )
        upper = min(
            body_top,
            lower + float(V448_M2_MAJOR_WIDTH_ATR) * atr,
        )
        upper = max(upper, lower + 0.15 * atr)
        if upper >= entry:
            continue

        candidates.append({
            "source": (
                "MAJOR_4H_CLUSTER"
                if repeated
                else "MAJOR_4H_DEPARTURE"
            ),
            "lower": lower,
            "upper": upper,
            "touches": len(group),
            "departure_atr": strongest_departure,
        })

    if not candidates:
        return None
    candidates.sort(
        key=lambda x: (float(x["upper"]), int(x["touches"])),
        reverse=True,
    )
    return candidates[0]


def _plan_reason(entry, stop, atr):
    if any(x is None for x in (entry, stop, atr)):
        return "INVALID_PLAN"
    if entry <= 0 or stop <= entry or atr <= 0:
        return "INVALID_PLAN"
    risk = stop - entry
    if 100.0 * risk / entry > float(V448_M2_MAX_STOP_PCT):
        return "SKIP_STOP_PCT"
    if risk / atr > float(V448_M2_MAX_RISK_ATR):
        return "SKIP_RISK_TOO_WIDE"
    cost_r = float(V441_COST_BPS) / 10000.0 * entry / risk
    if cost_r > float(V448_M2_MAX_COST_R):
        return "SKIP_COST_R"
    return None


def _finish(out, prefix, state, gross, cost_r, bars, exit_time):
    out.update({
        f"{prefix}_state": state,
        f"{prefix}_gross_r": round(float(gross), 5),
        f"{prefix}_net_r": round(float(gross) - float(cost_r), 5),
        f"{prefix}_hold_bars": int(bars),
        f"{prefix}_exit_time": exit_time.isoformat(),
    })
    return out


def _simulate(prefix, future15, start_idx, entry, stop, atr, mode, major_target, room_r, seed):
    out = dict(seed)
    risk = stop - entry
    cost_r = float(V441_COST_BPS) / 10000.0 * entry / risk
    entry_time = future15.index[start_idx]
    tp1 = entry - float(V448_M2_TP1_R) * risk
    open_tp2 = entry - float(V448_M2_OPEN_TP2_R) * risk
    tp2 = major_target if mode == "MAJOR_4H_DEMAND" else open_tp2

    out.update({
        f"{prefix}_state": "INVALID_PLAN",
        f"{prefix}_entry_time": entry_time.isoformat(),
        f"{prefix}_entry": round(entry, 10),
        f"{prefix}_stop": round(stop, 10),
        f"{prefix}_risk_pct": round(100.0 * risk / entry, 4),
        f"{prefix}_risk_atr": round(risk / atr, 4),
        f"{prefix}_cost_r": round(cost_r, 5),
        f"{prefix}_tp1": round(tp1, 10),
        f"{prefix}_tp2": (
            round(float(tp2), 10) if tp2 is not None else None
        ),
        f"{prefix}_tp1_hit": 0,
        f"{prefix}_tp1_time": None,
        f"{prefix}_tp2_hit": 0,
        f"{prefix}_tp2_time": None,
    })

    if float(future15.iloc[start_idx]["open"]) >= stop:
        out[f"{prefix}_state"] = "GAP_BEYOND_STOP"
        return out

    end_time = entry_time + pd.Timedelta(hours=int(V448_M2_HOLD_HOURS))
    expected = entry_time
    bars = 0
    last_close = entry
    tp1_hit = False
    tp2_hit = False
    runner_target = (
        float(major_target)
        if mode == "OPEN_SPACE" and major_target is not None
        else None
    )
    runner_room = (
        (entry - runner_target) / risk
        if runner_target is not None
        else None
    )
    out[f"{prefix}_runner_target"] = (
        round(runner_target, 10) if runner_target is not None else None
    )
    out[f"{prefix}_runner_room_r"] = (
        round(runner_room, 4) if runner_room is not None else None
    )

    for i in range(start_idx, len(future15)):
        t = future15.index[i]
        if t >= end_time:
            break
        if t != expected:
            out[f"{prefix}_state"] = "CENSORED_15M_GAP"
            return out
        expected += STEP
        bars += 1

        bar = future15.iloc[i]
        o, h, l, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
        if not all(math.isfinite(x) for x in (o, h, l, c)):
            out[f"{prefix}_state"] = "CENSORED_BAD_BAR"
            return out
        last_close = c

        # Conservative collision: protective stop is evaluated before a new
        # downside target on every bar.
        if not tp1_hit:
            if h >= stop:
                gross = (entry - max(o, stop)) / risk
                return _finish(
                    out, prefix, "SL_FIRST", gross, cost_r, bars, t + STEP
                )

            if l <= tp1:
                tp1_hit = True
                out[f"{prefix}_tp1_hit"] = 1
                out[f"{prefix}_tp1_time"] = (t + STEP).isoformat()

                if mode == "MAJOR_4H_DEMAND" and l <= float(tp2):
                    gross = 1.0 + 0.5 * float(room_r)
                    out[f"{prefix}_tp2_hit"] = 1
                    out[f"{prefix}_tp2_time"] = (t + STEP).isoformat()
                    return _finish(
                        out, prefix, "TP2_MAJOR_4H_DEMAND",
                        gross, cost_r, bars, t + STEP
                    )

                if mode == "OPEN_SPACE" and l <= open_tp2:
                    tp2_hit = True
                    out[f"{prefix}_tp2_hit"] = 1
                    out[f"{prefix}_tp2_time"] = (t + STEP).isoformat()
                    if runner_target is not None and l <= runner_target:
                        gross = 2.0 + 0.25 * float(runner_room)
                        return _finish(
                            out, prefix, "OPEN_RUNNER_MAJOR_4H_DEMAND",
                            gross, cost_r, bars, t + STEP
                        )
            continue

        if mode == "MAJOR_4H_DEMAND":
            if h >= entry:
                return _finish(
                    out, prefix, "TP1_THEN_BE", 1.0, cost_r, bars, t + STEP
                )
            if l <= float(tp2):
                gross = 1.0 + 0.5 * float(room_r)
                out[f"{prefix}_tp2_hit"] = 1
                out[f"{prefix}_tp2_time"] = (t + STEP).isoformat()
                return _finish(
                    out, prefix, "TP2_MAJOR_4H_DEMAND",
                    gross, cost_r, bars, t + STEP
                )
            continue

        # OPEN_SPACE.
        if not tp2_hit:
            if h >= entry:
                return _finish(
                    out, prefix, "OPEN_BE_AFTER_TP1",
                    1.0, cost_r, bars, t + STEP
                )
            if l <= open_tp2:
                tp2_hit = True
                out[f"{prefix}_tp2_hit"] = 1
                out[f"{prefix}_tp2_time"] = (t + STEP).isoformat()
                if runner_target is not None and l <= runner_target:
                    gross = 2.0 + 0.25 * float(runner_room)
                    return _finish(
                        out, prefix, "OPEN_RUNNER_MAJOR_4H_DEMAND",
                        gross, cost_r, bars, t + STEP
                    )
            continue

        # After 4R, protect the last 25% at the 2R price.
        if h >= tp1:
            return _finish(
                out, prefix, "OPEN_PROTECT_AFTER_4R",
                2.5, cost_r, bars, t + STEP
            )
        if runner_target is not None and l <= runner_target:
            gross = 2.0 + 0.25 * float(runner_room)
            return _finish(
                out, prefix, "OPEN_RUNNER_MAJOR_4H_DEMAND",
                gross, cost_r, bars, t + STEP
            )

    current_r = (entry - last_close) / risk
    if mode == "MAJOR_4H_DEMAND":
        gross = (
            1.0 + 0.5 * current_r
            if tp1_hit
            else current_r
        )
        state = "DEMAND_TIME_EXIT"
    else:
        if tp2_hit:
            gross = 2.0 + 0.25 * current_r
        elif tp1_hit:
            gross = 1.0 + 0.5 * current_r
        else:
            gross = current_r
        state = "OPEN_TIME_EXIT"
    return _finish(
        out, prefix, state, gross, cost_r, bars, min(end_time, expected)
    )


def evaluate_v448_m2(
    features,
    signal_time,
    hist4h,
    future4h,
    future1h,
    future15,
    one_all,
    four_all,
):
    prefix = "v448_m2"
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
        f"{prefix}_entry_selection_state": None,
        f"{prefix}_target_mode": None,
        f"{prefix}_major_demand_source": None,
        f"{prefix}_major_demand_lower": None,
        f"{prefix}_major_demand_upper": None,
        f"{prefix}_major_demand_room_r": None,
        f"{prefix}_hard_thesis_invalidation": None,
        f"{prefix}_runner_target": None,
        f"{prefix}_runner_room_r": None,
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
        f"{prefix}_hard_thesis_invalidation": round(
            float(event["upper"])
            + float(V447_RECLAIM_BUFFER_ATR) * float(event["atr"]),
            10,
        ),
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
        f"{prefix}_lower_high_confirmed": watch.get("lower_high_confirmed"),
    })
    if watch.get("state") != "SHORT_READY":
        out[f"{prefix}_lifecycle"] = watch.get("state") or "WATCH_ENDED"
        out[f"{prefix}_state"] = watch.get("state") or "WATCH_ENDED"
        return out

    out[f"{prefix}_lifecycle"] = "SHORT_READY"
    entry_plan = _find_1h_entry(watch, event, future1h, future15)
    out[f"{prefix}_entry_selection_state"] = entry_plan.get("state")
    if entry_plan.get("state") != "ENTRY":
        out[f"{prefix}_state"] = entry_plan.get("state") or "NO_ENTRY"
        return out

    atr = float(event["atr"])
    entry = float(entry_plan["entry"])
    if watch.get("ready_reason") == "FAILED_RECLAIM_TOUCH":
        tactical_anchor = max(
            float(watch.get("ready_reclaim_high") or entry),
            float(entry_plan.get("recent_1h_high") or entry),
            float(entry_plan.get("confirm_high") or entry),
        )
    else:
        tactical_anchor = max(
            float(entry_plan.get("recent_1h_high") or entry),
            float(entry_plan.get("confirm_high") or entry),
        )

    stop = max(
        tactical_anchor + float(V448_M2_STOP_BUFFER_ATR) * atr,
        entry + float(V448_M2_MIN_RISK_ATR) * atr,
    )
    reason = _plan_reason(entry, stop, atr)
    if reason:
        out[f"{prefix}_state"] = reason
        return out

    entry_time = future15.index[int(entry_plan["entry_idx"])]
    four_ctx = _closed(four_all, entry_time, 4)
    demand = _major_4h_demand(four_ctx, entry, atr)

    risk = stop - entry
    major_target = None
    major_room_r = None
    if demand is not None:
        major_target = float(demand["upper"]) + float(
            V448_M2_MAJOR_TARGET_BUFFER_ATR
        ) * atr
        if major_target < entry:
            major_room_r = (entry - major_target) / risk
        out.update({
            f"{prefix}_major_demand_source": demand["source"],
            f"{prefix}_major_demand_lower": round(float(demand["lower"]), 10),
            f"{prefix}_major_demand_upper": round(float(demand["upper"]), 10),
            f"{prefix}_major_demand_touches": int(demand["touches"]),
            f"{prefix}_major_demand_departure_atr": round(
                float(demand["departure_atr"]), 4
            ),
            f"{prefix}_major_demand_room_r": (
                round(float(major_room_r), 4)
                if major_room_r is not None
                else None
            ),
        })

    if (
        major_room_r is not None
        and major_room_r < float(V448_M2_MIN_MAJOR_ROOM_R)
    ):
        out[f"{prefix}_state"] = "SKIP_MAJOR_4H_DEMAND_TOO_CLOSE"
        return out

    mode = (
        "OPEN_SPACE"
        if major_room_r is None
        or major_room_r >= float(V448_M2_OPEN_SPACE_ROOM_R)
        else "MAJOR_4H_DEMAND"
    )
    out[f"{prefix}_target_mode"] = mode
    out[f"{prefix}_lifecycle"] = "ENTRY"

    seed = dict(out)
    seed.update({
        f"{prefix}_state": "PLANNED",
        f"{prefix}_confirm_time": entry_plan["confirm_time"].isoformat(),
        f"{prefix}_entry_below_support_atr": round(
            float(entry_plan["entry_below_support_atr"]), 4
        ),
        f"{prefix}_tactical_anchor": round(tactical_anchor, 10),
        f"{prefix}_room_r": (
            round(float(major_room_r), 4)
            if major_room_r is not None
            else None
        ),
        f"{prefix}_room_pass": 1,
    })

    return _simulate(
        prefix,
        future15,
        int(entry_plan["entry_idx"]),
        entry,
        stop,
        atr,
        mode,
        major_target,
        major_room_r,
        seed,
    )
