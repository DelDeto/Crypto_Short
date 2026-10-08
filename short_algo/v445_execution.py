"""V4.4.5 execution lab.

M1:
- detector/outcome from V4.4/V4.4.1 stays untouched;
- E1 waits for a causal 50% confirmation-candle retest/rejection (max 2h);
- E2 waits for a deeper 65% retest/rejection (max 4h);
- fills remain next-15m-open only.

M2:
- detects an important structural-support break as an event;
- records the following 24h path for research diagnostics only;
- separately simulates three causal entries that never read those 24h labels:
  A = 3 consecutive closes accepted below support;
  B = A + next-open near broken support (<=0.20 ATR);
  C = A + failed-reclaim retest/rejection.

No "best price in hindsight" is used as a trade entry.
"""
import math

import pandas as pd

from .v441_config import V441_COST_BPS
from .v441_execution import (
    _empty,
    _next_bar,
    _next_demand_below,
    _num,
    _simulate_staged,
    _structural_support,
)
from .v444_execution import _pressure_profile
from .v445_config import (
    V445_M1_E1_RETRACE,
    V445_M1_E1_WAIT_BARS,
    V445_M1_E2_RETRACE,
    V445_M1_E2_WAIT_BARS,
    V445_M1_MAX_COST_R,
    V445_M1_MAX_RISK_ATR,
    V445_M1_MAX_STOP_PCT,
    V445_M1_MIN_RISK_ATR,
    V445_M1_MIN_ROOM_R,
    V445_M1_STOP_BUFFER_ATR,
    V445_M1_TP1_R,
    V445_M2_ACCEPTANCE_CLOSES,
    V445_M2_BREAK_BUFFER_ATR,
    V445_M2_EVENT_HOURS,
    V445_M2_HARD_RECLAIM_ATR,
    V445_M2_MAX_CHASE_ATR,
    V445_M2_MAX_COST_R,
    V445_M2_MAX_RISK_ATR,
    V445_M2_MAX_STOP_PCT,
    V445_M2_MIN_RISK_ATR,
    V445_M2_MIN_ROOM_R,
    V445_M2_NEAR_ENTRY_ATR,
    V445_M2_RETEST_TOLERANCE_ATR,
    V445_M2_STOP_BUFFER_ATR,
    V445_M2_TP1_R,
    V445_M2_TRIGGER_WAIT_HOURS,
)

STEP = pd.Timedelta(minutes=15)


def _plan_reason(entry, stop, atr, max_risk_atr, max_stop_pct, max_cost_r):
    if any(x is None for x in (entry, stop, atr)):
        return "INVALID_PLAN"
    if entry <= 0 or stop <= entry or atr <= 0:
        return "INVALID_PLAN"
    risk = stop - entry
    if 100.0 * risk / entry > float(max_stop_pct):
        return "SKIP_STOP_PCT"
    if risk / atr > float(max_risk_atr):
        return "SKIP_RISK_TOO_WIDE"
    cost_r = float(V441_COST_BPS) / 10000.0 * entry / risk
    if cost_r > float(max_cost_r):
        return "SKIP_COST_R"
    return None


def _find_index(frame, time_value):
    if frame is None or frame.empty or not time_value:
        return None
    try:
        t = pd.Timestamp(time_value)
    except Exception:
        return None
    if t.tzinfo is None and frame.index.tz is not None:
        t = t.tz_localize(frame.index.tz)
    try:
        loc = frame.index.get_loc(t)
    except KeyError:
        return None
    if isinstance(loc, slice):
        return int(loc.start)
    if hasattr(loc, "__len__") and not isinstance(loc, (int,)):
        positions = [i for i, x in enumerate(loc) if x]
        return positions[0] if positions else None
    return int(loc)


