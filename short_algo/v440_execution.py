"""V4.4 causal structural short-entry engine.

Decision chain:
1) strong supply context already frozen in the upstream feature row;
2) repeated buy-side liquidity pool exists before the trigger;
3) a closed 15m candle sweeps the pool and closes back below it;
4) a subsequent closed 15m candle produces a controlled bearish micro-BOS;
5) fill only at the next 15m open;
6) freeze nearest meaningful demand from signal-time 1h/4h data;
7) require >= fixed room-to-demand R before allowing the trade;
8) require causal immediate follow-through or exit early.

No future best-price selection, no C re-entry, no retrospective follow-through
filter, and no optimistic same-bar SL/TP ordering.
"""
import math

import pandas as pd

from .v440_config import (
    V440_BOS_LOOKBACK_BARS,
    V440_BOS_WAIT_BARS,
    V440_BREAK_BODY_MAX_ATR,
    V440_BREAK_BODY_MIN_ATR,
    V440_BREAK_BUFFER_ATR,
    V440_COST_BPS,
    V440_DEMAND_1H_BARS,
    V440_DEMAND_1H_WIDTH_ATR,
    V440_DEMAND_4H_BARS,
    V440_DEMAND_4H_WIDTH_ATR,
    V440_DEMAND_BROKEN_ATR,
    V440_DEMAND_CLUSTER_ATR,
    V440_DEMAND_TARGET_BUFFER_ATR,
    V440_FT_MIN_MFE_R,
    V440_FT_RECLAIM_BUFFER_ATR,
    V440_FT_WINDOW_BARS,
    V440_HOLD_HOURS,
    V440_LIQ_CLUSTER_ATR,
    V440_LIQ_LOOKBACK_BARS,
    V440_LIQ_MIN_SEPARATION_BARS,
    V440_LIQ_MIN_TOUCHES,
    V440_LIQ_ZONE_ABOVE_ATR,
    V440_LIQ_ZONE_BELOW_ATR,
    V440_MAX_COST_R,
    V440_MAX_RISK_ATR,
    V440_MAX_STOP_PCT,
    V440_MIN_RISK_ATR,
    V440_MIN_ROOM_R,
    V440_MIN_SWEEP_UPPER_WICK_RATIO,
    V440_NO_CHASE_ATR,
    V440_STOP_BUFFER_ATR,
    V440_SWEEP_BUFFER_ATR,
    V440_SWEEP_RECLAIM_BUFFER_ATR,
    V440_TP1_R,
    V440_TRIGGER_WAIT_HOURS,
)

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


def _empty(state):
    return {
        "v440_state": state,
        "v440_trigger": None,
        "v440_liquidity_pool": None,
        "v440_liquidity_touches": 0,
        "v440_sweep_time": None,
        "v440_sweep_high": None,
        "v440_bos_time": None,
        "v440_bos_level": None,
        "v440_break_body_atr": None,
        "v440_entry_time": None,
        "v440_entry": None,
        "v440_stop": None,
        "v440_risk_pct": None,
        "v440_risk_atr": None,
        "v440_cost_r": None,
        "v440_demand_source": None,
        "v440_demand_lower": None,
        "v440_demand_upper": None,
        "v440_demand_target": None,
        "v440_room_r": None,
        "v440_room_pass": 0,
        "v440_tp1": None,
        "v440_tp2": None,
        "v440_tp1_hit": 0,
        "v440_tp1_time": None,
        "v440_ft_state": None,
        "v440_ft_pass": 0,
        "v440_ft_mfe_r": None,
        "v440_gross_r": None,
        "v440_net_r": None,
        "v440_hold_bars": None,
        "v440_exit_time": None,
    }


def _next_bar(frame, i):
    return (
        i + 1 < len(frame)
        and frame.index[i + 1] == frame.index[i] + STEP
    )


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


def _is_unbroken(pivot, atr):
    view = pivot["view"]
    later = view.iloc[int(pivot["pos"]) + 3 :]["close"].astype(float)
    if later.empty:
        return True
    return not bool((later < float(pivot["low"]) - float(V440_DEMAND_BROKEN_ATR) * atr).any())


