"""M3 V1 — Intraday Bearish Pullback Continuation.

Causal research chain:
4H bearish context -> 1H bearish impulse -> controlled pullback into resistance
-> failed reclaim/rejection -> 15m bearish confirmation -> next 15m open.

The user remains the decision maker in live use. Backtest entries are only a
standardized benchmark for comparing signal quality.
"""
import math

import pandas as pd

from .config import (
    BACKTEST_FEE_BPS_ROUND_TRIP,
    BACKTEST_SLIPPAGE_BPS_ROUND_TRIP,
)
from .indicators import atr, bearish_rejection, ema, structure_snapshot
from .m3_v1_config import (
    M3_CONFIRM_WINDOW_MINUTES,
    M3_HOLD_HOURS,
    M3_IMPULSE_LOOKBACK_1H,
    M3_MAX_EMA20_DISTANCE_ATR,
    M3_MAX_PULLBACK_RETRACE,
    M3_MAX_RESISTANCE_DISTANCE_ATR,
    M3_MAX_RISK_ATR,
    M3_MIN_4H_BEAR_SCORE,
    M3_MIN_IMPULSE_ATR,
    M3_MIN_PULLBACK_RETRACE,
    M3_MIN_RISK_ATR,
    M3_STOP_BUFFER_ATR,
    M3_TARGET_ATR_VARIANTS,
)

STEP = pd.Timedelta(minutes=15)


def _num(x):
    try:
        y = float(x)
        return y if math.isfinite(y) else None
    except (TypeError, ValueError):
        return None


def _four_bear_context(four):
    if four is None or len(four) < 60:
        return None
    snap = structure_snapshot(four)
    close = four["close"].astype(float)
    e20 = ema(close, 20)
    e50 = ema(close, 50)
    slope_down = len(e20) >= 5 and float(e20.iloc[-1]) < float(e20.iloc[-5])
    below20 = float(snap["close"]) < float(snap["ema20"])
    ema_stack_bear = float(e20.iloc[-1]) < float(e50.iloc[-1]) or slope_down
    structure_bear = bool(snap["lower_high"] or snap["lower_low"])

    score = int(below20) + int(ema_stack_bear) + int(structure_bear)
    return {
        "bear_score": score,
        "below_ema20": int(below20),
        "ema_stack_or_slope_bear": int(ema_stack_bear),
        "structure_bear": int(structure_bear),
        "macro_bear": int(bool(snap["macro_bear"])),
        "close": float(snap["close"]),
        "ema20": float(snap["ema20"]),
        "ema50": float(snap["ema50"]),
    }


def _find_impulse_pullback(one):
    if one is None or len(one) < max(40, M3_IMPULSE_LOOKBACK_1H + 5):
        return None

    view = one.iloc[-int(M3_IMPULSE_LOOKBACK_1H):].copy()
    a = _num(atr(one).iloc[-1])
    if a is None or a <= 0:
        return None

    # Search recent troughs that leave 1-5 bars for a pullback.
    best = None
    n = len(view)
    for trough_pos in range(max(3, n - 6), n - 1):
        prior = view.iloc[:trough_pos]
        if len(prior) < 3:
            continue

        # Peak must be before trough and not too far back.
        peak_start = max(0, trough_pos - 8)
        peak_slice = view.iloc[peak_start:trough_pos]
        if peak_slice.empty:
            continue
        peak_rel = int(peak_slice["high"].astype(float).values.argmax())
        peak_pos = peak_start + peak_rel
        peak = float(view.iloc[peak_pos]["high"])
        trough = float(view.iloc[trough_pos]["low"])
        impulse = peak - trough
        impulse_atr = impulse / a
        if impulse_atr < float(M3_MIN_IMPULSE_ATR):
            continue

        current = float(view.iloc[-1]["close"])
        retrace = (current - trough) / max(impulse, 1e-12)
        if not (
            float(M3_MIN_PULLBACK_RETRACE)
            <= retrace
            <= float(M3_MAX_PULLBACK_RETRACE)
        ):
            continue

        # Previous local support likely broken during the impulse.
        pre = view.iloc[max(0, peak_pos - 6):trough_pos]
        prior_support = (
            float(pre["low"].astype(float).min())
            if not pre.empty
            else trough
        )

        candidate = {
            "atr": a,
            "peak_pos": peak_pos,
            "trough_pos": trough_pos,
            "peak_time": view.index[peak_pos],
            "trough_time": view.index[trough_pos],
            "peak": peak,
            "trough": trough,
            "impulse_atr": impulse_atr,
            "pullback_retrace": retrace,
            "prior_support": prior_support,
            "pullback_bars": n - 1 - trough_pos,
        }
        if best is None or candidate["impulse_atr"] > best["impulse_atr"]:
            best = candidate

    return best