def _m1_variant(
    prefix,
    future15,
    confirm_time,
    base_stop,
    demand_target,
    base_entry,
    atr,
    retrace_fraction,
    wait_bars,
):
    out = _empty(prefix, "NO_BASE_SETUP")
    out.update({
        f"{prefix}_variant": None,
        f"{prefix}_base_entry": base_entry,
        f"{prefix}_confirm_time": confirm_time,
        f"{prefix}_retest_time": None,
        f"{prefix}_retest_level": None,
        f"{prefix}_demand_target": demand_target,
    })
    if (
        future15 is None
        or future15.empty
        or _num(atr) is None
        or _num(base_stop) is None
        or _num(demand_target) is None
        or not confirm_time
    ):
        return out

    frame = future15.sort_index()
    confirm_idx = _find_index(frame, confirm_time)
    if confirm_idx is None or confirm_idx >= len(frame) - 2:
        out[f"{prefix}_state"] = "NO_CONFIRM_BAR"
        return out

    confirm = frame.iloc[confirm_idx]
    ch = float(confirm["high"])
    cl = float(confirm["low"])
    if not (math.isfinite(ch) and math.isfinite(cl) and ch > cl):
        out[f"{prefix}_state"] = "BAD_CONFIRM_BAR"
        return out

    retrace_level = cl + float(retrace_fraction) * (ch - cl)
    out[f"{prefix}_retest_level"] = round(retrace_level, 10)
    end = min(len(frame) - 1, confirm_idx + int(wait_bars) + 1)

    for j in range(confirm_idx + 1, end):
        bar = frame.iloc[j]
        o, h, l, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
        if not all(math.isfinite(x) for x in (o, h, l, c)):
            continue
        # Retest has happened, but entry waits for this rejection bar to close.
        rejection = bool(h >= retrace_level and c < retrace_level and c < o)
        if not rejection:
            continue
        if not _next_bar(frame, j):
            out[f"{prefix}_state"] = "NO_NEXT_OPEN"
            return out

        entry = float(frame.iloc[j + 1]["open"])
        # Hold the original structural stop fixed so this experiment isolates
        # entry timing instead of quietly optimizing entry and stop together.
        stop = float(base_stop)
        reason = _plan_reason(
            entry,
            stop,
            atr,
            V445_M1_MAX_RISK_ATR,
            V445_M1_MAX_STOP_PCT,
            V445_M1_MAX_COST_R,
        )
        if reason:
            out[f"{prefix}_state"] = reason
            return out

        risk = stop - entry
        target = float(demand_target)
        room_r = (entry - target) / risk
        if target <= 0 or target >= entry or room_r < float(V445_M1_MIN_ROOM_R):
            out[f"{prefix}_state"] = "SKIP_ROOM_TO_DEMAND"
            return out

        tp1 = entry - float(V445_M1_TP1_R) * risk
        seed = _empty(prefix, "PLANNED")
        seed.update({
            f"{prefix}_context_ok": 1,
            f"{prefix}_variant": (
                "RETEST_50_2H"
                if abs(float(retrace_fraction) - 0.50) < 1e-9
                else "DEEP_RETEST_65_4H"
            ),
            f"{prefix}_base_entry": base_entry,
            f"{prefix}_confirm_time": confirm_time,
            f"{prefix}_retest_time": frame.index[j].isoformat(),
            f"{prefix}_retest_level": round(retrace_level, 10),
            f"{prefix}_demand_target": round(target, 10),
            f"{prefix}_room_r": round(room_r, 4),
            f"{prefix}_room_pass": 1,
        })
        return _simulate_staged(
            prefix,
            frame,
            j + 1,
            entry,
            stop,
            atr,
            tp1,
            target,
            room_r,
            retrace_level,
            seed,
        )

    out[f"{prefix}_state"] = "NO_RETEST_FILL"
    return out


