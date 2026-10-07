"""V4.4.1 dual-model causal execution engine.

M1 LIQUIDITY_REVERSAL
  strong supply + repeated buy-side liquidity -> sweep -> scored confirmation
  -> next-open short -> demand room hard gate -> causal follow-through management.

M2 SUPPORT_BREAKDOWN_CONTINUATION (SBC / EDGE-like)
  bearish 4H pressure + repeatedly defended structural support -> controlled
  break -> failed reclaim/retest -> next-open short -> next demand target.

Every decision uses candles already closed at decision time. No future best-price
selection, no parameter search inside the replay, no re-entry/martingale.
"""
import math

import pandas as pd

from .v441_config import (
    V441_COST_BPS,
    V441_DEMAND_TARGET_BUFFER_ATR,
    V441_FT_MIN_MFE_R,
    V441_FT_RECLAIM_BUFFER_ATR,
    V441_FT_WINDOW_BARS,
    V441_HOLD_HOURS,
    V441_M1_BODY_MAX_ATR,
    V441_M1_BODY_MIN_ATR,
    V441_M1_BOS_LOOKBACK_BARS,
    V441_M1_BREAK_BUFFER_ATR,
    V441_M1_CLOSE_TOLERANCE_ATR,
    V441_M1_CONFIRM_WAIT_BARS,
    V441_M1_LIQ_CLUSTER_ATR,
    V441_M1_LIQ_LOOKBACK_BARS,
    V441_M1_LIQ_MIN_SEPARATION_BARS,
    V441_M1_LIQ_MIN_TOUCHES,
    V441_M1_LIQ_ZONE_ABOVE_ATR,
    V441_M1_LIQ_ZONE_BELOW_ATR,
    V441_M1_MIN_CONFIRM_SCORE,
    V441_M1_MIN_REJECTION_WICK_RATIO,
    V441_M1_NO_CHASE_ATR,
    V441_M1_SWEEP_BUFFER_ATR,
    V441_M1_TRIGGER_WAIT_HOURS,
    V441_M2_BREAK_BODY_MAX_ATR,
    V441_M2_BREAK_BODY_MIN_ATR,
    V441_M2_BREAK_BUFFER_ATR,
    V441_M2_MAX_DISTANCE_ATR,
    V441_M2_MAX_PREBROKEN_ATR,
    V441_M2_MIN_CONFIRM_SCORE,
    V441_M2_NEXT_DEMAND_GAP_ATR,
    V441_M2_NO_CHASE_ATR,
    V441_M2_RECLAIM_INVALIDATION_ATR,
    V441_M2_RETEST_TOLERANCE_ATR,
    V441_M2_RETEST_WAIT_BARS,
    V441_M2_SUPPORT_CLUSTER_ATR,
    V441_M2_SUPPORT_LOOKBACK_4H,
    V441_M2_SUPPORT_MIN_SEPARATION_BARS,
    V441_M2_SUPPORT_MIN_TOUCHES,
    V441_M2_TRIGGER_WAIT_HOURS,
    V441_MAX_COST_R,
    V441_MAX_RISK_ATR,
    V441_MAX_STOP_PCT,
    V441_MIN_RISK_ATR,
    V441_MIN_ROOM_R,
    V441_STOP_BUFFER_ATR,
    V441_TP1_R,
)
from .v440_execution import _nearest_demand

STEP = pd.Timedelta(minutes=15)
TERMINAL_STATES = {
    "SL_FIRST",
    "TP2_DEMAND",
    "TP1_THEN_BE",
    "TP1_TIME_EXIT",
    "TIME_EXIT",
    "FT_EXIT",
    "FT_RECLAIM_EXIT",
}


