"""V4.3.1 timestamp-safe 15m micro-entry simulator.

A0 = V4.3 immediate baseline after 1h confirmation.
A1 = zone rejection + close back below zone midpoint.
A2 = micro-high liquidity sweep + bearish close back below sweep.
A3 = A1-style rejection followed by 15m micro-low break.

All micro triggers consume closed 15m bars and fill only at the next 15m open.
Each primary may receive at most one conditional C re-entry after a realized
stop. No future best-price selection and no parameter grid search.
"""
import math

import pandas as pd

from .v431_config import (
    V431_A3_BREAK_WAIT_BARS,
    V431_BREAK_BUFFER_ATR,
    V431_C_MAX_RISK_MULT,
    V431_C_MIN_BODY_ATR,
    V431_C_RECLAIM_BUFFER_ATR,
    V431_C_WAIT_HOURS,
    V431_COST_BPS,
    V431_FOLLOWTHROUGH_R,
    V431_HOLD_HOURS,
    V431_MAX_COST_R,
    V431_MAX_RISK_ATR,
    V431_MAX_STOP_PCT,
    V431_MIN_RISK_ATR,
    V431_NO_CHASE_ATR,
    V431_STOP_BUFFER_ATR,
    V431_STRUCTURAL_ROOM_R,
    V431_SWEEP_BUFFER_ATR,
    V431_TOUCH_TOLERANCE_ATR,
    V431_TRIGGER_WAIT_HOURS,
)

STEP = pd.Timedelta(minutes=15)
PRIMARY_MODES = ("A0", "A1", "A2", "A3")
STOP_STATES = ("SL_FIRST", "SL_SAME_BAR")
TERMINAL_STATES = ("TP2R_FIRST", "SL_FIRST", "SL_SAME_BAR", "TIME_EXIT")