def evaluate_m1_entry_lab(future15, strict, scored, atr):
    """Alternative entries on the same causal M1 setups already found by E0."""
    out = {}

    a_ok = _num(strict.get("v440_net_r")) is not None
    for prefix, retrace, wait in (
        ("v445_m1a_e1", V445_M1_E1_RETRACE, V445_M1_E1_WAIT_BARS),
        ("v445_m1a_e2", V445_M1_E2_RETRACE, V445_M1_E2_WAIT_BARS),
    ):
        if a_ok:
            out.update(_m1_variant(
                prefix,
                future15,
                strict.get("v440_bos_time"),
                strict.get("v440_stop"),
                strict.get("v440_demand_target"),
                strict.get("v440_entry"),
                atr,
                retrace,
                wait,
            ))
        else:
            out.update(_empty(prefix, "NO_BASE_SETUP"))

    b_ok = _num(scored.get("v441_m1_net_r")) is not None
    for prefix, retrace, wait in (
        ("v445_m1b_e1", V445_M1_E1_RETRACE, V445_M1_E1_WAIT_BARS),
        ("v445_m1b_e2", V445_M1_E2_RETRACE, V445_M1_E2_WAIT_BARS),
    ):
        if b_ok:
            out.update(_m1_variant(
                prefix,
                future15,
                scored.get("v441_m1_confirm_time"),
                scored.get("v441_m1_stop"),
                scored.get("v441_m1_demand_target"),
                scored.get("v441_m1_entry"),
                atr,
                retrace,
                wait,
            ))
        else:
            out.update(_empty(prefix, "NO_BASE_SETUP"))

    return out


def _empty_m2_event():
    return {
        "v445_m2_event_found": 0,
        "v445_m2_event_break_time": None,
        "v445_m2_event_support": None,
        "v445_m2_event_support_touches": None,
        "v445_m2_event_pressure_score": None,
        "v445_m2_event_break_body_atr": None,
        "v445_m2_event_24h_max_reclaim_atr": None,
        "v445_m2_event_24h_max_extension_atr": None,
        "v445_m2_event_24h_closes_below": None,
        "v445_m2_event_24h_max_consecutive_below": None,
        "v445_m2_event_24h_first_retest_bars": None,
        "v445_m2_event_24h_first_reclaim_bars": None,
        "v445_m2_event_24h_first_1atr_extension_bars": None,
        "v445_m2_event_24h_end_close_below_atr": None,
    }


def _detect_m2_break(features, future15, one_closed, four_closed):
    atr = _num(features.get("atr_1h"))
    current = _num(features.get("current_price"))
    if atr is None or atr <= 0 or current is None or future15 is None or future15.empty:
        return None

    support = _structural_support(four_closed, current, atr)
    if support is None:
        return None
    level = float(support["level"])
    pressure = _pressure_profile(one_closed, level, atr, features)

    frame = future15.sort_index()
    deadline = frame.index[0] + pd.Timedelta(hours=int(V445_M2_TRIGGER_WAIT_HOURS))
    for i in range(0, len(frame)):
        t = frame.index[i]
        if t >= deadline:
            break
        bar = frame.iloc[i]
        o, h, l, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
        if not all(math.isfinite(x) for x in (o, h, l, c)):
            continue
        if c < level - float(V445_M2_BREAK_BUFFER_ATR) * atr and c < o:
            return {
                "frame": frame,
                "break_idx": i,
                "break_time": t,
                "support": support,
                "level": level,
                "atr": atr,
                "pressure": pressure,
                "break_body_atr": (o - c) / atr,
            }
    return None


