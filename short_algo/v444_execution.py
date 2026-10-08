"""V4.4.4 Support Breakdown Continuation engine.

Core idea:
  repeated structural support -> pressure/compression into support -> breakdown
  -> acceptance below support or failed reclaim -> next-open short -> next demand.

Unlike V4.4.1 M2, the coin does NOT have to be classified as an existing
4H downtrend before the break. The breakdown itself may create the bearish
regime. All context and trigger fields are causal.
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
from .v444_config import (
    V444_BREAK_BODY_MAX_ATR,
    V444_BREAK_BODY_MIN_ATR,
    V444_BREAK_BUFFER_ATR,
    V444_COMPRESSION_BUFFER_ATR,
    V444_LOWER_HIGH_BUFFER_ATR,
    V444_MAX_COST_R,
    V444_MAX_ENTRY_BELOW_SUPPORT_ATR,
    V444_MAX_RISK_ATR,
    V444_MAX_STOP_PCT,
    V444_MIN_ACCEPTANCE_BARS,
    V444_MIN_CONFIRM_SCORE,
    V444_MIN_PRESSURE_SCORE,
    V444_MIN_RISK_ATR,
    V444_MIN_ROOM_R,
    V444_NEAR_SUPPORT_ATR,
    V444_PRESSURE_LOOKBACK_1H,
    V444_RECLAIM_INVALIDATION_ATR,
    V444_RETEST_TOLERANCE_ATR,
    V444_RETEST_WAIT_BARS,
    V444_STOP_BUFFER_ATR,
    V444_SUPPORT_MAX_DISTANCE_ATR,
    V444_TP1_R,
    V444_TRIGGER_WAIT_HOURS,
)


def _pressure_profile(one_closed, support_level, atr, features=None):
    """Signal-time pressure into support.

    The score is deliberately structure-based rather than trend-label based:
    lower recent highs, closes compressing toward support, proximity to support,
    short-term bearish alignment, and relative weakness.
    """
    features = features or {}
    if one_closed is None or len(one_closed) < int(V444_PRESSURE_LOOKBACK_1H):
        return {
            "score": 0,
            "lower_highs": 0,
            "close_compression": 0,
            "near_support": 0,
            "bearish_alignment": 0,
            "relative_weakness": 0,
            "recent_high_atr": None,
            "prior_high_atr": None,
            "recent_close_distance_atr": None,
            "prior_close_distance_atr": None,
        }

    view = one_closed.tail(int(V444_PRESSURE_LOOKBACK_1H)).copy()
    recent = view.tail(8)
    prior = view.iloc[-16:-8]
    if len(prior) < 6 or len(recent) < 6:
        return {"score": 0}

    recent_high = float(recent["high"].astype(float).max())
    prior_high = float(prior["high"].astype(float).max())
    last_close = float(view["close"].astype(float).iloc[-1])

    recent_dist = float(
        (recent["close"].astype(float) - float(support_level)).mean() / atr
    )
    prior_dist = float(
        (prior["close"].astype(float) - float(support_level)).mean() / atr
    )

    lower_highs = int(
        recent_high
        <= prior_high - float(V444_LOWER_HIGH_BUFFER_ATR) * atr
    )
    close_compression = int(
        recent_dist
        <= prior_dist - float(V444_COMPRESSION_BUFFER_ATR)
    )
    near_support = int(
        -0.20
        <= (last_close - float(support_level)) / atr
        <= float(V444_NEAR_SUPPORT_ATR)
    )

    mean8 = float(view["close"].astype(float).tail(8).mean())
    mean20 = float(view["close"].astype(float).tail(20).mean())
    bearish_closes = int(
        (recent["close"].astype(float) < recent["open"].astype(float)).sum()
    )
    bearish_alignment = int(
        last_close <= mean8
        and mean8 <= mean20 + 0.05 * atr
        and bearish_closes >= 3
    )
    relative_weakness = int(float(features.get("relative_4h_pct") or 0.0) < 0.0)

    score = sum(
        (
            lower_highs,
            close_compression,
            near_support,
            bearish_alignment,
            relative_weakness,
        )
    )
    return {
        "score": int(score),
        "lower_highs": lower_highs,
        "close_compression": close_compression,
        "near_support": near_support,
        "bearish_alignment": bearish_alignment,
        "relative_weakness": relative_weakness,
        "recent_high_atr": round((recent_high - support_level) / atr, 4),
        "prior_high_atr": round((prior_high - support_level) / atr, 4),
        "recent_close_distance_atr": round(recent_dist, 4),
        "prior_close_distance_atr": round(prior_dist, 4),
    }


def _plan_reason(entry, stop, atr):
    if any(x is None for x in (entry, stop, atr)):
        return "INVALID_PLAN"
    if entry <= 0 or stop <= entry or atr <= 0:
        return "INVALID_PLAN"
    risk = stop - entry
    if 100.0 * risk / entry > float(V444_MAX_STOP_PCT):
        return "SKIP_STOP_PCT"
    if risk / atr > float(V444_MAX_RISK_ATR):
        return "SKIP_RISK_TOO_WIDE"
    cost_r = float(V441_COST_BPS) / 10000.0 * entry / risk
    if cost_r > float(V444_MAX_COST_R):
        return "SKIP_COST_R"
    return None


def evaluate_v444_m2(features, hist15, future15, one_closed, four_closed):
    prefix = "v444_m2"
    result = _empty(prefix, "NO_M2_CONTEXT")

    atr = _num(features.get("atr_1h"))
    current = _num(features.get("current_price"))
    if atr is None or atr <= 0 or current is None:
        return _empty(prefix, "INVALID_CONTEXT")

    support = _structural_support(four_closed, current, atr)
    if support is None:
        result[f"{prefix}_state"] = "NO_STRUCTURAL_SUPPORT"
        return result

    distance_atr = (current - float(support["level"])) / atr
    if distance_atr > float(V444_SUPPORT_MAX_DISTANCE_ATR):
        result[f"{prefix}_state"] = "SUPPORT_TOO_FAR"
        return result

    pressure = _pressure_profile(
        one_closed,
        float(support["level"]),
        atr,
        features,
    )
    result.update({
        f"{prefix}_support_level": round(float(support["level"]), 10),
        f"{prefix}_support_lower": round(float(support["lower"]), 10),
        f"{prefix}_support_upper": round(float(support["upper"]), 10),
        f"{prefix}_support_touches": int(support["touches"]),
        f"{prefix}_support_distance_atr": round(distance_atr, 4),
        f"{prefix}_pressure_score": int(pressure.get("score") or 0),
        f"{prefix}_lower_highs": int(pressure.get("lower_highs") or 0),
        f"{prefix}_close_compression": int(pressure.get("close_compression") or 0),
        f"{prefix}_near_support": int(pressure.get("near_support") or 0),
        f"{prefix}_bearish_alignment": int(pressure.get("bearish_alignment") or 0),
        f"{prefix}_relative_weakness": int(pressure.get("relative_weakness") or 0),
        f"{prefix}_recent_high_atr": pressure.get("recent_high_atr"),
        f"{prefix}_prior_high_atr": pressure.get("prior_high_atr"),
        f"{prefix}_recent_close_distance_atr": pressure.get("recent_close_distance_atr"),
        f"{prefix}_prior_close_distance_atr": pressure.get("prior_close_distance_atr"),
    })

    if int(pressure.get("score") or 0) < int(V444_MIN_PRESSURE_SCORE):
        result[f"{prefix}_state"] = "NO_SUPPORT_PRESSURE"
        return result

    result[f"{prefix}_context_ok"] = 1
    if hist15 is None or future15 is None or len(future15) < 2:
        result[f"{prefix}_state"] = "NO_15M_CONTEXT"
        return result

    future15 = future15.sort_index()
    deadline = future15.index[0] + pd.Timedelta(hours=int(V444_TRIGGER_WAIT_HOURS))
    level = float(support["level"])
    break_seed = None
    last_reason = "NO_BREAKDOWN"

    for i in range(0, len(future15) - 1):
        t = future15.index[i]
        if t >= deadline:
            break
        bar = future15.iloc[i]
        prev = future15.iloc[i - 1] if i > 0 else None
        o, h, l, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
        if not all(math.isfinite(x) for x in (o, h, l, c)):
            continue

        if break_seed is None:
            bearish_break = bool(
                c < level - float(V444_BREAK_BUFFER_ATR) * atr
                and c < o
            )
            if bearish_break:
                body_atr = (o - c) / atr
                break_seed = {
                    "break_i": i,
                    "break_time": t,
                    "body_atr": body_atr,
                    "controlled": int(
                        float(V444_BREAK_BODY_MIN_ATR)
                        <= body_atr
                        <= float(V444_BREAK_BODY_MAX_ATR)
                    ),
                    "acceptance": 1,
                    "retest_high": level,
                }
                last_reason = "NO_FAILED_RECLAIM"
            continue

        bars_after = i - int(break_seed["break_i"])
        if c > level + float(V444_RECLAIM_INVALIDATION_ATR) * atr:
            break_seed = None
            last_reason = "BREAKDOWN_INVALIDATED"
            continue
        if bars_after > int(V444_RETEST_WAIT_BARS):
            break_seed = None
            last_reason = "NO_FAILED_RECLAIM"
            continue

        if c < level:
            break_seed["acceptance"] = int(break_seed.get("acceptance", 0)) + 1

        touched = h >= level - float(V444_RETEST_TOLERANCE_ATR) * atr
        if touched:
            break_seed["retest_high"] = max(
                float(break_seed.get("retest_high") or level),
                h,
            )

        rng = max(h - l, 1e-12)
        bearish_rejection = bool(
            touched
            and c < level
            and c < o
            and (
                (c - l) / rng <= 0.55
                or (prev is not None and c < float(prev["close"]))
            )
        )
        acceptance = int(break_seed.get("acceptance", 0)) >= int(
            V444_MIN_ACCEPTANCE_BARS
        )
        pressure_strong = int(pressure.get("score") or 0) >= 3

        confirm_score = sum(
            (
                bool(break_seed["controlled"]),
                bool(touched),
                bool(bearish_rejection),
                bool(acceptance),
                bool(pressure_strong),
            )
        )
        confirmed = bool(
            c < level
            and confirm_score >= int(V444_MIN_CONFIRM_SCORE)
            and (bearish_rejection or acceptance)
        )
        if not confirmed:
            continue

        if not _next_bar(future15, i):
            result[f"{prefix}_state"] = "NO_NEXT_OPEN"
            return result

        entry = float(future15.iloc[i + 1]["open"])
        entry_below_atr = max(0.0, (level - entry) / atr)
        if entry_below_atr > float(V444_MAX_ENTRY_BELOW_SUPPORT_ATR):
            break_seed = None
            last_reason = "SKIP_CHASE"
            continue

        stop = max(
            float(break_seed.get("retest_high") or level)
            + float(V444_STOP_BUFFER_ATR) * atr,
            level + float(V444_STOP_BUFFER_ATR) * atr,
            entry + float(V444_MIN_RISK_ATR) * atr,
        )
        reason = _plan_reason(entry, stop, atr)
        if reason:
            break_seed = None
            last_reason = reason
            continue

        demand = _next_demand_below(
            one_closed,
            four_closed,
            entry,
            atr,
            level,
        )
        if demand is None:
            break_seed = None
            last_reason = "NO_NEXT_DEMAND"
            continue

        risk = stop - entry
        target = float(demand["upper"]) + 0.10 * atr
        room_r = (entry - target) / risk
        if target <= 0 or room_r < float(V444_MIN_ROOM_R):
            break_seed = None
            last_reason = "SKIP_ROOM_TO_DEMAND"
            continue

        tp1 = entry - float(V444_TP1_R) * risk
        seed = _empty(prefix, "PLANNED")
        seed.update({
            f"{prefix}_context_ok": 1,
            f"{prefix}_support_level": round(level, 10),
            f"{prefix}_support_lower": round(float(support["lower"]), 10),
            f"{prefix}_support_upper": round(float(support["upper"]), 10),
            f"{prefix}_support_touches": int(support["touches"]),
            f"{prefix}_support_distance_atr": round(distance_atr, 4),
            f"{prefix}_pressure_score": int(pressure.get("score") or 0),
            f"{prefix}_lower_highs": int(pressure.get("lower_highs") or 0),
            f"{prefix}_close_compression": int(pressure.get("close_compression") or 0),
            f"{prefix}_near_support": int(pressure.get("near_support") or 0),
            f"{prefix}_bearish_alignment": int(pressure.get("bearish_alignment") or 0),
            f"{prefix}_relative_weakness": int(pressure.get("relative_weakness") or 0),
            f"{prefix}_break_time": break_seed["break_time"].isoformat(),
            f"{prefix}_break_body_atr": round(float(break_seed["body_atr"]), 4),
            f"{prefix}_controlled_break": int(break_seed["controlled"]),
            f"{prefix}_confirm_score": int(confirm_score),
            f"{prefix}_retest_touched": int(touched),
            f"{prefix}_retest_rejection": int(bearish_rejection),
            f"{prefix}_acceptance_bars": int(break_seed.get("acceptance", 0)),
            f"{prefix}_confirm_time": t.isoformat(),
            f"{prefix}_entry_below_support_atr": round(entry_below_atr, 4),
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
            i + 1,
            entry,
            stop,
            atr,
            tp1,
            target,
            room_r,
            level,
            seed,
        )

    result[f"{prefix}_state"] = last_reason
    return result