def _num(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _next_bar(frame, i):
    return (
        i + 1 < len(frame)
        and frame.index[i + 1] == frame.index[i] + STEP
    )


def _empty(prefix, state):
    return {
        f"{prefix}_state": state,
        f"{prefix}_context_ok": 0,
        f"{prefix}_confirm_score": None,
        f"{prefix}_entry_time": None,
        f"{prefix}_entry": None,
        f"{prefix}_stop": None,
        f"{prefix}_risk_pct": None,
        f"{prefix}_risk_atr": None,
        f"{prefix}_cost_r": None,
        f"{prefix}_demand_source": None,
        f"{prefix}_demand_lower": None,
        f"{prefix}_demand_upper": None,
        f"{prefix}_demand_target": None,
        f"{prefix}_room_r": None,
        f"{prefix}_room_pass": 0,
        f"{prefix}_tp1": None,
        f"{prefix}_tp2": None,
        f"{prefix}_tp1_hit": 0,
        f"{prefix}_tp1_time": None,
        f"{prefix}_ft_state": None,
        f"{prefix}_ft_pass": 0,
        f"{prefix}_ft_mfe_r": None,
        f"{prefix}_gross_r": None,
        f"{prefix}_net_r": None,
        f"{prefix}_hold_bars": None,
        f"{prefix}_exit_time": None,
    }


def _plan_reason(entry, stop, atr):
    if any(x is None for x in (entry, stop, atr)):
        return "INVALID_PLAN"
    if entry <= 0 or stop <= entry or atr <= 0:
        return "INVALID_PLAN"
    risk = stop - entry
    if 100.0 * risk / entry > float(V441_MAX_STOP_PCT):
        return "SKIP_STOP_PCT"
    if risk / atr > float(V441_MAX_RISK_ATR):
        return "SKIP_RISK_TOO_WIDE"
    cost_r = float(V441_COST_BPS) / 10000.0 * entry / risk
    if cost_r > float(V441_MAX_COST_R):
        return "SKIP_COST_R"
    return None


def _simulate_staged(
    prefix,
    future15,
    start_idx,
    entry,
    stop,
    atr,
    tp1,
    tp2,
    room_r,
    reclaim_level,
    seed,
):
    out = dict(seed)
    risk = stop - entry
    cost_r = float(V441_COST_BPS) / 10000.0 * entry / risk
    entry_time = future15.index[start_idx]
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
    })
    if float(future15.iloc[start_idx]["open"]) >= stop:
        out[f"{prefix}_state"] = "GAP_BEYOND_STOP"
        return out

    end_time = entry_time + pd.Timedelta(hours=int(V441_HOLD_HOURS))
    expected = entry_time
    bars = 0
    last_close = None
    tp1_hit = False
    tp1_index = None
    ft_pass = False
    best_low = entry

    for i in range(start_idx, len(future15)):
        t = future15.index[i]
        if t >= end_time:
            break
        if t != expected:
            out[f"{prefix}_state"] = "CENSORED_15M_GAP"
            return out
        bar = future15.iloc[i]
        o, h, l, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
        if not all(math.isfinite(x) for x in (o, h, l, c)):
            out[f"{prefix}_state"] = "CENSORED_BAD_BAR"
            return out

        expected += STEP
        bars += 1
        last_close = c
        best_low = min(best_low, l)
        mfe_r = max(0.0, (entry - best_low) / risk)
        out[f"{prefix}_ft_mfe_r"] = round(mfe_r, 4)

        if not tp1_hit and h >= stop:
            gross = (entry - max(o, stop)) / risk
            out.update({
                f"{prefix}_state": "SL_FIRST",
                f"{prefix}_gross_r": round(gross, 5),
                f"{prefix}_net_r": round(gross - cost_r, 5),
                f"{prefix}_hold_bars": bars,
                f"{prefix}_exit_time": (t + STEP).isoformat(),
                f"{prefix}_ft_state": (
                    "STOP_BEFORE_FOLLOWTHROUGH" if not ft_pass else "PASS"
                ),
                f"{prefix}_ft_pass": int(ft_pass),
            })
            return out

        if not ft_pass and mfe_r >= float(V441_FT_MIN_MFE_R):
            ft_pass = True
            out[f"{prefix}_ft_state"] = "PASS"
            out[f"{prefix}_ft_pass"] = 1

        if not tp1_hit:
            if (
                not ft_pass
                and bars <= int(V441_FT_WINDOW_BARS)
                and c > float(reclaim_level) + float(V441_FT_RECLAIM_BUFFER_ATR) * atr
            ):
                gross = (entry - c) / risk
                out.update({
                    f"{prefix}_state": "FT_RECLAIM_EXIT",
                    f"{prefix}_ft_state": "FAIL_RECLAIM",
                    f"{prefix}_ft_pass": 0,
                    f"{prefix}_gross_r": round(gross, 5),
                    f"{prefix}_net_r": round(gross - cost_r, 5),
                    f"{prefix}_hold_bars": bars,
                    f"{prefix}_exit_time": (t + STEP).isoformat(),
                })
                return out

            if l <= tp1:
                tp1_hit = True
                tp1_index = i
                ft_pass = True
                out.update({
                    f"{prefix}_tp1_hit": 1,
                    f"{prefix}_tp1_time": (t + STEP).isoformat(),
                    f"{prefix}_ft_state": "PASS",
                    f"{prefix}_ft_pass": 1,
                })
                if l <= tp2:
                    gross = 1.0 + 0.5 * float(room_r)
                    out.update({
                        f"{prefix}_state": "TP2_DEMAND",
                        f"{prefix}_gross_r": round(gross, 5),
                        f"{prefix}_net_r": round(gross - cost_r, 5),
                        f"{prefix}_hold_bars": bars,
                        f"{prefix}_exit_time": (t + STEP).isoformat(),
                    })
                    return out

            if (
                not tp1_hit
                and not ft_pass
                and bars >= int(V441_FT_WINDOW_BARS)
            ):
                gross = (entry - c) / risk
                out.update({
                    f"{prefix}_state": "FT_EXIT",
                    f"{prefix}_ft_state": "FAIL_NO_IMMEDIATE_FOLLOWTHROUGH",
                    f"{prefix}_ft_pass": 0,
                    f"{prefix}_gross_r": round(gross, 5),
                    f"{prefix}_net_r": round(gross - cost_r, 5),
                    f"{prefix}_hold_bars": bars,
                    f"{prefix}_exit_time": (t + STEP).isoformat(),
                })
                return out
        else:
            if l <= tp2:
                gross = 1.0 + 0.5 * float(room_r)
                out.update({
                    f"{prefix}_state": "TP2_DEMAND",
                    f"{prefix}_gross_r": round(gross, 5),
                    f"{prefix}_net_r": round(gross - cost_r, 5),
                    f"{prefix}_hold_bars": bars,
                    f"{prefix}_exit_time": (t + STEP).isoformat(),
                })
                return out
            if tp1_index is not None and i > tp1_index and h >= entry:
                gross = 1.0
                out.update({
                    f"{prefix}_state": "TP1_THEN_BE",
                    f"{prefix}_gross_r": round(gross, 5),
                    f"{prefix}_net_r": round(gross - cost_r, 5),
                    f"{prefix}_hold_bars": bars,
                    f"{prefix}_exit_time": (t + STEP).isoformat(),
                })
                return out

    if expected < end_time or last_close is None:
        out[f"{prefix}_state"] = "CENSORED_INCOMPLETE_HORIZON"
        return out

    if tp1_hit:
        gross = 1.0 + 0.5 * ((entry - last_close) / risk)
        state = "TP1_TIME_EXIT"
    else:
        gross = (entry - last_close) / risk
        state = "TIME_EXIT"
    out.update({
        f"{prefix}_state": state,
        f"{prefix}_gross_r": round(gross, 5),
        f"{prefix}_net_r": round(gross - cost_r, 5),
        f"{prefix}_hold_bars": bars,
        f"{prefix}_exit_time": end_time.isoformat(),
        f"{prefix}_ft_state": out.get(f"{prefix}_ft_state") or (
            "PASS" if ft_pass else "FAIL_NO_IMMEDIATE_FOLLOWTHROUGH"
        ),
        f"{prefix}_ft_pass": int(ft_pass),
    })
    return out


