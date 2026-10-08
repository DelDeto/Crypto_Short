"""V4.4.9 M2 — Confirmed Support Flip execution.

Lifecycle:
4H structural support break
 -> WATCH_SUPPORT_FLIP up to 7 days
 -> true reclaim (2 closes above zone) => cancel
 -> first failed reclaim => evidence only
 -> repeated failed reclaim + lower-high OR persistent no-reclaim + lower highs
 -> CONFIRMED_SUPPORT_FLIP
 -> causal 1H bearish confirmation
 -> next 15m open
 -> tactical stop above latest flip/lower-high structure
 -> 2R / 4R ladder, with major 4H demand used only as optional runner context.

No future path label is used in selection.
"""
import math

import pandas as pd

from .v440_execution import _is_unbroken, _pivot_lows
from .v441_config import V441_COST_BPS
from .v441_execution import _empty
from .v447_execution import _closed, _find_break_event, _future_closed
from .v449_m2_config import (
    V449_ENTRY_CONFIRM_HOURS,
    V449_HOLD_HOURS,
    V449_LOWER_HIGH_BUFFER_ATR,
    V449_MAJOR_CLUSTER_ATR,
    V449_MAJOR_DEPARTURE_ATR,
    V449_MAJOR_LOOKBACK_4H,
    V449_MAJOR_MIN_SEPARATION_BARS,
    V449_MAJOR_TARGET_BUFFER_ATR,
    V449_MAJOR_WIDTH_ATR,
    V449_MAX_COST_R,
    V449_MAX_ENTRY_BELOW_SUPPORT_ATR,
    V449_MAX_RISK_ATR,
    V449_MAX_STOP_PCT,
    V449_MIN_FAILED_RECLAIMS,
    V449_MIN_FLIP_HOURS,
    V449_MIN_RECLAIM_SEPARATION_4H,
    V449_MIN_RISK_ATR,
    V449_PERSIST_MIN_4H_BARS,
    V449_PERSIST_MIN_CLOSES_BELOW,
    V449_PERSIST_MIN_PIVOT_HIGHS,
    V449_PERSIST_WINDOW_4H,
    V449_PIVOT_LEFT,
    V449_PIVOT_RIGHT,
    V449_RECLAIM_BUFFER_ATR,
    V449_RECLAIM_CONFIRM_4H,
    V449_REJECTION_WICK_RATIO,
    V449_RETEST_TOUCH_ATR,
    V449_STOP_BUFFER_ATR,
    V449_TP1_R,
    V449_TP2_R,
    V449_WATCH_DAYS,
)

STEP = pd.Timedelta(minutes=15)


def _bar_values(bar):
    vals = tuple(float(bar[k]) for k in ("open", "high", "low", "close"))
    return vals if all(math.isfinite(x) for x in vals) else None