def _resistance_and_rejection(one, impulse):
    snap = structure_snapshot(one)
    a = float(impulse["atr"])
    current = float(one["close"].iloc[-1])
    ema20 = float(snap["ema20"])
    prior_support = float(impulse["prior_support"])

    candidates = [
        ("EMA20_1H", ema20, abs(current - ema20) / a),
        (
            "BROKEN_SUPPORT_1H",
            prior_support,
            abs(current - prior_support) / a,
        ),
    ]
    candidates.sort(key=lambda x: x[2])
    source, resistance, distance = candidates[0]

    near = distance <= float(M3_MAX_RESISTANCE_DISTANCE_ATR)
    ema_distance_below = max(0.0, ema20 - current) / a
    if ema_distance_below > float(M3_MAX_EMA20_DISTANCE_ATR):
        return {
            "ok": False,
            "reason": "OVEREXTENDED_BELOW_EMA20",
            "ema20_distance_atr": ema_distance_below,
        }

    last = one.iloc[-1]
    prev = one.iloc[-2]
    bearish_close = float(last["close"]) < float(last["open"])
    reject = bearish_rejection(last)
    failed_reclaim = bool(
        float(last["high"]) >= resistance - 0.25 * a
        and float(last["close"]) <= resistance + 0.10 * a
        and bearish_close
    )
    lower_close = float(last["close"]) < float(prev["close"])
    lower_high_proxy = bool(snap["lower_high"])

    quality = 0
    quality += int(near)
    quality += int(failed_reclaim or reject)
    quality += int(lower_close or lower_high_proxy)

    return {
        "ok": bool(near and (failed_reclaim or reject or lower_high_proxy)),
        "reason": "OK" if near else "TOO_FAR_FROM_RESISTANCE",
        "resistance_source": source,
        "resistance": resistance,
        "resistance_distance_atr": distance,
        "ema20_distance_atr": ema_distance_below,
        "failed_reclaim": int(failed_reclaim),
        "bearish_rejection": int(reject),
        "lower_high_proxy": int(lower_high_proxy),
        "lower_close": int(lower_close),
        "quality_points": quality,
    }


def _find_15m_confirmation(future15, signal_time):
    if future15 is None or future15.empty:
        return {"state": "NO_15M_DATA"}

    start = pd.Timestamp(signal_time)
    deadline = start + pd.Timedelta(minutes=int(M3_CONFIRM_WINDOW_MINUTES))
    rows = future15.loc[future15.index >= start]
    if rows.empty:
        return {"state": "NO_15M_DATA"}

    for i in range(1, len(rows) - 1):
        t = rows.index[i]
        close_time = t + STEP
        if close_time > deadline:
            break

        row = rows.iloc[i]
        prev = rows.iloc[i - 1]
        o, h, l, c = (float(row[k]) for k in ("open", "high", "low", "close"))
        prev_close = float(prev["close"])
        prev_low = float(prev["low"])

        bearish = c < o and c < prev_close
        strong = bearish and c < prev_low
        if not bearish:
            continue

        next_i = i + 1
        entry_time = rows.index[next_i]
        entry = float(rows.iloc[next_i]["open"])
        return {
            "state": "CONFIRMED",
            "tier": "A" if strong else "B",
            "confirm_time": close_time,
            "entry_time": entry_time,
            "entry_idx": next_i,
            "entry": entry,
            "confirm_high": h,
            "confirm_low": l,
            "confirm_close": c,
            "strong_bos": int(strong),
        }

    return {"state": "NO_CONFIRMATION"}


def _finish(seed, prefix, state, gross_r, cost_r, bars, exit_time, mfe_r, mae_r):
    out = dict(seed)
    out.update({
        f"{prefix}_state": state,
        f"{prefix}_gross_r": round(float(gross_r), 5),
        f"{prefix}_net_r": round(float(gross_r) - float(cost_r), 5),
        f"{prefix}_hold_bars": int(bars),
        f"{prefix}_exit_time": pd.Timestamp(exit_time).isoformat(),
        f"{prefix}_mfe_r": round(float(mfe_r), 5),
        f"{prefix}_mae_r": round(float(mae_r), 5),
    })
    return out