def _liquidity_pool(records, atr, zone_lower, zone_upper):
    if not records or len(records) < int(V441_M1_LIQ_MIN_TOUCHES):
        return None
    recent = records[-int(V441_M1_LIQ_LOOKBACK_BARS):]
    pts = [
        {"i": i, "high": float(r["high"])}
        for i, r in enumerate(recent)
        if _num(r.get("high")) is not None
    ]
    pts.sort(key=lambda x: x["high"])
    groups = []
    for p in pts:
        if (
            groups
            and abs(float(p["high"]) - float(groups[-1][-1]["high"]))
            <= float(V441_M1_LIQ_CLUSTER_ATR) * atr
        ):
            groups[-1].append(p)
        else:
            groups.append([p])

    lo = zone_lower - float(V441_M1_LIQ_ZONE_BELOW_ATR) * atr
    hi = zone_upper + float(V441_M1_LIQ_ZONE_ABOVE_ATR) * atr
    valid = []
    for g in groups:
        if len(g) < int(V441_M1_LIQ_MIN_TOUCHES):
            continue
        pos = sorted(int(x["i"]) for x in g)
        if pos[-1] - pos[0] < int(V441_M1_LIQ_MIN_SEPARATION_BARS):
            continue
        level = sum(float(x["high"]) for x in g) / len(g)
        if lo <= level <= hi:
            valid.append({"level": level, "touches": len(g), "last_i": pos[-1]})
    if not valid:
        return None
    valid.sort(key=lambda x: (x["touches"], x["last_i"], x["level"]), reverse=True)
    return valid[0]