def _nearest_demand(one_closed, four_closed, entry, atr):
    """Nearest meaningful demand known at signal time.

    4h confirmed pivot lows are structural demand. 1h demand is admitted only
    when at least two confirmed pivots cluster, reducing single-pivot noise.
    The nearest zone upper edge is the first meaningful obstacle for a short.
    """
    candidates = []

    for p in _pivot_lows(four_closed, V440_DEMAND_4H_BARS):
        if p["low"] >= entry or not _is_unbroken(p, atr):
            continue
        body_top = max(p["open"], p["close"])
        upper = min(body_top, p["low"] + float(V440_DEMAND_4H_WIDTH_ATR) * atr)
        upper = max(upper, p["low"] + 0.10 * atr)
        if upper < entry:
            candidates.append({
                "source": "DEMAND_4H",
                "lower": p["low"],
                "upper": upper,
            })

    piv1 = [
        p for p in _pivot_lows(one_closed, V440_DEMAND_1H_BARS)
        if p["low"] < entry and _is_unbroken(p, atr)
    ]
    piv1.sort(key=lambda x: x["low"])
    groups = []
    for p in piv1:
        if (
            groups
            and abs(float(p["low"]) - float(groups[-1][-1]["low"]))
            <= float(V440_DEMAND_CLUSTER_ATR) * atr
        ):
            groups[-1].append(p)
        else:
            groups.append([p])
    for group in groups:
        if len(group) < 2:
            continue
        lower = min(float(p["low"]) for p in group)
        body_top = max(max(float(p["open"]), float(p["close"])) for p in group)
        upper = min(body_top, lower + float(V440_DEMAND_1H_WIDTH_ATR) * atr)
        upper = max(upper, lower + 0.08 * atr)
        if upper < entry:
            candidates.append({
                "source": "DEMAND_1H_CLUSTER",
                "lower": lower,
                "upper": upper,
            })

    if not candidates:
        return None
    candidates.sort(key=lambda x: (float(x["upper"]), x["source"]), reverse=True)
    return candidates[0]


def _liquidity_pool(records, atr, zone_lower, zone_upper):
    """Find repeated highs from bars that were closed before the sweep bar."""
    if not records or len(records) < int(V440_LIQ_MIN_TOUCHES):
        return None
    recent = records[-int(V440_LIQ_LOOKBACK_BARS):]
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
            <= float(V440_LIQ_CLUSTER_ATR) * atr
        ):
            groups[-1].append(p)
        else:
            groups.append([p])

    valid = []
    lo = zone_lower - float(V440_LIQ_ZONE_BELOW_ATR) * atr
    hi = zone_upper + float(V440_LIQ_ZONE_ABOVE_ATR) * atr
    for g in groups:
        if len(g) < int(V440_LIQ_MIN_TOUCHES):
            continue
        positions = sorted(int(x["i"]) for x in g)
        if positions[-1] - positions[0] < int(V440_LIQ_MIN_SEPARATION_BARS):
            continue
        level = sum(float(x["high"]) for x in g) / len(g)
        if not (lo <= level <= hi):
            continue
        valid.append({
            "level": level,
            "touches": len(g),
            "last_i": positions[-1],
        })
    if not valid:
        return None
    valid.sort(key=lambda x: (x["touches"], x["last_i"], x["level"]), reverse=True)
    return valid[0]


def _failed_auction(bar, pool, atr):
    o, h, l, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
    if h <= l or c >= o:
        return False
    wick = h - max(o, c)
    upper_wick_ratio = wick / max(h - l, 1e-12)
    return bool(
        h >= float(pool) + float(V440_SWEEP_BUFFER_ATR) * atr
        and c < float(pool)
        and upper_wick_ratio >= float(V440_MIN_SWEEP_UPPER_WICK_RATIO)
    )


def _plan_reason(entry, stop, atr):
    if any(x is None for x in (entry, stop, atr)):
        return "INVALID_PLAN"
    if entry <= 0 or stop <= entry or atr <= 0:
        return "INVALID_PLAN"
    risk = stop - entry
    if 100.0 * risk / entry > float(V440_MAX_STOP_PCT):
        return "SKIP_STOP_PCT"
    if risk / atr > float(V440_MAX_RISK_ATR):
        return "SKIP_RISK_TOO_WIDE"
    cost_r = float(V440_COST_BPS) / 10000.0 * entry / risk
    if cost_r > float(V440_MAX_COST_R):
        return "SKIP_COST_R"
    return None