def _simulate_variant(future15, entry_idx, entry, stop, atr_value, target_atr, seed):
    tag = str(target_atr).replace(".", "_")
    prefix = f"m3_t{tag}"
    risk = float(stop) - float(entry)
    target = float(entry) - float(target_atr) * float(atr_value)
    if risk <= 0:
        out = dict(seed)
        out[f"{prefix}_state"] = "INVALID_RISK"
        return out

    total_cost_bps = (
        float(BACKTEST_FEE_BPS_ROUND_TRIP)
        + float(BACKTEST_SLIPPAGE_BPS_ROUND_TRIP)
    )
    cost_r = float(entry) * total_cost_bps / 10000.0 / risk
    target_r = (float(entry) - target) / risk

    out = dict(seed)
    out.update({
        f"{prefix}_state": "OPEN",
        f"{prefix}_target_atr": float(target_atr),
        f"{prefix}_target": round(target, 10),
        f"{prefix}_target_r": round(target_r, 5),
        f"{prefix}_cost_r": round(cost_r, 5),
        f"{prefix}_gross_r": None,
        f"{prefix}_net_r": None,
        f"{prefix}_hold_bars": None,
        f"{prefix}_exit_time": None,
        f"{prefix}_mfe_r": None,
        f"{prefix}_mae_r": None,
    })

    entry_time = future15.index[int(entry_idx)]
    end_time = entry_time + pd.Timedelta(hours=int(M3_HOLD_HOURS))
    last_close = float(entry)
    bars = 0
    mfe = 0.0
    mae = 0.0

    for i in range(int(entry_idx), len(future15)):
        t = future15.index[i]
        if t >= end_time:
            break
        row = future15.iloc[i]
        o, h, l, c = (float(row[k]) for k in ("open", "high", "low", "close"))
        bars += 1
        last_close = c
        mfe = max(mfe, max(0.0, float(entry) - l) / risk)
        mae = max(mae, max(0.0, h - float(entry)) / risk)

        hit_sl = h >= float(stop)
        hit_tp = l <= target
        if hit_sl and hit_tp:
            return _finish(
                out, prefix, "SL_FIRST_SAME_BAR", -1.0, cost_r,
                bars, t + STEP, mfe, mae
            )
        if hit_sl:
            gross = (float(entry) - max(o, float(stop))) / risk
            return _finish(
                out, prefix, "SL_FIRST", gross, cost_r,
                bars, t + STEP, mfe, mae
            )
        if hit_tp:
            gross = target_r
            return _finish(
                out, prefix, "TARGET", gross, cost_r,
                bars, t + STEP, mfe, mae
            )

    gross = (float(entry) - last_close) / risk
    return _finish(
        out, prefix, "TIME_EXIT_24H", gross, cost_r,
        bars, min(end_time, future15.index[-1] + STEP), mfe, mae
    )


def _build_24h_path(future15, entry_idx, entry, atr_value, stop):
    """Observe raw post-entry price path for 24h without censoring at SL/TP.

    Each hourly checkpoint records close displacement for a short plus
    cumulative favorable/adverse excursion. This is diagnostic only.
    """
    if future15 is None or future15.empty:
        return []

    risk = max(float(stop) - float(entry), 1e-12)
    a = max(float(atr_value), 1e-12)
    rows = future15.iloc[int(entry_idx):]
    if rows.empty:
        return []

    entry_time = rows.index[0]
    checkpoints = []
    running_low = float(entry)
    running_high = float(entry)

    for hour in range(1, 25):
        cutoff = entry_time + pd.Timedelta(hours=hour)
        window = rows.loc[rows.index < cutoff]
        if window.empty:
            continue

        running_low = min(running_low, float(window["low"].astype(float).min()))
        running_high = max(running_high, float(window["high"].astype(float).max()))
        last_close = float(window["close"].iloc[-1])

        close_move = float(entry) - last_close
        mfe = max(0.0, float(entry) - running_low)
        mae = max(0.0, running_high - float(entry))

        checkpoints.append({
            "hour": hour,
            "checkpoint_time": cutoff.isoformat(),
            "close": round(last_close, 10),
            "short_close_atr": round(close_move / a, 5),
            "short_close_r": round(close_move / risk, 5),
            "cum_mfe_atr": round(mfe / a, 5),
            "cum_mae_atr": round(mae / a, 5),
            "cum_mfe_r": round(mfe / risk, 5),
            "cum_mae_r": round(mae / risk, 5),
        })
    return checkpoints