def _bar_rejection(bar):
    o, h, l, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
    if h <= l or c >= o:
        return False
    upper_wick = h - max(o, c)
    wick_ratio = upper_wick / max(h - l, 1e-12)
    close_pos = (c - l) / max(h - l, 1e-12)
    return bool(
        wick_ratio >= float(V441_M1_MIN_REJECTION_WICK_RATIO)
        or close_pos <= 0.45
    )


def _m1_confirmation(bar, seed, atr, zone_upper):
    o, h, l, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
    pool = float(seed["pool"])
    failed_auction = c < pool
    rejection = _bar_rejection(bar)
    bos = c < float(seed["micro_low"]) - float(V441_M1_BREAK_BUFFER_ATR) * atr
    body_atr = (o - c) / atr if c < o else 0.0
    controlled_body = bool(
        float(V441_M1_BODY_MIN_ATR)
        <= body_atr
        <= float(V441_M1_BODY_MAX_ATR)
    )
    no_reclaim = c <= max(pool, zone_upper) + 0.12 * atr
    score = sum((failed_auction, rejection, bos, controlled_body, no_reclaim))
    return {
        "score": int(score),
        "failed_auction": int(failed_auction),
        "rejection": int(rejection),
        "bos": int(bos),
        "controlled_body": int(controlled_body),
        "no_reclaim": int(no_reclaim),
        "body_atr": round(body_atr, 4),
        "close_near_pool": int(c <= pool + float(V441_M1_CLOSE_TOLERANCE_ATR) * atr),
    }


def _attach_demand(prefix, seed, demand, entry, stop, atr):
    risk = stop - entry
    target = float(demand["upper"]) + float(V441_DEMAND_TARGET_BUFFER_ATR) * atr
    room_r = (entry - target) / risk
    seed.update({
        f"{prefix}_demand_source": demand["source"],
        f"{prefix}_demand_lower": round(float(demand["lower"]), 10),
        f"{prefix}_demand_upper": round(float(demand["upper"]), 10),
        f"{prefix}_demand_target": round(target, 10),
        f"{prefix}_room_r": round(room_r, 4),
        f"{prefix}_room_pass": int(target > 0 and room_r >= float(V441_MIN_ROOM_R)),
    })
    return target, room_r