def _simulate_staged(
    future15,
    start_idx,
    entry,
    stop,
    atr,
    tp1,
    tp2,
    room_r,
    bos_level,
    seed,
):
    out = dict(seed)
    risk = stop - entry
    cost_r = float(V440_COST_BPS) / 10000.0 * entry / risk
    entry_time = future15.index[start_idx]
    out.update({
        "v440_state": "INVALID_PLAN",
        "v440_entry_time": entry_time.isoformat(),
        "v440_entry": round(entry, 10),
        "v440_stop": round(stop, 10),
        "v440_risk_pct": round(100.0 * risk / entry, 4),
        "v440_risk_atr": round(risk / atr, 4),
        "v440_cost_r": round(cost_r, 5),
        "v440_tp1": round(tp1, 10),
        "v440_tp2": round(tp2, 10),
    })
    if float(future15.iloc[start_idx]["open"]) >= stop:
        out["v440_state"] = "GAP_BEYOND_STOP"
        return out

    end_time = entry_time + pd.Timedelta(hours=int(V440_HOLD_HOURS))
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
            out["v440_state"] = "CENSORED_15M_GAP"
            return out
        bar = future15.iloc[i]
        o, h, l, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
        if not all(math.isfinite(x) for x in (o, h, l, c)):
            out["v440_state"] = "CENSORED_BAD_BAR"
            return out

        expected += STEP
        bars += 1
        last_close = c
        best_low = min(best_low, l)
        mfe_r = max(0.0, (entry - best_low) / risk)
        out["v440_ft_mfe_r"] = round(mfe_r, 4)

        # Conservative collision rule: initial SL wins if both full-stop and
        # a target are touched in the same bar before TP1 was previously banked.
        if not tp1_hit and h >= stop:
            gross = (entry - max(o, stop)) / risk
            out.update({
                "v440_state": "SL_FIRST",
                "v440_gross_r": round(gross, 5),
                "v440_net_r": round(gross - cost_r, 5),
                "v440_hold_bars": bars,
                "v440_exit_time": (t + STEP).isoformat(),
                "v440_ft_state": "STOP_BEFORE_FOLLOWTHROUGH" if not ft_pass else "PASS",
                "v440_ft_pass": int(ft_pass),
            })
            return out

        if not ft_pass and mfe_r >= float(V440_FT_MIN_MFE_R):
            ft_pass = True
            out["v440_ft_state"] = "PASS"
            out["v440_ft_pass"] = 1

        if not tp1_hit:
            reclaim_level = float(bos_level) + float(V440_FT_RECLAIM_BUFFER_ATR) * atr
            if (
                not ft_pass
                and bars <= int(V440_FT_WINDOW_BARS)
                and c > reclaim_level
            ):
                gross = (entry - c) / risk
                out.update({
                    "v440_state": "FT_RECLAIM_EXIT",
                    "v440_ft_state": "FAIL_BOS_RECLAIM",
                    "v440_ft_pass": 0,
                    "v440_gross_r": round(gross, 5),
                    "v440_net_r": round(gross - cost_r, 5),
                    "v440_hold_bars": bars,
                    "v440_exit_time": (t + STEP).isoformat(),
                })
                return out

            if l <= tp1:
                tp1_hit = True
                tp1_index = i
                ft_pass = True
                out.update({
                    "v440_tp1_hit": 1,
                    "v440_tp1_time": (t + STEP).isoformat(),
                    "v440_ft_state": "PASS",
                    "v440_ft_pass": 1,
                })
                if l <= tp2:
                    gross = 1.0 + 0.5 * float(room_r)
                    out.update({
                        "v440_state": "TP2_DEMAND",
                        "v440_gross_r": round(gross, 5),
                        "v440_net_r": round(gross - cost_r, 5),
                        "v440_hold_bars": bars,
                        "v440_exit_time": (t + STEP).isoformat(),
                    })
                    return out

            if (
                not tp1_hit
                and not ft_pass
                and bars >= int(V440_FT_WINDOW_BARS)
            ):
                gross = (entry - c) / risk
                out.update({
                    "v440_state": "FT_EXIT",
                    "v440_ft_state": "FAIL_NO_IMMEDIATE_FOLLOWTHROUGH",
                    "v440_ft_pass": 0,
                    "v440_gross_r": round(gross, 5),
                    "v440_net_r": round(gross - cost_r, 5),
                    "v440_hold_bars": bars,
                    "v440_exit_time": (t + STEP).isoformat(),
                })
                return out
        else:
            if l <= tp2:
                gross = 1.0 + 0.5 * float(room_r)
                out.update({
                    "v440_state": "TP2_DEMAND",
                    "v440_gross_r": round(gross, 5),
                    "v440_net_r": round(gross - cost_r, 5),
                    "v440_hold_bars": bars,
                    "v440_exit_time": (t + STEP).isoformat(),
                })
                return out
            # Break-even is active only from the bar after TP1 was banked.
            if tp1_index is not None and i > tp1_index and h >= entry:
                gross = 1.0
                out.update({
                    "v440_state": "TP1_THEN_BE",
                    "v440_gross_r": round(gross, 5),
                    "v440_net_r": round(gross - cost_r, 5),
                    "v440_hold_bars": bars,
                    "v440_exit_time": (t + STEP).isoformat(),
                })
                return out

    if expected < end_time or last_close is None:
        out["v440_state"] = "CENSORED_INCOMPLETE_HORIZON"
        return out

    if tp1_hit:
        gross = 1.0 + 0.5 * ((entry - last_close) / risk)
        state = "TP1_TIME_EXIT"
    else:
        gross = (entry - last_close) / risk
        state = "TIME_EXIT"
    out.update({
        "v440_state": state,
        "v440_gross_r": round(gross, 5),
        "v440_net_r": round(gross - cost_r, 5),
        "v440_hold_bars": bars,
        "v440_exit_time": end_time.isoformat(),
        "v440_ft_state": out.get("v440_ft_state") or ("PASS" if ft_pass else "FAIL_NO_IMMEDIATE_FOLLOWTHROUGH"),
        "v440_ft_pass": int(ft_pass),
    })
    return out