def _num(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _empty(mode, state):
    prefix = f"v431_{mode}_"
    return {
        prefix + "state": state,
        prefix + "trigger": None,
        prefix + "trigger_time": None,
        prefix + "entry_time": None,
        prefix + "entry": None,
        prefix + "stop": None,
        prefix + "tp2": None,
        prefix + "risk_pct": None,
        prefix + "risk_atr": None,
        prefix + "cost_r": None,
        prefix + "gross_r": None,
        prefix + "net_r": None,
        prefix + "hold_bars": None,
        prefix + "exit_time": None,
        prefix + "exit_bar_index": None,
        prefix + "wait_bars": None,
        prefix + "entry_improvement_atr": None,
        prefix + "entry_vs_reference_atr": None,
        prefix + "structural_room_r": None,
        prefix + "structural_room_pass": 0,
        prefix + "ft_first_0_5r": None,
        prefix + "mfe_r_1h": None,
        prefix + "mae_r_1h": None,
        prefix + "mfe_r_4h": None,
        prefix + "mae_r_4h": None,
    }


def _next_bar(frame, i):
    return (
        i + 1 < len(frame)
        and frame.index[i + 1] == frame.index[i] + STEP
    )


def _contiguous_block(frame, start_idx, bars):
    if start_idx >= len(frame):
        return None
    end = min(len(frame), start_idx + bars)
    block = frame.iloc[start_idx:end]
    if len(block) < bars:
        return None
    expected = frame.index[start_idx]
    for t in block.index:
        if t != expected:
            return None
        expected += STEP
    return block


def _path_metrics(frame, start_idx, entry, risk):
    out = {
        "ft_first_0_5r": None,
        "mfe_r_1h": None,
        "mae_r_1h": None,
        "mfe_r_4h": None,
        "mae_r_4h": None,
    }
    block4 = _contiguous_block(frame, start_idx, 16)
    if block4 is None:
        return out
    block1 = block4.iloc[:4]
    for label, block in (("1h", block1), ("4h", block4)):
        low = float(block["low"].astype(float).min())
        high = float(block["high"].astype(float).max())
        out[f"mfe_r_{label}"] = round(max(0.0, (entry - low) / risk), 4)
        out[f"mae_r_{label}"] = round(max(0.0, (high - entry) / risk), 4)

    fav = entry - float(V431_FOLLOWTHROUGH_R) * risk
    adv = entry + float(V431_FOLLOWTHROUGH_R) * risk
    first = "NONE"
    for _, bar in block4.iterrows():
        hit_fav = float(bar["low"]) <= fav
        hit_adv = float(bar["high"]) >= adv
        if hit_fav and hit_adv:
            first = "AMBIGUOUS"
            break
        if hit_fav:
            first = "SHORT_0.5R_FIRST"
            break
        if hit_adv:
            first = "ADVERSE_0.5R_FIRST"
            break
    out["ft_first_0_5r"] = first
    return out


def _plan_reason(entry, stop, atr, enforce_micro=True):
    if any(x is None for x in (entry, stop, atr)):
        return "INVALID_PLAN"
    if entry <= 0 or stop <= entry or atr <= 0:
        return "INVALID_PLAN"
    risk = stop - entry
    if 100.0 * risk / entry > float(V431_MAX_STOP_PCT):
        return "SKIP_STOP_PCT"
    if enforce_micro:
        if risk / atr > float(V431_MAX_RISK_ATR):
            return "SKIP_RISK_TOO_WIDE"
        cost_r = float(V431_COST_BPS) / 10000.0 * entry / risk
        if cost_r > float(V431_MAX_COST_R):
            return "SKIP_COST_R"
    return None


def _simulate_trade(
    future15, start_idx, entry, stop, atr, mode, wait_bars,
    trigger, trigger_time, enforce_micro=True,
):
    reason = _plan_reason(entry, stop, atr, enforce_micro=enforce_micro)
    if reason:
        return _empty(mode, reason)
    if start_idx >= len(future15):
        return _empty(mode, "NO_NEXT_OPEN")

    out = _empty(mode, "INVALID_PLAN")
    prefix = f"v431_{mode}_"
    risk = stop - entry
    tp2 = entry - 2.0 * risk
    if tp2 <= 0:
        return out
    if float(future15.iloc[start_idx]["open"]) >= stop:
        return _empty(mode, "GAP_BEYOND_STOP")

    cost_r = float(V431_COST_BPS) / 10000.0 * entry / risk
    entry_time = future15.index[start_idx]
    out.update({
        prefix + "trigger": trigger,
        prefix + "trigger_time": None if trigger_time is None else trigger_time.isoformat(),
        prefix + "entry_time": entry_time.isoformat(),
        prefix + "entry": round(entry, 10),
        prefix + "stop": round(stop, 10),
        prefix + "tp2": round(tp2, 10),
        prefix + "risk_pct": round(100.0 * risk / entry, 4),
        prefix + "risk_atr": round(risk / atr, 4),
        prefix + "cost_r": round(cost_r, 5),
        prefix + "wait_bars": int(wait_bars),
    })
    path = _path_metrics(future15, start_idx, entry, risk)
    for key, value in path.items():
        out[prefix + key] = value

    end_time = entry_time + pd.Timedelta(hours=int(V431_HOLD_HOURS))
    expected = entry_time
    last_close = None
    bars = 0

    for i in range(start_idx, len(future15)):
        t = future15.index[i]
        if t >= end_time:
            break
        if t != expected:
            out[prefix + "state"] = "CENSORED_15M_GAP"
            return out
        bar = future15.iloc[i]
        o, h, l, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
        if not all(math.isfinite(x) for x in (o, h, l, c)):
            out[prefix + "state"] = "CENSORED_BAD_BAR"
            return out
        expected += STEP
        bars += 1
        last_close = c

        hit_sl = h >= stop
        hit_tp = l <= tp2
        if hit_sl:
            exit_price = max(o, stop)
            gross = (entry - exit_price) / risk
            state = "SL_SAME_BAR" if hit_tp else "SL_FIRST"
        elif hit_tp:
            gross = 2.0
            state = "TP2R_FIRST"
        else:
            continue

        out.update({
            prefix + "state": state,
            prefix + "gross_r": round(gross, 5),
            prefix + "net_r": round(gross - cost_r, 5),
            prefix + "hold_bars": bars,
            prefix + "exit_time": (t + STEP).isoformat(),
            prefix + "exit_bar_index": i,
        })
        return out

    if expected < end_time or last_close is None:
        out[prefix + "state"] = "CENSORED_INCOMPLETE_HORIZON"
        return out

    gross = (entry - last_close) / risk
    out.update({
        prefix + "state": "TIME_EXIT",
        prefix + "gross_r": round(gross, 5),
        prefix + "net_r": round(gross - cost_r, 5),
        prefix + "hold_bars": bars,
        prefix + "exit_time": end_time.isoformat(),
        prefix + "exit_bar_index": start_idx + bars - 1,
    })
    return out


def _bearish_rejection(bar, previous_close):
    o, h, l, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
    if not (h > l and c < o and c < previous_close):
        return False
    return c <= l + 0.45 * (h - l)


def _micro_stop(entry, trigger_high, atr):
    stop = max(
        float(trigger_high) + float(V431_STOP_BUFFER_ATR) * atr,
        entry + float(V431_MIN_RISK_ATR) * atr,
    )
    if stop - entry > float(V431_MAX_RISK_ATR) * atr:
        return None
    return stop


def _entry_constraints(entry, zone_lower, zone_upper, atr):
    if entry < zone_lower - float(V431_NO_CHASE_ATR) * atr:
        return "SKIP_CHASE"
    if entry > zone_upper + float(V431_TOUCH_TOLERANCE_ATR) * atr:
        return "SKIP_ZONE_RECLAIM"
    return None


def _attach_room(out, mode, structural_support):
    prefix = f"v431_{mode}_"
    entry = _num(out.get(prefix + "entry"))
    stop = _num(out.get(prefix + "stop"))
    support = _num(structural_support)
    if entry is None or stop is None or support is None or stop <= entry:
        return
    room = (entry - support) / (stop - entry)
    out[prefix + "structural_room_r"] = round(room, 4)
    out[prefix + "structural_room_pass"] = int(
        room >= float(V431_STRUCTURAL_ROOM_R)
    )


def _fill_micro(
    future15, i, features, mode, trigger, trigger_high, structural_support,
):
    if not _next_bar(future15, i):
        return _empty(mode, "NO_NEXT_OPEN")
    atr = float(features["atr_1h"])
    zone_lower = float(features["preferred_zone_lower"])
    zone_upper = float(features["preferred_zone_upper"])
    entry = float(future15.iloc[i + 1]["open"])
    reason = _entry_constraints(entry, zone_lower, zone_upper, atr)
    if reason:
        return _empty(mode, reason)
    stop = _micro_stop(entry, trigger_high, atr)
    if stop is None:
        return _empty(mode, "SKIP_RISK_TOO_WIDE")
    out = _simulate_trade(
        future15, i + 1, entry, stop, atr, mode, i + 1,
        trigger, future15.index[i], enforce_micro=True,
    )
    _attach_room(out, mode, structural_support)
    return out


def _scan_micro(features, hist15, future15, structural_support):
    results = {
        "A1": _empty("A1", "NO_15M_REJECTION"),
        "A2": _empty("A2", "NO_15M_SWEEP"),
        "A3": _empty("A3", "NO_MICRO_BOS"),
    }
    atr = _num(features.get("atr_1h"))
    zone_lower = _num(features.get("preferred_zone_lower"))
    zone_upper = _num(features.get("preferred_zone_upper"))
    if any(x is None for x in (atr, zone_lower, zone_upper)) or atr <= 0:
        return results
    if hist15 is None or len(hist15) < 8 or future15 is None or len(future15) < 2:
        return results

    hist15 = hist15.sort_index()
    future15 = future15.sort_index()
    zone_mid = (zone_lower + zone_upper) / 2.0
    tolerance = float(V431_TOUCH_TOLERANCE_ATR) * atr
    pre_high = float(hist15.tail(8)["high"].astype(float).max())
    sweep_level = max(zone_mid, pre_high)
    deadline = future15.index[0] + pd.Timedelta(hours=int(V431_TRIGGER_WAIT_HOURS))
    recent_closed = list(hist15.tail(6).to_dict("records"))
    a3_seed = None

    for i in range(0, len(future15) - 1):
        t = future15.index[i]
        if t >= deadline:
            break
        bar = future15.iloc[i]
        previous_close = (
            float(hist15.iloc[-1]["close"]) if i == 0
            else float(future15.iloc[i - 1]["close"])
        )
        o, h, l, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
        if not all(math.isfinite(x) for x in (o, h, l, c)):
            continue

        touched = h >= zone_lower - tolerance and l <= zone_upper + tolerance
        rejection = (
            touched
            and c < zone_mid
            and c <= zone_upper + tolerance
            and _bearish_rejection(bar, previous_close)
        )

        if results["A1"]["v431_A1_state"] == "NO_15M_REJECTION" and rejection:
            prior_high = max(
                [float(x["high"]) for x in recent_closed[-3:]] + [h]
            )
            results["A1"] = _fill_micro(
                future15, i, features, "A1", "REJECTION_CLOSE_BELOW_ZONE",
                prior_high, structural_support,
            )

        sweep = (
            touched
            and h >= sweep_level + float(V431_SWEEP_BUFFER_ATR) * atr
            and c < sweep_level
            and c < o
            and c <= zone_upper + tolerance
        )
        if results["A2"]["v431_A2_state"] == "NO_15M_SWEEP" and sweep:
            results["A2"] = _fill_micro(
                future15, i, features, "A2", "MICRO_HIGH_SWEEP",
                h, structural_support,
            )

        if a3_seed is None and rejection:
            prior_lows = [float(x["low"]) for x in recent_closed[-4:]]
            if prior_lows:
                a3_seed = {
                    "rejection_i": i,
                    "rejection_high": h,
                    "micro_low": min(prior_lows),
                }
        elif a3_seed is not None:
            bars_after = i - int(a3_seed["rejection_i"])
            if bars_after > int(V431_A3_BREAK_WAIT_BARS):
                a3_seed = None
            elif (
                bars_after >= 1
                and c < float(a3_seed["micro_low"]) - float(V431_BREAK_BUFFER_ATR) * atr
                and c < o
            ):
                trigger_high = max(float(a3_seed["rejection_high"]), h)
                results["A3"] = _fill_micro(
                    future15, i, features, "A3", "REJECTION_THEN_MICRO_BOS",
                    trigger_high, structural_support,
                )
                a3_seed = None

        recent_closed.append({"open": o, "high": h, "low": l, "close": c})

    return results


def _baseline(features, future15, structural_support):
    if int(features.get("v428_entry_confirmed") or 0) != 1:
        return _empty("A0", "NO_1H_CONFIRMATION")
    if future15 is None or len(future15) < 1:
        return _empty("A0", "NO_FUTURE_15M")
    atr = _num(features.get("atr_1h"))
    stop = _num(features.get("v428_confirm_stop_reference"))
    entry = _num(future15.iloc[0]["open"])
    if any(x is None for x in (atr, stop, entry)):
        return _empty("A0", "INVALID_PLAN")
    out = _simulate_trade(
        future15, 0, entry, stop, atr, "A0", 0,
        "V430_IMMEDIATE_BASELINE", None, enforce_micro=False,
    )
    _attach_room(out, "A0", structural_support)
    return out


def _reentry(features, future15, primary, primary_mode, mode, structural_support):
    p = f"v431_{primary_mode}_"
    if primary.get(p + "state") not in STOP_STATES:
        return _empty(mode, "PRIMARY_NOT_STOPPED")
    stop_idx = primary.get(p + "exit_bar_index")
    old_stop = _num(primary.get(p + "stop"))
    old_entry = _num(primary.get(p + "entry"))
    atr = _num(features.get("atr_1h"))
    if stop_idx is None or any(x is None for x in (old_stop, old_entry, atr)):
        return _empty(mode, "INVALID_PRIMARY")
    old_risk = old_stop - old_entry
    if old_risk <= 0:
        return _empty(mode, "INVALID_PRIMARY")

    invalidation = old_stop - float(V431_C_RECLAIM_BUFFER_ATR) * atr
    start = int(stop_idx) + 1
    if start >= len(future15):
        return _empty(mode, "NO_REENTRY_FUTURE")
    deadline = future15.index[int(stop_idx)] + pd.Timedelta(hours=int(V431_C_WAIT_HOURS))
    highs = [float(future15.iloc[int(stop_idx)]["high"])]

    for i in range(start, len(future15) - 1):
        if future15.index[i] >= deadline:
            break
        bar = future15.iloc[i]
        prev = future15.iloc[i - 1]
        o, h, l, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
        highs.append(h)
        if not _next_bar(future15, i):
            continue
        if not (float(prev["close"]) >= invalidation and c < invalidation):
            continue
        if o - c < float(V431_C_MIN_BODY_ATR) * atr:
            continue
        if not _bearish_rejection(bar, float(prev["close"])):
            continue

        entry = float(future15.iloc[i + 1]["open"])
        stop = max(
            old_stop,
            max(highs) + float(V431_STOP_BUFFER_ATR) * atr,
            entry + float(V431_MIN_RISK_ATR) * atr,
        )
        risk = stop - entry
        if risk > float(V431_C_MAX_RISK_MULT) * old_risk:
            return _empty(mode, "SKIP_REENTRY_RISK_MULT")
        if risk > float(V431_MAX_RISK_ATR) * atr:
            return _empty(mode, "SKIP_REENTRY_RISK_ATR")
        out = _simulate_trade(
            future15, i + 1, entry, stop, atr, mode,
            i + 1 - start, "BEARISH_INVALIDATION_RECLAIM",
            future15.index[i], enforce_micro=True,
        )
        _attach_room(out, mode, structural_support)
        return out
    return _empty(mode, "NO_RECLAIM_CONFIRMATION")


def evaluate_v431_entries(features, hist15, future15, support):
    result = {}
    structural_support = (support or {}).get("v430_support_structural")

    a0 = _baseline(features, future15, structural_support)
    result.update(a0)
    micro = _scan_micro(features, hist15, future15, structural_support)
    for mode in ("A1", "A2", "A3"):
        result.update(micro[mode])

    atr = _num(features.get("atr_1h"))
    baseline_entry = _num(a0.get("v431_A0_entry"))
    reference = _num(features.get("v428_confirm_entry_reference"))
    if atr is not None and atr > 0:
        for mode in PRIMARY_MODES:
            key = f"v431_{mode}_"
            entry = _num(result.get(key + "entry"))
            if entry is None:
                continue
            if baseline_entry is not None:
                result[key + "entry_improvement_atr"] = round(
                    (entry - baseline_entry) / atr, 4
                )
            if reference is not None:
                result[key + "entry_vs_reference_atr"] = round(
                    (entry - reference) / atr, 4
                )

    for primary_mode in PRIMARY_MODES:
        c_mode = primary_mode + "C"
        c = _reentry(
            features, future15, result, primary_mode, c_mode, structural_support
        )
        result.update(c)
        pnet = _num(result.get(f"v431_{primary_mode}_net_r"))
        cnet = _num(c.get(f"v431_{c_mode}_net_r"))
        result[f"v431_{primary_mode}_plus_C_net_r"] = (
            None if pnet is None else round(pnet + (cnet or 0.0), 5)
        )
        result[f"v431_{primary_mode}_plus_C_trades"] = (
            0 if pnet is None else 1 + int(cnet is not None)
        )
        result[f"v431_{primary_mode}_plus_C_state"] = (
            "NO_PRIMARY_FILL" if pnet is None
            else ("WITH_REENTRY" if cnet is not None else "PRIMARY_ONLY")
        )
    return result