def evaluate_m1(features, hist15, future15, one_closed, four_closed):
    prefix = "v441_m1"
    result = _empty(prefix, "NO_M1_CONTEXT")
    atr = _num(features.get("atr_1h"))
    lower = _num(features.get("preferred_zone_lower"))
    upper = _num(features.get("preferred_zone_upper"))
    if any(x is None for x in (atr, lower, upper)) or atr <= 0:
        return _empty(prefix, "INVALID_CONTEXT")

    context_ok = bool(
        int(features.get("v428_strong_zone") or 0) == 1
        and int(features.get("s4_ema_bear") or 0) == 1
        and int(features.get("s4_lower_high") or 0) == 1
        and not bool(features.get("severe_bottom_rule"))
    )
    if not context_ok:
        return result
    result[f"{prefix}_context_ok"] = 1

    if hist15 is None or len(hist15) < 12 or future15 is None or len(future15) < 2:
        result[f"{prefix}_state"] = "NO_15M_CONTEXT"
        return result

    hist15 = hist15.sort_index()
    future15 = future15.sort_index()
    recent_closed = list(hist15.tail(int(V441_M1_LIQ_LOOKBACK_BARS)).to_dict("records"))
    deadline = future15.index[0] + pd.Timedelta(hours=int(V441_M1_TRIGGER_WAIT_HOURS))
    sweep_seed = None
    last_reason = "NO_LIQUIDITY_POOL"

    for i in range(0, len(future15) - 1):
        t = future15.index[i]
        if t >= deadline:
            break
        bar = future15.iloc[i]
        o, h, l, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
        if not all(math.isfinite(x) for x in (o, h, l, c)):
            continue

        if sweep_seed is None:
            pool = _liquidity_pool(recent_closed, atr, lower, upper)
            if pool is not None:
                last_reason = "NO_SWEEP"
                touched_zone = h >= lower - 0.12 * atr and l <= upper + 0.12 * atr
                if (
                    touched_zone
                    and h >= float(pool["level"]) + float(V441_M1_SWEEP_BUFFER_ATR) * atr
                ):
                    prior = recent_closed[-int(V441_M1_BOS_LOOKBACK_BARS):]
                    if prior:
                        sweep_seed = {
                            "sweep_i": i,
                            "pool": float(pool["level"]),
                            "touches": int(pool["touches"]),
                            "sweep_high": h,
                            "micro_low": min(float(x["low"]) for x in prior),
                            "sweep_time": t,
                        }
                        last_reason = "NO_M1_CONFIRMATION"
        else:
            bars_after = i - int(sweep_seed["sweep_i"])
            sweep_seed["sweep_high"] = max(float(sweep_seed["sweep_high"]), h)
            if c > upper + 0.30 * atr:
                sweep_seed = None
                last_reason = "SWEEP_INVALIDATED"
            elif bars_after > int(V441_M1_CONFIRM_WAIT_BARS):
                sweep_seed = None
                last_reason = "NO_M1_CONFIRMATION"
            else:
                conf = _m1_confirmation(bar, sweep_seed, atr, upper)
                if (
                    conf["score"] >= int(V441_M1_MIN_CONFIRM_SCORE)
                    and conf["close_near_pool"] == 1
                ):
                    if not _next_bar(future15, i):
                        result[f"{prefix}_state"] = "NO_NEXT_OPEN"
                        return result
                    entry = float(future15.iloc[i + 1]["open"])
                    if entry < lower - float(V441_M1_NO_CHASE_ATR) * atr:
                        sweep_seed = None
                        last_reason = "SKIP_CHASE"
                    else:
                        stop = max(
                            float(sweep_seed["sweep_high"]) + float(V441_STOP_BUFFER_ATR) * atr,
                            upper + float(V441_STOP_BUFFER_ATR) * atr,
                            entry + float(V441_MIN_RISK_ATR) * atr,
                        )
                        reason = _plan_reason(entry, stop, atr)
                        if reason:
                            sweep_seed = None
                            last_reason = reason
                        else:
                            demand = _nearest_demand(one_closed, four_closed, entry, atr)
                            if demand is None:
                                sweep_seed = None
                                last_reason = "NO_DEMAND"
                            else:
                                seed = _empty(prefix, "PLANNED")
                                seed.update({
                                    f"{prefix}_context_ok": 1,
                                    f"{prefix}_confirm_score": conf["score"],
                                    f"{prefix}_liquidity_pool": round(float(sweep_seed["pool"]), 10),
                                    f"{prefix}_liquidity_touches": int(sweep_seed["touches"]),
                                    f"{prefix}_sweep_time": sweep_seed["sweep_time"].isoformat(),
                                    f"{prefix}_sweep_high": round(float(sweep_seed["sweep_high"]), 10),
                                    f"{prefix}_confirm_time": t.isoformat(),
                                    f"{prefix}_failed_auction": conf["failed_auction"],
                                    f"{prefix}_rejection": conf["rejection"],
                                    f"{prefix}_micro_bos": conf["bos"],
                                    f"{prefix}_controlled_body": conf["controlled_body"],
                                    f"{prefix}_no_reclaim": conf["no_reclaim"],
                                    f"{prefix}_confirm_body_atr": conf["body_atr"],
                                })
                                target, room_r = _attach_demand(
                                    prefix, seed, demand, entry, stop, atr
                                )
                                if target <= 0 or room_r < float(V441_MIN_ROOM_R):
                                    sweep_seed = None
                                    last_reason = "SKIP_ROOM_TO_DEMAND"
                                else:
                                    tp1 = entry - float(V441_TP1_R) * (stop - entry)
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
                                        float(sweep_seed["pool"]),
                                        seed,
                                    )

        recent_closed.append({"open": o, "high": h, "low": l, "close": c})

    result[f"{prefix}_state"] = last_reason
    return result