def evaluate_v440_entry(features, hist15, future15, one_closed, four_closed):
    result = _empty("NO_LIQUIDITY_POOL")
    atr = _num(features.get("atr_1h"))
    zone_lower = _num(features.get("preferred_zone_lower"))
    zone_upper = _num(features.get("preferred_zone_upper"))
    if any(x is None for x in (atr, zone_lower, zone_upper)) or atr <= 0:
        return _empty("INVALID_CONTEXT")
    if int(features.get("v428_strong_zone") or 0) != 1:
        return _empty("NO_STRONG_SUPPLY")
    if hist15 is None or len(hist15) < 12 or future15 is None or len(future15) < 2:
        return _empty("NO_15M_CONTEXT")

    hist15 = hist15.sort_index()
    future15 = future15.sort_index()
    deadline = future15.index[0] + pd.Timedelta(hours=int(V440_TRIGGER_WAIT_HOURS))
    recent_closed = list(hist15.tail(int(V440_LIQ_LOOKBACK_BARS)).to_dict("records"))
    sweep_seed = None
    last_reason = "NO_LIQUIDITY_POOL"

    for i in range(0, len(future15) - 1):
        t = future15.index[i]
        if t >= deadline:
            break
        bar = future15.iloc[i]
        o, h, l, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
        if not all(math.isfinite(x) for x in (o, h, l, c)):
            recent_closed.append({"open": o, "high": h, "low": l, "close": c})
            continue

        if sweep_seed is None:
            pool = _liquidity_pool(recent_closed, atr, zone_lower, zone_upper)
            if pool is not None:
                last_reason = "NO_SWEEP"
                touched_zone = (
                    h >= zone_lower - 0.12 * atr
                    and l <= zone_upper + 0.12 * atr
                )
                if touched_zone and _failed_auction(bar, pool["level"], atr):
                    prior = recent_closed[-int(V440_BOS_LOOKBACK_BARS):]
                    if prior:
                        sweep_seed = {
                            "sweep_i": i,
                            "pool": float(pool["level"]),
                            "touches": int(pool["touches"]),
                            "sweep_high": h,
                            "micro_low": min(float(x["low"]) for x in prior),
                            "sweep_time": t,
                        }
                        last_reason = "NO_CONTROLLED_BOS"
        else:
            bars_after = i - int(sweep_seed["sweep_i"])
            if c > float(sweep_seed["sweep_high"]) + float(V440_SWEEP_RECLAIM_BUFFER_ATR) * atr:
                sweep_seed = None
                last_reason = "SWEEP_INVALIDATED"
            elif bars_after > int(V440_BOS_WAIT_BARS):
                sweep_seed = None
                last_reason = "NO_CONTROLLED_BOS"
            elif bars_after >= 1:
                body_atr = (o - c) / atr if c < o else 0.0
                bos = (
                    c < float(sweep_seed["micro_low"]) - float(V440_BREAK_BUFFER_ATR) * atr
                    and c < o
                    and float(V440_BREAK_BODY_MIN_ATR)
                    <= body_atr
                    <= float(V440_BREAK_BODY_MAX_ATR)
                )
                if bos:
                    if not _next_bar(future15, i):
                        return _empty("NO_NEXT_OPEN")
                    entry = float(future15.iloc[i + 1]["open"])
                    if entry < zone_lower - float(V440_NO_CHASE_ATR) * atr:
                        sweep_seed = None
                        last_reason = "SKIP_CHASE"
                    else:
                        stop = max(
                            float(sweep_seed["sweep_high"]),
                            zone_upper,
                            entry + float(V440_MIN_RISK_ATR) * atr,
                        ) + float(V440_STOP_BUFFER_ATR) * atr
                        reason = _plan_reason(entry, stop, atr)
                        if reason:
                            sweep_seed = None
                            last_reason = reason
                        else:
                            risk = stop - entry
                            demand = _nearest_demand(
                                one_closed, four_closed, entry, atr
                            )
                            if demand is None:
                                sweep_seed = None
                                last_reason = "NO_DEMAND"
                            else:
                                target = float(demand["upper"]) + float(V440_DEMAND_TARGET_BUFFER_ATR) * atr
                                room_r = (entry - target) / risk
                                if target <= 0 or room_r < float(V440_MIN_ROOM_R):
                                    sweep_seed = None
                                    last_reason = "SKIP_ROOM_TO_DEMAND"
                                else:
                                    tp1 = entry - float(V440_TP1_R) * risk
                                    seed = _empty("PLANNED")
                                    seed.update({
                                        "v440_trigger": "LIQUIDITY_SWEEP_CONTROLLED_BOS",
                                        "v440_liquidity_pool": round(float(sweep_seed["pool"]), 10),
                                        "v440_liquidity_touches": int(sweep_seed["touches"]),
                                        "v440_sweep_time": sweep_seed["sweep_time"].isoformat(),
                                        "v440_sweep_high": round(float(sweep_seed["sweep_high"]), 10),
                                        "v440_bos_time": t.isoformat(),
                                        "v440_bos_level": round(float(sweep_seed["micro_low"]), 10),
                                        "v440_break_body_atr": round(body_atr, 4),
                                        "v440_demand_source": demand["source"],
                                        "v440_demand_lower": round(float(demand["lower"]), 10),
                                        "v440_demand_upper": round(float(demand["upper"]), 10),
                                        "v440_demand_target": round(target, 10),
                                        "v440_room_r": round(room_r, 4),
                                        "v440_room_pass": 1,
                                    })
                                    return _simulate_staged(
                                        future15,
                                        i + 1,
                                        entry,
                                        stop,
                                        atr,
                                        tp1,
                                        target,
                                        room_r,
                                        float(sweep_seed["micro_low"]),
                                        seed,
                                    )

        recent_closed.append({"open": o, "high": h, "low": l, "close": c})

    result["v440_state"] = last_reason
    return result