def _num(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _pivot_highs(records):
    left = int(V449_PIVOT_LEFT)
    right = int(V449_PIVOT_RIGHT)
    if len(records) < left + right + 1:
        return []
    out = []
    for i in range(left, len(records) - right):
        h = float(records[i]["high"])
        if any(h <= float(records[j]["high"]) for j in range(i - left, i)):
            continue
        if any(h < float(records[j]["high"]) for j in range(i + 1, i + right + 1)):
            continue
        out.append({
            "i": i,
            "high": h,
            "close_time": records[i]["close_time"],
        })
    return out


def _lower_high_pair(points, atr):
    if len(points) < 2:
        return None
    a = points[-2]
    b = points[-1]
    if (
        float(b["high"])
        <= float(a["high"]) - float(V449_LOWER_HIGH_BUFFER_ATR) * atr
    ):
        return {
            "prior_high": float(a["high"]),
            "latest_high": float(b["high"]),
            "prior_time": a.get("close_time"),
            "latest_time": b.get("close_time"),
        }
    return None


def _watch_support_flip(event, future4h):
    """Do not arm on first failed reclaim; require a confirmed support flip."""
    atr = float(event["atr"])
    lower = float(event["lower"])
    upper = float(event["upper"])
    break_time = pd.Timestamp(event["break_time"])
    watch_end = break_time + pd.Timedelta(days=int(V449_WATCH_DAYS))

    rows = _future_closed(future4h, break_time, 4)
    if rows is None or rows.empty:
        return {
            "state": "CENSORED_NO_4H_WATCH",
            "ready_time": None,
            "ready_reason": None,
        }

    records = []
    failed = []
    reclaim_closes = 0
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
        records.append({
            "i": len(records),
            "open_time": open_time,
            "close_time": close_time,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
        })

        reclaim_threshold = upper + float(V449_RECLAIM_BUFFER_ATR) * atr
        if c > reclaim_threshold:
            reclaim_closes += 1
        else:
            reclaim_closes = 0

        if reclaim_closes >= int(V449_RECLAIM_CONFIRM_4H):
            return {
                "state": "RECLAIMED",
                "ready_time": None,
                "ready_reason": None,
                "watch_bars": len(records),
                "watch_hours": len(records) * 4,
                "failed_reclaim_attempts": len(failed),
                "retest_attempts": retest_attempts,
                "pivot_high_count": len(_pivot_highs(records)),
                "bars_below": bars_below,
            }

        if c < lower:
            bars_below += 1

        touched = h >= lower - float(V449_RETEST_TOUCH_ATR) * atr
        if touched:
            retest_attempts += 1
            rng = max(h - l, 1e-12)
            upper_wick_ratio = (h - max(o, c)) / rng
            prev_close = (
                float(records[-2]["close"]) if len(records) >= 2 else None
            )
            rejection = bool(
                c < lower
                and c < o
                and (
                    upper_wick_ratio >= float(V449_REJECTION_WICK_RATIO)
                    or (prev_close is not None and c < prev_close)
                )
            )
            if rejection:
                if (
                    not failed
                    or len(records) - 1 - int(failed[-1]["record_i"])
                    >= int(V449_MIN_RECLAIM_SEPARATION_4H)
                ):
                    failed.append({
                        "record_i": len(records) - 1,
                        "high": h,
                        "close_time": close_time,
                        "upper_wick_ratio": upper_wick_ratio,
                    })

        elapsed_hours = (close_time - break_time).total_seconds() / 3600.0

        # Route A: repeated failed attempts whose highs step down.
        if (
            elapsed_hours >= float(V449_MIN_FLIP_HOURS)
            and len(failed) >= int(V449_MIN_FAILED_RECLAIMS)
        ):
            pair = _lower_high_pair(failed, atr)
            if pair is not None:
                return {
                    "state": "CONFIRMED_SUPPORT_FLIP",
                    "ready_time": close_time,
                    "ready_reason": "REPEATED_FAILED_RECLAIM_LOWER_HIGH",
                    "watch_bars": len(records),
                    "watch_hours": len(records) * 4,
                    "failed_reclaim_attempts": len(failed),
                    "retest_attempts": retest_attempts,
                    "pivot_high_count": len(_pivot_highs(records)),
                    "bars_below": bars_below,
                    "flip_anchor_high": float(pair["latest_high"]),
                    "prior_flip_high": float(pair["prior_high"]),
                }

        # Route B: support remains lost for >=24h and 4H swing highs step down.
        if len(records) >= int(V449_PERSIST_MIN_4H_BARS):
            recent = records[-int(V449_PERSIST_WINDOW_4H):]
            closes_below = sum(float(x["close"]) < lower for x in recent)
            pivots = _pivot_highs(records)
            pair = _lower_high_pair(pivots, atr)
            if (
                closes_below >= int(V449_PERSIST_MIN_CLOSES_BELOW)
                and len(pivots) >= int(V449_PERSIST_MIN_PIVOT_HIGHS)
                and pair is not None
                and float(pair["latest_high"]) < reclaim_threshold
            ):
                return {
                    "state": "CONFIRMED_SUPPORT_FLIP",
                    "ready_time": close_time,
                    "ready_reason": "PERSISTENT_NO_RECLAIM_LOWER_HIGHS",
                    "watch_bars": len(records),
                    "watch_hours": len(records) * 4,
                    "failed_reclaim_attempts": len(failed),
                    "retest_attempts": retest_attempts,
                    "pivot_high_count": len(pivots),
                    "bars_below": bars_below,
                    "flip_anchor_high": float(pair["latest_high"]),
                    "prior_flip_high": float(pair["prior_high"]),
                }

    pivots = _pivot_highs(records)
    return {
        "state": "EXPIRED_NO_CONFIRMED_FLIP",
        "ready_time": None,
        "ready_reason": None,
        "watch_bars": len(records),
        "watch_hours": len(records) * 4,
        "failed_reclaim_attempts": len(failed),
        "retest_attempts": retest_attempts,
        "pivot_high_count": len(pivots),
        "bars_below": bars_below,
    }


def _find_1h_entry(watch, event, future1h, future15):
    ready_time = pd.Timestamp(watch["ready_time"])
    upper = float(event["upper"])
    lower = float(event["lower"])
    atr = float(event["atr"])
    deadline = ready_time + pd.Timedelta(hours=int(V449_ENTRY_CONFIRM_HOURS))

    rows = _future_closed(future1h, ready_time, 1)
    if rows is None or rows.empty:
        return {"state": "NO_1H_CONFIRMATION"}

    recent_highs = []
    for i in range(len(rows)):
        close_time = rows.index[i] + pd.Timedelta(hours=1)
        if close_time > deadline:
            break
        vals = _bar_values(rows.iloc[i])
        if vals is None:
            continue
        o, h, l, c = vals
        recent_highs.append(h)

        prev_close = None
        if i > 0:
            prev = _bar_values(rows.iloc[i - 1])
            if prev is not None:
                prev_close = prev[3]

        bearish_confirm = bool(
            c < o
            and c < lower
            and prev_close is not None
            and c < prev_close
            and h <= upper + 0.25 * atr
        )
        if not bearish_confirm:
            continue

        if future15 is None or future15.empty:
            return {"state": "NO_15M_ENTRY_BAR"}
        pos = int(future15.index.searchsorted(close_time, side="left"))
        if pos >= len(future15):
            return {"state": "NO_15M_ENTRY_BAR"}

        entry = float(future15.iloc[pos]["open"])
        distance = max(0.0, (lower - entry) / atr)
        if distance > float(V449_MAX_ENTRY_BELOW_SUPPORT_ATR):
            return {
                "state": "SKIP_CHASE_BELOW_SUPPORT",
                "entry_below_support_atr": distance,
            }

        return {
            "state": "ENTRY",
            "confirm_time": close_time,
            "entry_idx": pos,
            "entry": entry,
            "entry_below_support_atr": distance,
            "confirm_high": h,
            "confirm_low": l,
            "confirm_close": c,
            "recent_1h_high": max(recent_highs[-6:]),
        }

    return {"state": "NO_1H_CONFIRMATION"}


def _major_4h_demand(four_closed, entry, atr):
    pivots = _pivot_lows(four_closed, int(V449_MAJOR_LOOKBACK_4H))
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
        enriched.append({**p, "departure_atr": departure})

    enriched.sort(key=lambda x: float(x["low"]))
    groups = []
    for p in enriched:
        if (
            groups
            and abs(float(p["low"]) - float(groups[-1][-1]["low"]))
            <= float(V449_MAJOR_CLUSTER_ATR) * atr
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
            >= int(V449_MAJOR_MIN_SEPARATION_BARS)
        )
        departure = max(float(p["departure_atr"]) for p in group)
        if not repeated and departure < float(V449_MAJOR_DEPARTURE_ATR):
            continue
        lower = min(float(p["low"]) for p in group)
        body_top = max(
            max(float(p["open"]), float(p["close"])) for p in group
        )
        upper = min(body_top, lower + float(V449_MAJOR_WIDTH_ATR) * atr)
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
            "departure_atr": departure,
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
    if 100.0 * risk / entry > float(V449_MAX_STOP_PCT):
        return "SKIP_STOP_PCT"
    if risk / atr > float(V449_MAX_RISK_ATR):
        return "SKIP_RISK_TOO_WIDE"
    cost_r = float(V441_COST_BPS) / 10000.0 * entry / risk
    if cost_r > float(V449_MAX_COST_R):
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


def _simulate(
    prefix,
    future15,
    start_idx,
    entry,
    stop,
    atr,
    runner_target,
    runner_room_r,
    seed,
):
    """50% at 2R, 25% at 4R, 25% runner."""
    out = dict(seed)
    risk = stop - entry
    cost_r = float(V441_COST_BPS) / 10000.0 * entry / risk
    entry_time = future15.index[start_idx]
    tp1 = entry - float(V449_TP1_R) * risk
    tp2 = entry - float(V449_TP2_R) * risk

    out.update({
        f"{prefix}_state": "INVALID_PLAN",
        f"{prefix}_entry_time": entry_time.isoformat(),
        f"{prefix}_entry": round(entry, 10),
        f"{prefix}_stop": round(stop, 10),
        f"{prefix}_risk_pct": round(100.0 * risk / entry, 4),
        f"{prefix}_risk_atr": round(risk / atr, 4),
        f"{prefix}_cost_r": round(cost_r, 5),
        f"{prefix}_tp1": round(tp1, 10),
        f"{prefix}_tp2": round(tp2, 10),
        f"{prefix}_tp1_hit": 0,
        f"{prefix}_tp1_time": None,
        f"{prefix}_tp2_hit": 0,
        f"{prefix}_tp2_time": None,
        f"{prefix}_runner_target": (
            round(float(runner_target), 10)
            if runner_target is not None
            else None
        ),
        f"{prefix}_runner_room_r": (
            round(float(runner_room_r), 4)
            if runner_room_r is not None
            else None
        ),
    })

    if float(future15.iloc[start_idx]["open"]) >= stop:
        out[f"{prefix}_state"] = "GAP_BEYOND_STOP"
        return out

    end_time = entry_time + pd.Timedelta(hours=int(V449_HOLD_HOURS))
    expected = entry_time
    bars = 0
    last_close = entry
    tp1_hit = False
    tp2_hit = False

    for i in range(start_idx, len(future15)):
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
            continue

        if not tp2_hit:
            if h >= entry:
                return _finish(
                    out, prefix, "BE_AFTER_TP1", 1.0, cost_r, bars, t + STEP
                )
            if l <= tp2:
                tp2_hit = True
                out[f"{prefix}_tp2_hit"] = 1
                out[f"{prefix}_tp2_time"] = (t + STEP).isoformat()
                if runner_target is not None and l <= runner_target:
                    gross = 2.0 + 0.25 * float(runner_room_r)
                    return _finish(
                        out, prefix, "RUNNER_MAJOR_4H_DEMAND",
                        gross, cost_r, bars, t + STEP
                    )
            continue

        # After 4R, protect the final 25% at the 2R price.
        if h >= tp1:
            return _finish(
                out, prefix, "PROTECT_AFTER_4R", 2.5, cost_r, bars, t + STEP
            )
        if runner_target is not None and l <= runner_target:
            gross = 2.0 + 0.25 * float(runner_room_r)
            return _finish(
                out, prefix, "RUNNER_MAJOR_4H_DEMAND",
                gross, cost_r, bars, t + STEP
            )

    current_r = (entry - last_close) / risk
    if tp2_hit:
        gross = 2.0 + 0.25 * current_r
    elif tp1_hit:
        gross = 1.0 + 0.5 * current_r
    else:
        gross = current_r
    return _finish(
        out,
        prefix,
        "TIME_EXIT",
        gross,
        cost_r,
        bars,
        min(end_time, expected),
    )


def evaluate_v449_m2(
    features,
    signal_time,
    hist4h,
    future4h,
    future1h,
    future15,
    one_all,
    four_all,
):
    prefix = "v449_m2"
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
        f"{prefix}_failed_reclaim_attempts": None,
        f"{prefix}_retest_attempts": None,
        f"{prefix}_pivot_high_count": None,
        f"{prefix}_flip_anchor_high": None,
        f"{prefix}_prior_flip_high": None,
        f"{prefix}_entry_selection_state": None,
        f"{prefix}_hard_thesis_invalidation": None,
        f"{prefix}_major_demand_source": None,
        f"{prefix}_major_demand_lower": None,
        f"{prefix}_major_demand_upper": None,
        f"{prefix}_major_demand_room_r": None,
        f"{prefix}_major_demand_obstacle": 0,
        f"{prefix}_runner_target": None,
        f"{prefix}_runner_room_r": None,
    })

    event = _find_break_event(features, hist4h, future4h, signal_time)
    if event is None:
        return out

    atr = float(event["atr"])
    hard_invalidation = (
        float(event["upper"]) + float(V449_RECLAIM_BUFFER_ATR) * atr
    )
    out.update({
        f"{prefix}_lifecycle": "BREAK_CONFIRMED",
        f"{prefix}_break_time": event["break_time"].isoformat(),
        f"{prefix}_break_body_atr": round(float(event["break_body_atr"]), 4),
        f"{prefix}_support_level": round(float(event["level"]), 10),
        f"{prefix}_support_lower": round(float(event["lower"]), 10),
        f"{prefix}_support_upper": round(float(event["upper"]), 10),
        f"{prefix}_support_touches": int(event["support"]["touches"]),
        f"{prefix}_hard_thesis_invalidation": round(hard_invalidation, 10),
    })

    watch = _watch_support_flip(event, future4h)
    out.update({
        f"{prefix}_watch_state": watch.get("state"),
        f"{prefix}_ready_reason": watch.get("ready_reason"),
        f"{prefix}_ready_time": (
            watch["ready_time"].isoformat()
            if watch.get("ready_time") is not None
            else None
        ),
        f"{prefix}_watch_hours": watch.get("watch_hours"),
        f"{prefix}_failed_reclaim_attempts": watch.get(
            "failed_reclaim_attempts"
        ),
        f"{prefix}_retest_attempts": watch.get("retest_attempts"),
        f"{prefix}_pivot_high_count": watch.get("pivot_high_count"),
        f"{prefix}_flip_anchor_high": watch.get("flip_anchor_high"),
        f"{prefix}_prior_flip_high": watch.get("prior_flip_high"),
    })
    if watch.get("state") != "CONFIRMED_SUPPORT_FLIP":
        out[f"{prefix}_lifecycle"] = watch.get("state") or "WATCH_ENDED"
        out[f"{prefix}_state"] = watch.get("state") or "WATCH_ENDED"
        return out

    out[f"{prefix}_lifecycle"] = "CONFIRMED_SUPPORT_FLIP"
    entry_plan = _find_1h_entry(watch, event, future1h, future15)
    out[f"{prefix}_entry_selection_state"] = entry_plan.get("state")
    if entry_plan.get("state") != "ENTRY":
        out[f"{prefix}_state"] = entry_plan.get("state") or "NO_ENTRY"
        return out

    entry = float(entry_plan["entry"])
    tactical_anchor = max(
        float(watch.get("flip_anchor_high") or entry),
        float(entry_plan.get("recent_1h_high") or entry),
        float(entry_plan.get("confirm_high") or entry),
    )
    raw_stop = tactical_anchor + float(V449_STOP_BUFFER_ATR) * atr
    if raw_stop >= hard_invalidation:
        raw_stop = hard_invalidation
    stop = max(raw_stop, entry + float(V449_MIN_RISK_ATR) * atr)
    if stop > hard_invalidation:
        out[f"{prefix}_state"] = "SKIP_MIN_RISK_EXCEEDS_THESIS"
        return out

    reason = _plan_reason(entry, stop, atr)
    if reason:
        out[f"{prefix}_state"] = reason
        return out

    risk = stop - entry
    entry_time = future15.index[int(entry_plan["entry_idx"])]
    four_ctx = _closed(four_all, entry_time, 4)
    demand = _major_4h_demand(four_ctx, entry, atr)

    major_target = None
    major_room_r = None
    if demand is not None:
        major_target = (
            float(demand["upper"])
            + float(V449_MAJOR_TARGET_BUFFER_ATR) * atr
        )
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
            f"{prefix}_major_demand_obstacle": int(
                major_room_r is not None
                and major_room_r < float(V449_TP2_R)
            ),
        })

    # Major demand is runner context only when it is beyond TP2.
    runner_target = (
        major_target
        if major_room_r is not None
        and major_room_r >= float(V449_TP2_R)
        else None
    )
    runner_room_r = (
        major_room_r if runner_target is not None else None
    )

    seed = dict(out)
    seed.update({
        f"{prefix}_state": "PLANNED",
        f"{prefix}_lifecycle": "ENTRY",
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
        runner_target,
        runner_room_r,
        seed,
    )