def _study_24h(event):
    frame = event["frame"]
    i0 = int(event["break_idx"])
    level = float(event["level"])
    atr = float(event["atr"])
    start = frame.index[i0]
    end_time = start + pd.Timedelta(hours=int(V445_M2_EVENT_HOURS))
    view = frame.iloc[i0:].loc[frame.index[i0:] < end_time]
    if view.empty:
        return {}

    highs = view["high"].astype(float)
    lows = view["low"].astype(float)
    closes = view["close"].astype(float)

    max_consecutive = 0
    consecutive = 0
    first_retest = None
    first_reclaim = None
    first_1atr = None

    for k, (_, row) in enumerate(view.iterrows()):
        c = float(row["close"])
        h = float(row["high"])
        l = float(row["low"])
        if c < level:
            consecutive += 1
            max_consecutive = max(max_consecutive, consecutive)
        else:
            consecutive = 0
        if k > 0 and first_retest is None and h >= level - float(V445_M2_RETEST_TOLERANCE_ATR) * atr:
            first_retest = k
        if first_reclaim is None and c > level + 0.05 * atr:
            first_reclaim = k
        if first_1atr is None and l <= level - 1.0 * atr:
            first_1atr = k

    return {
        "v445_m2_event_24h_max_reclaim_atr": round((float(highs.max()) - level) / atr, 4),
        "v445_m2_event_24h_max_extension_atr": round((level - float(lows.min())) / atr, 4),
        "v445_m2_event_24h_closes_below": int((closes < level).sum()),
        "v445_m2_event_24h_max_consecutive_below": int(max_consecutive),
        "v445_m2_event_24h_first_retest_bars": first_retest,
        "v445_m2_event_24h_first_reclaim_bars": first_reclaim,
        "v445_m2_event_24h_first_1atr_extension_bars": first_1atr,
        "v445_m2_event_24h_end_close_below_atr": round((level - float(closes.iloc[-1])) / atr, 4),
    }


def _select_m2_entry(frame, break_idx, level, atr, mode):
    """Return the first entry allowed by a fixed causal rule."""
    break_time = frame.index[int(break_idx)]
    end_time = break_time + pd.Timedelta(hours=int(V445_M2_EVENT_HOURS))
    consecutive = 0
    accepted = False
    retest_high = level

    for j in range(int(break_idx), len(frame) - 1):
        t = frame.index[j]
        if t >= end_time:
            break
        bar = frame.iloc[j]
        prev = frame.iloc[j - 1] if j > int(break_idx) else None
        o, h, l, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
        if not all(math.isfinite(x) for x in (o, h, l, c)):
            continue

        if j > int(break_idx):
            retest_high = max(retest_high, h)

        if c > level + float(V445_M2_HARD_RECLAIM_ATR) * atr:
            return None

        if c < level:
            consecutive += 1
        else:
            consecutive = 0

        if consecutive >= int(V445_M2_ACCEPTANCE_CLOSES):
            accepted = True

        if not accepted or not _next_bar(frame, j):
            continue

        next_open = float(frame.iloc[j + 1]["open"])
        below_atr = max(0.0, (level - next_open) / atr)

        if mode == "ACCEPT3":
            if below_atr <= float(V445_M2_MAX_CHASE_ATR):
                return {
                    "trigger_idx": j,
                    "entry_idx": j + 1,
                    "acceptance_closes": consecutive,
                    "retest_high": retest_high,
                    "entry_below_support_atr": below_atr,
                    "reason": "3_CONSECUTIVE_CLOSES_BELOW",
                }

        elif mode == "ACCEPT3_NEAR":
            if c < level and below_atr <= float(V445_M2_NEAR_ENTRY_ATR):
                return {
                    "trigger_idx": j,
                    "entry_idx": j + 1,
                    "acceptance_closes": consecutive,
                    "retest_high": retest_high,
                    "entry_below_support_atr": below_atr,
                    "reason": "ACCEPT3_NEXT_OPEN_NEAR_SUPPORT",
                }

        elif mode == "ACCEPT3_RETEST":
            rng = max(h - l, 1e-12)
            touched = h >= level - float(V445_M2_RETEST_TOLERANCE_ATR) * atr
            rejection = bool(
                touched
                and c < level
                and c < o
                and (
                    (c - l) / rng <= 0.55
                    or (prev is not None and c < float(prev["close"]))
                )
            )
            if rejection and below_atr <= float(V445_M2_MAX_CHASE_ATR):
                return {
                    "trigger_idx": j,
                    "entry_idx": j + 1,
                    "acceptance_closes": consecutive,
                    "retest_high": max(retest_high, h),
                    "entry_below_support_atr": below_atr,
                    "reason": "ACCEPT3_FAILED_RECLAIM",
                }

    return None