def _pivot_lows(frame, bars, left=2, right=2):
    if frame is None or len(frame) < left + right + 2:
        return []
    view = frame.tail(int(bars)).copy()
    lows = view["low"].astype(float).to_numpy()
    out = []
    for i in range(left, len(view) - right):
        x = float(lows[i])
        if x <= 0 or not math.isfinite(x):
            continue
        if any(x >= float(lows[j]) for j in range(i - left, i)):
            continue
        if any(x > float(lows[j]) for j in range(i + 1, i + right + 1)):
            continue
        row = view.iloc[i]
        out.append({
            "pos": i,
            "low": x,
            "open": float(row["open"]),
            "close": float(row["close"]),
            "view": view,
        })
    return out


def _structural_support(four_closed, current, atr):
    pivots = _pivot_lows(four_closed, V441_M2_SUPPORT_LOOKBACK_4H)
    pivots.sort(key=lambda x: x["low"])
    groups = []
    for p in pivots:
        if (
            groups
            and abs(float(p["low"]) - float(groups[-1][-1]["low"]))
            <= float(V441_M2_SUPPORT_CLUSTER_ATR) * atr
        ):
            groups[-1].append(p)
        else:
            groups.append([p])

    candidates = []
    for g in groups:
        if len(g) < int(V441_M2_SUPPORT_MIN_TOUCHES):
            continue
        positions = sorted(int(p["pos"]) for p in g)
        if positions[-1] - positions[0] < int(V441_M2_SUPPORT_MIN_SEPARATION_BARS):
            continue
        level = sum(float(p["low"]) for p in g) / len(g)
        latest = g[-1]
        later = latest["view"].iloc[int(latest["pos"]) + 3 :]["close"].astype(float)
        if len(later) and bool((later < level - 0.20 * atr).any()):
            continue
        distance = (current - level) / atr
        if not (
            -float(V441_M2_MAX_PREBROKEN_ATR)
            <= distance
            <= float(V441_M2_MAX_DISTANCE_ATR)
        ):
            continue
        candidates.append({
            "level": level,
            "lower": min(float(p["low"]) for p in g),
            "upper": max(max(float(p["open"]), float(p["close"])) for p in g),
            "touches": len(g),
            "distance_atr": distance,
        })
    if not candidates:
        return None
    candidates.sort(key=lambda x: (abs(float(x["distance_atr"])), -int(x["touches"])))
    return candidates[0]


def _next_demand_below(one_closed, four_closed, entry, atr, broken_support):
    probe = entry
    for _ in range(8):
        demand = _nearest_demand(one_closed, four_closed, probe, atr)
        if demand is None:
            return None
        if float(demand["upper"]) < float(broken_support) - float(V441_M2_NEXT_DEMAND_GAP_ATR) * atr:
            return demand
        probe = float(demand["lower"]) - 0.05 * atr
        if probe <= 0:
            return None
    return None


def _m2_pressure_score(features):
    votes = [
        int(features.get("s1_ema_bear") or 0) == 1,
        int(features.get("s1_lower_high") or 0) == 1,
        float(features.get("relative_4h_pct") or 0.0) < 0.0,
        float(features.get("continuation_quality") or 0.0) >= 2.0,
    ]
    return sum(bool(x) for x in votes)