def evaluate_m3_v1(one_closed, four_closed, future15, signal_time):
    out = {
        "m3_state": "NO_SETUP",
        "m3_signal_time": pd.Timestamp(signal_time).isoformat(),
        "m3_4h_bear_score": None,
        "m3_impulse_atr": None,
        "m3_pullback_retrace": None,
        "m3_pullback_bars": None,
        "m3_resistance_source": None,
        "m3_resistance": None,
        "m3_resistance_distance_atr": None,
        "m3_failed_reclaim": None,
        "m3_bearish_rejection": None,
        "m3_lower_high_proxy": None,
        "m3_confirmation_state": None,
        "m3_tier": None,
        "m3_confirm_time": None,
        "m3_entry_time": None,
        "m3_entry": None,
        "m3_stop": None,
        "m3_risk_atr": None,
        "m3_risk_pct": None,
        "m3_atr": None,
    }

    four_ctx = _four_bear_context(four_closed)
    if four_ctx is None:
        out["m3_state"] = "NO_4H_CONTEXT"
        return out
    out.update({
        "m3_4h_bear_score": four_ctx["bear_score"],
        "m3_4h_below_ema20": four_ctx["below_ema20"],
        "m3_4h_ema_bear": four_ctx["ema_stack_or_slope_bear"],
        "m3_4h_structure_bear": four_ctx["structure_bear"],
    })
    if int(four_ctx["bear_score"]) < int(M3_MIN_4H_BEAR_SCORE):
        out["m3_state"] = "FAIL_4H_BEAR"
        return out

    impulse = _find_impulse_pullback(one_closed)
    if impulse is None:
        out["m3_state"] = "NO_IMPULSE_PULLBACK"
        return out
    out.update({
        "m3_impulse_atr": round(float(impulse["impulse_atr"]), 4),
        "m3_pullback_retrace": round(float(impulse["pullback_retrace"]), 4),
        "m3_pullback_bars": int(impulse["pullback_bars"]),
        "m3_impulse_peak_time": pd.Timestamp(impulse["peak_time"]).isoformat(),
        "m3_impulse_trough_time": pd.Timestamp(impulse["trough_time"]).isoformat(),
        "m3_impulse_peak": round(float(impulse["peak"]), 10),
        "m3_impulse_trough": round(float(impulse["trough"]), 10),
        "m3_atr": round(float(impulse["atr"]), 10),
    })

    rejection = _resistance_and_rejection(one_closed, impulse)
    out.update({
        "m3_resistance_source": rejection.get("resistance_source"),
        "m3_resistance": rejection.get("resistance"),
        "m3_resistance_distance_atr": rejection.get("resistance_distance_atr"),
        "m3_ema20_distance_atr": rejection.get("ema20_distance_atr"),
        "m3_failed_reclaim": rejection.get("failed_reclaim"),
        "m3_bearish_rejection": rejection.get("bearish_rejection"),
        "m3_lower_high_proxy": rejection.get("lower_high_proxy"),
        "m3_rejection_quality_points": rejection.get("quality_points"),
    })
    if not rejection.get("ok"):
        out["m3_state"] = rejection.get("reason") or "NO_REJECTION"
        return out

    # A 1H-only candidate is useful for live observation even if 15m does not
    # confirm. It is labelled C and is not benchmark-entered.
    out["m3_state"] = "CANDIDATE_C"
    out["m3_tier"] = "C"

    confirm = _find_15m_confirmation(future15, signal_time)
    out["m3_confirmation_state"] = confirm.get("state")
    if confirm.get("state") != "CONFIRMED":
        return out

    entry = float(confirm["entry"])
    a = float(impulse["atr"])
    post_trough = one_closed.loc[one_closed.index >= impulse["trough_time"]]
    swing_high = max(
        float(post_trough["high"].astype(float).max()),
        float(rejection["resistance"]),
        float(confirm["confirm_high"]),
    )
    raw_stop = swing_high + float(M3_STOP_BUFFER_ATR) * a
    min_stop = entry + float(M3_MIN_RISK_ATR) * a
    stop = max(raw_stop, min_stop)
    risk_atr = (stop - entry) / a

    out.update({
        "m3_state": "ENTRY_BENCHMARK",
        "m3_tier": confirm["tier"],
        "m3_confirm_time": pd.Timestamp(confirm["confirm_time"]).isoformat(),
        "m3_entry_time": pd.Timestamp(confirm["entry_time"]).isoformat(),
        "m3_entry": round(entry, 10),
        "m3_stop": round(stop, 10),
        "m3_risk_atr": round(risk_atr, 4),
        "m3_risk_pct": round(100.0 * (stop - entry) / max(entry, 1e-12), 4),
        "m3_strong_15m_bos": confirm.get("strong_bos"),
    })

    if risk_atr > float(M3_MAX_RISK_ATR):
        out["m3_state"] = "SKIP_RISK_TOO_WIDE"
        return out

    # V1.1 diagnostic: raw 24h path from benchmark entry. This intentionally
    # ignores theoretical exits so we can study what price did after entry.
    out["m3_path_24h"] = _build_24h_path(
        future15,
        int(confirm["entry_idx"]),
        entry,
        a,
        stop,
    )

    for target_atr in M3_TARGET_ATR_VARIANTS:
        out.update(
            _simulate_variant(
                future15,
                int(confirm["entry_idx"]),
                entry,
                stop,
                a,
                float(target_atr),
                {},
            )
        )
    return out