def _m2_variant(prefix, event, one_closed, four_closed, mode):
    out = _empty(prefix, "NO_ENTRY")
    out.update({
        f"{prefix}_mode": mode,
        f"{prefix}_break_time": event["break_time"].isoformat(),
        f"{prefix}_support_level": round(float(event["level"]), 10),
        f"{prefix}_acceptance_closes": None,
        f"{prefix}_entry_below_support_atr": None,
        f"{prefix}_trigger_reason": None,
    })

    frame = event["frame"]
    atr = float(event["atr"])
    level = float(event["level"])
    selection = _select_m2_entry(
        frame,
        event["break_idx"],
        level,
        atr,
        mode,
    )
    if selection is None:
        out[f"{prefix}_state"] = "NO_CAUSAL_ENTRY"
        return out

    entry_idx = int(selection["entry_idx"])
    entry = float(frame.iloc[entry_idx]["open"])
    stop = max(
        float(selection["retest_high"]) + float(V445_M2_STOP_BUFFER_ATR) * atr,
        level + float(V445_M2_STOP_BUFFER_ATR) * atr,
        entry + float(V445_M2_MIN_RISK_ATR) * atr,
    )
    reason = _plan_reason(
        entry,
        stop,
        atr,
        V445_M2_MAX_RISK_ATR,
        V445_M2_MAX_STOP_PCT,
        V445_M2_MAX_COST_R,
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
    if target <= 0 or target >= entry or room_r < float(V445_M2_MIN_ROOM_R):
        out[f"{prefix}_state"] = "SKIP_ROOM_TO_DEMAND"
        return out

    tp1 = entry - float(V445_M2_TP1_R) * risk
    seed = _empty(prefix, "PLANNED")
    seed.update({
        f"{prefix}_context_ok": 1,
        f"{prefix}_mode": mode,
        f"{prefix}_break_time": event["break_time"].isoformat(),
        f"{prefix}_support_level": round(level, 10),
        f"{prefix}_support_touches": int(event["support"]["touches"]),
        f"{prefix}_pressure_score": int(event["pressure"].get("score") or 0),
        f"{prefix}_acceptance_closes": int(selection["acceptance_closes"]),
        f"{prefix}_entry_below_support_atr": round(float(selection["entry_below_support_atr"]), 4),
        f"{prefix}_trigger_time": frame.index[int(selection["trigger_idx"])].isoformat(),
        f"{prefix}_trigger_reason": selection["reason"],
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


def evaluate_m2_24h_lab(features, future15, one_closed, four_closed):
    out = _empty_m2_event()
    for prefix in ("v445_m2_a", "v445_m2_b", "v445_m2_c"):
        out.update(_empty(prefix, "NO_BREAK_EVENT"))

    event = _detect_m2_break(
        features,
        future15,
        one_closed,
        four_closed,
    )
    if event is None:
        return out

    out.update({
        "v445_m2_event_found": 1,
        "v445_m2_event_break_time": event["break_time"].isoformat(),
        "v445_m2_event_support": round(float(event["level"]), 10),
        "v445_m2_event_support_touches": int(event["support"]["touches"]),
        "v445_m2_event_pressure_score": int(event["pressure"].get("score") or 0),
        "v445_m2_event_break_body_atr": round(float(event["break_body_atr"]), 4),
    })
    out.update(_study_24h(event))

    out.update(_m2_variant(
        "v445_m2_a",
        event,
        one_closed,
        four_closed,
        "ACCEPT3",
    ))
    out.update(_m2_variant(
        "v445_m2_b",
        event,
        one_closed,
        four_closed,
        "ACCEPT3_NEAR",
    ))
    out.update(_m2_variant(
        "v445_m2_c",
        event,
        one_closed,
        four_closed,
        "ACCEPT3_RETEST",
    ))
    return out