def evaluate_m2(features, hist15, future15, one_closed, four_closed):
    prefix = "v441_m2"
    result = _empty(prefix, "NO_M2_CONTEXT")
    atr = _num(features.get("atr_1h"))
    current = _num(features.get("current_price"))
    if atr is None or atr <= 0 or current is None:
        return _empty(prefix, "INVALID_CONTEXT")

    pressure = _m2_pressure_score(features)
    bearish4 = bool(
        int(features.get("s4_ema_bear") or 0) == 1
        and int(features.get("s4_lower_high") or 0) == 1
    )
    if not bearish4 or pressure < 1 or bool(features.get("severe_bottom_rule")):
        return result

    support = _structural_support(four_closed, current, atr)
    if support is None:
        result[f"{prefix}_state"] = "NO_STRUCTURAL_SUPPORT"
        return result
    result.update({
        f"{prefix}_context_ok": 1,
        f"{prefix}_support_level": round(float(support["level"]), 10),
        f"{prefix}_support_lower": round(float(support["lower"]), 10),
        f"{prefix}_support_upper": round(float(support["upper"]), 10),
        f"{prefix}_support_touches": int(support["touches"]),
        f"{prefix}_support_distance_atr": round(float(support["distance_atr"]), 4),
        f"{prefix}_pressure_score": int(pressure),
        f"{prefix}_compression": int(features.get("s1_lower_high") or 0),
    })

    if future15 is None or len(future15) < 2:
        result[f"{prefix}_state"] = "NO_15M_CONTEXT"
        return result
    future15 = future15.sort_index()
    deadline = future15.index[0] + pd.Timedelta(hours=int(V441_M2_TRIGGER_WAIT_HOURS))
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
            if c < level - float(V441_M2_BREAK_BUFFER_ATR) * atr and c < o:
                body_atr = (o - c) / atr
                break_seed = {
                    "break_i": i,
                    "break_time": t,
                    "break_high": h,
                    "break_low": l,
                    "body_atr": body_atr,
                    "controlled": int(
                        float(V441_M2_BREAK_BODY_MIN_ATR)
                        <= body_atr
                        <= float(V441_M2_BREAK_BODY_MAX_ATR)
                    ),
                    "acceptance": 1,
                }
                last_reason = "NO_FAILED_RECLAIM"
        else:
            bars_after = i - int(break_seed["break_i"])
            if c > level + float(V441_M2_RECLAIM_INVALIDATION_ATR) * atr:
                break_seed = None
                last_reason = "BREAKDOWN_INVALIDATED"
            elif bars_after > int(V441_M2_RETEST_WAIT_BARS):
                break_seed = None
                last_reason = "NO_FAILED_RECLAIM"
            else:
                if c < level:
                    break_seed["acceptance"] = int(break_seed.get("acceptance", 0)) + 1
                touched = h >= level - float(V441_M2_RETEST_TOLERANCE_ATR) * atr
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
                acceptance = int(break_seed.get("acceptance", 0)) >= 2
                compression = int(features.get("s1_lower_high") or 0) == 1
                confirm_score = sum((
                    bool(break_seed["controlled"]),
                    bool(touched),
                    bool(bearish_rejection),
                    bool(acceptance),
                    bool(compression),
                ))
                confirmed = bool(
                    confirm_score >= int(V441_M2_MIN_CONFIRM_SCORE)
                    and (touched or acceptance)
                    and c < level
                )
                if confirmed:
                    if not _next_bar(future15, i):
                        result[f"{prefix}_state"] = "NO_NEXT_OPEN"
                        return result
                    entry = float(future15.iloc[i + 1]["open"])
                    if entry < level - float(V441_M2_NO_CHASE_ATR) * atr:
                        break_seed = None
                        last_reason = "SKIP_CHASE"
                    else:
                        trigger_high = max(float(break_seed["break_high"]), h)
                        stop = max(
                            trigger_high + float(V441_STOP_BUFFER_ATR) * atr,
                            level + float(V441_STOP_BUFFER_ATR) * atr,
                            entry + float(V441_MIN_RISK_ATR) * atr,
                        )
                        reason = _plan_reason(entry, stop, atr)
                        if reason:
                            break_seed = None
                            last_reason = reason
                        else:
                            demand = _next_demand_below(
                                one_closed, four_closed, entry, atr, level
                            )
                            if demand is None:
                                break_seed = None
                                last_reason = "NO_NEXT_DEMAND"
                            else:
                                seed = dict(result)
                                seed.update({
                                    f"{prefix}_state": "PLANNED",
                                    f"{prefix}_confirm_score": int(confirm_score),
                                    f"{prefix}_break_time": break_seed["break_time"].isoformat(),
                                    f"{prefix}_break_body_atr": round(float(break_seed["body_atr"]), 4),
                                    f"{prefix}_controlled_break": int(break_seed["controlled"]),
                                    f"{prefix}_retest_touched": int(touched),
                                    f"{prefix}_retest_rejection": int(bearish_rejection),
                                    f"{prefix}_acceptance_bars": int(break_seed.get("acceptance", 0)),
                                    f"{prefix}_confirm_time": t.isoformat(),
                                })
                                target, room_r = _attach_demand(
                                    prefix, seed, demand, entry, stop, atr
                                )
                                if target <= 0 or room_r < float(V441_MIN_ROOM_R):
                                    break_seed = None
                                    last_reason = "SKIP_ROOM_TO_DEMAND"
                                else:
                                    tp1 = entry - float(V441_TP1_R) * (stop - entry)
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


def evaluate_v441_models(features, hist15, future15, one_closed, four_closed):
    out = {}
    out.update(evaluate_m1(features, hist15, future15, one_closed, four_closed))
    out.update(evaluate_m2(features, hist15, future15, one_closed, four_closed))
    return out
