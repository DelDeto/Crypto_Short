"""V4.2.2 discretionary Short scanner.

Design goals:
- Separate SHORT_BIAS from SHORT_NOW.
- Do not reward bearishness enough to justify a bottom-chasing entry.
- Continuation requires an actual pullback/retest to broken support.
- Add explicit rebound/exhaustion risk after sharp breakdowns.
- Slippage remains advisory and never rejects a candidate.

Everything in this module is signal-time safe. No future candles are used.
"""

import math

from .config import BACKTEST_FEE_BPS_ROUND_TRIP
from .indicators import atr, ema, return_pct, structure_snapshot, volume_ratio
from .v4_regime import route_v4_regime
from .v42_entry import build_v42_zone
from .v42_setup import route_v42_setup
from .v422_config import (
    V422_BOTTOM_BLOCK_SCORE,
    V422_BREAKDOWN_MAX_AGE_1H,
    V422_CAPITULATION_RANGE_ATR,
    V422_CAPITULATION_VOL_RATIO,
    V422_DROP_LEG_EXTREME_ATR,
    V422_EMA_EXTENDED_ATR,
    V422_FAST_DROP_ATR,
    V422_MIN_EMIT_SCORE,
    V422_MIN_SHORT_NOW_SCORE,
    V422_PULLBACK_MAX_BELOW_LEVEL_ATR,
    V422_PULLBACK_TOUCH_ATR,
    V422_READY_ZONE_DISTANCE_ATR,
    V422_RECENT_LOW_CAUTION_ATR,
    V422_RECENT_LOW_NEAR_ATR,
    V422_REFERENCE_STOP_BUFFER_ATR,
    V422_SLIPPAGE_BPS_REFERENCE,
    V422_SUPPORT_BLOCK_ATR,
)


def _clamp(value, lo=0.0, hi=100.0):
    return max(lo, min(hi, float(value)))


def _range_position(one, bars):
    view = one.tail(max(10, int(bars)))
    low = float(view["low"].min())
    high = float(view["high"].max())
    current = float(view["close"].iloc[-1])
    width = high - low
    if width <= 0:
        return 0.5
    return _clamp((current - low) / width, 0.0, 1.0)


def _preferred_zone(base, setup, one):
    current = float(one["close"].iloc[-1])
    a1 = float(atr(one).iloc[-1])
    setup_type = str((setup or {}).get("v42_setup") or "")

    # Continuation reference is the broken support itself. Do not substitute
    # a generic EMA pullback and call it a completed breakdown retest.
    if setup_type == "BEAR_CONTINUATION_RETEST":
        breakdown = base.get("breakdown_retest") or {}
        level = breakdown.get("level")
        if level is not None:
            level = float(level)
            return {
                "lower": level - 0.12 * a1,
                "upper": level + 0.18 * a1,
                "mid": level,
                "source": "BROKEN_SUPPORT_RETEST",
                "signal_price": current,
                "atr_1h": a1,
            }

    zone = build_v42_zone(setup, base, one) if setup is not None else None
    if zone is not None:
        return dict(zone)

    supplies = []
    for source, raw, priority in (
        ("SUPPLY_1H", base.get("supply_1h") or {}, 1),
        ("SUPPLY_4H", base.get("supply_4h") or {}, 2),
    ):
        if raw.get("lower") is None or raw.get("upper") is None:
            continue
        lower = float(raw["lower"])
        upper = float(raw["upper"])
        if upper < current - 0.20 * a1:
            continue
        if lower <= current <= upper:
            distance = 0.0
        elif current < lower:
            distance = (lower - current) / max(a1, 1e-12)
        else:
            distance = (current - upper) / max(a1, 1e-12)
        supplies.append({
            "lower": lower,
            "upper": upper,
            "mid": (lower + upper) / 2.0,
            "source": source,
            "priority": priority,
            "signal_price": current,
            "atr_1h": a1,
            "distance_atr1h": distance,
        })
    if supplies:
        supplies.sort(key=lambda z: (z["priority"], z["distance_atr1h"]))
        return supplies[0]

    e20 = float(ema(one["close"].astype(float), 20).iloc[-1])
    return {
        "lower": e20 - 0.18 * a1,
        "upper": e20 + 0.18 * a1,
        "mid": e20,
        "source": "EMA20_PULLBACK_REFERENCE",
        "signal_price": current,
        "atr_1h": a1,
    }


def _directional_bias_score(s1, s4, regime, relative_4h, relative_24h):
    # Structure is deliberately capped. A deeply bearish chart may have a
    # strong bias but must not automatically become SHORT_NOW.
    score = 0.0
    if s4["ema_bear"]:
        score += 4.0
    if s4["lower_high"]:
        score += 3.0
    if s4["lower_low"]:
        score += 2.0
    if s1["ema_bear"]:
        score += 3.0
    if s1["lower_high"]:
        score += 2.0
    if s1["lower_low"]:
        score += 1.0

    if relative_4h <= -1.0:
        score += 2.0
    if relative_24h <= -3.0:
        score += 2.0
    if relative_24h <= -7.0:
        score += 1.0

    if regime.get("risk_state") == "RISK_OFF":
        score += 2.0
    if regime.get("trend_state") == "BEAR":
        score += 2.0
    if regime.get("trend_state") == "BULL":
        score -= 4.0

    return _clamp(score, 0.0, 22.0)


def _continuation_pullback(base, one, a1):
    breakdown = base.get("breakdown_retest") or {}
    level = breakdown.get("level")
    bars_ago = int(breakdown.get("bars_ago") or 999)
    if (
        not breakdown.get("breakdown")
        or level is None
        or bars_ago > V422_BREAKDOWN_MAX_AGE_1H
    ):
        return {
            "eligible": False,
            "ready": False,
            "reason": "NO_FRESH_BREAKDOWN",
            "level": level,
        }

    level = float(level)
    current = float(one["close"].iloc[-1])
    high = float(one["high"].iloc[-1])
    prev_close = (
        float(one["close"].iloc[-2])
        if len(one) >= 2
        else current
    )

    distance_below = (level - current) / max(a1, 1e-12)
    touched = high >= level - V422_PULLBACK_TOUCH_ATR * a1
    not_too_far_below = distance_below <= V422_PULLBACK_MAX_BELOW_LEVEL_ATR
    held_below = current <= level + 0.10 * a1
    rejection = bool(
        current < prev_close
        or bool(base.get("bearish_rejection"))
    )

    ready = bool(
        touched
        and not_too_far_below
        and held_below
        and rejection
    )

    if ready:
        reason = "PULLBACK_RETEST_REJECTED"
    elif distance_below > V422_PULLBACK_MAX_BELOW_LEVEL_ATR:
        reason = "BREAKDOWN_EXTENDED_WAIT_PULLBACK"
    elif not touched:
        reason = "NO_PULLBACK_TOUCH"
    elif not held_below:
        reason = "BROKEN_LEVEL_RECLAIMED"
    else:
        reason = "PULLBACK_NOT_REJECTED"

    return {
        "eligible": True,
        "ready": ready,
        "reason": reason,
        "level": level,
        "bars_ago": bars_ago,
        "distance_below_level_atr": round(distance_below, 4),
        "touched": touched,
        "held_below": held_below,
        "rejection": rejection,
    }


def _rebound_bottom_risk(base, one, current, a1, nearest_support):
    close = one["close"].astype(float)
    high = one["high"].astype(float)
    low = one["low"].astype(float)

    r4 = float(return_pct(close, 4))
    r12 = float(return_pct(close, 12))
    r24 = float(return_pct(close, 24))

    e20 = float(ema(close, 20).iloc[-1])
    below_ema_atr = max(0.0, (e20 - current) / max(a1, 1e-12))

    low12 = float(low.tail(12).min())
    low24 = float(low.tail(24).min())
    high12 = float(high.tail(12).max())
    dist_low12_atr = (current - low12) / max(a1, 1e-12)
    dist_low24_atr = (current - low24) / max(a1, 1e-12)
    drop_leg_atr = max(0.0, (high12 - current) / max(a1, 1e-12))

    close3_start = float(close.iloc[-4]) if len(close) >= 4 else float(close.iloc[0])
    fast_drop_atr = max(0.0, (close3_start - current) / max(a1, 1e-12))

    bottom = 0.0
    rebound = 0.0
    reasons = []

    if dist_low12_atr <= V422_RECENT_LOW_NEAR_ATR:
        bottom += 6.0
        reasons.append("AT_12H_LOW")
    elif dist_low12_atr <= V422_RECENT_LOW_CAUTION_ATR:
        bottom += 3.0
        reasons.append("NEAR_12H_LOW")

    if dist_low24_atr <= V422_RECENT_LOW_NEAR_ATR:
        bottom += 4.0
        reasons.append("AT_24H_LOW")

    if drop_leg_atr >= V422_DROP_LEG_EXTREME_ATR:
        rebound += 4.0
        reasons.append("LARGE_DOWNSIDE_LEG")

    if fast_drop_atr >= V422_FAST_DROP_ATR:
        rebound += 4.0
        reasons.append("FAST_3H_DROP")

    if below_ema_atr >= V422_EMA_EXTENDED_ATR:
        bottom += 4.0
        reasons.append("EXTENDED_BELOW_EMA20")

    support_distance_atr = None
    if nearest_support is not None and float(nearest_support) < current:
        support_distance_atr = (
            current - float(nearest_support)
        ) / max(a1, 1e-12)
        if support_distance_atr < V422_SUPPORT_BLOCK_ATR:
            bottom += 6.0
            reasons.append("SUPPORT_TOO_CLOSE")
    else:
        bottom += 2.0
        reasons.append("SUPPORT_UNKNOWN")

    last = one.iloc[-1]
    o = float(last["open"])
    h = float(last["high"])
    l = float(last["low"])
    c = float(last["close"])
    rng = max(h - l, 1e-12)
    lower_wick_ratio = (
        min(o, c) - l
    ) / rng
    range_atr = rng / max(a1, 1e-12)
    vr = float(volume_ratio(one))

    if (
        range_atr >= V422_CAPITULATION_RANGE_ATR
        and vr >= V422_CAPITULATION_VOL_RATIO
        and lower_wick_ratio >= 0.35
    ):
        rebound += 5.0
        reasons.append("CAPITULATION_REJECTION")

    if r4 <= -8.0:
        rebound += 4.0
        reasons.append("4H_DROP_EXTREME")
    elif r4 <= -5.0:
        rebound += 2.0
        reasons.append("4H_DROP_LARGE")

    if r12 <= -15.0:
        rebound += 3.0
        reasons.append("12H_DROP_EXTREME")

    # Being in the bottom of the recent range is useful only as a penalty.
    range_pos_24h = _range_position(one, 24)
    if range_pos_24h <= 0.15:
        bottom += 4.0
        reasons.append("BOTTOM_15PCT_OF_24H_RANGE")

    total = bottom + rebound
    return {
        "bottom_risk": round(bottom, 3),
        "rebound_risk": round(rebound, 3),
        "anti_bottom_total": round(total, 3),
        "bottom_reasons": reasons,
        "return_4h_pct": round(r4, 4),
        "return_12h_pct": round(r12, 4),
        "return_24h_pct": round(r24, 4),
        "below_ema20_atr": round(below_ema_atr, 4),
        "distance_12h_low_atr": round(dist_low12_atr, 4),
        "distance_24h_low_atr": round(dist_low24_atr, 4),
        "drop_leg_12h_atr": round(drop_leg_atr, 4),
        "fast_drop_3h_atr": round(fast_drop_atr, 4),
        "range_position_24h": round(range_pos_24h, 4),
        "support_distance_atr": (
            None
            if support_distance_atr is None
            else round(support_distance_atr, 4)
        ),
        "last_range_atr": round(range_atr, 4),
        "last_lower_wick_ratio": round(lower_wick_ratio, 4),
        "volume_ratio_1h": round(vr, 4),
    }


def _location_and_trigger(base, zone, one, setup, continuation):
    current = float(one["close"].iloc[-1])
    a1 = float(atr(one).iloc[-1])

    location = 0.0
    distance = None
    if zone is not None:
        lower = float(zone["lower"])
        upper = float(zone["upper"])
        if lower <= current <= upper:
            distance = 0.0
            location += 16.0
        elif current < lower:
            distance = (lower - current) / max(a1, 1e-12)
            if distance <= 0.35:
                location += 13.0
            elif distance <= 0.75:
                location += 8.0
            elif distance <= 1.25:
                location += 4.0
        else:
            distance = (current - upper) / max(a1, 1e-12)
            if distance <= 0.20:
                location += 8.0

        source = str(zone.get("source") or "")
        if source in ("SUPPLY_1H", "SWEEP_RETEST"):
            location += 10.0
        elif source in ("SUPPLY_4H", "BROKEN_SUPPORT_RETEST"):
            location += 8.0
        elif source == "EMA20_PULLBACK_REFERENCE":
            location += 2.0

    trigger = 0.0
    sweep = base.get("liquidity_sweep") or {}
    breakdown = base.get("breakdown_retest") or {}

    if sweep.get("detected") and int(sweep.get("bars_ago") or 999) <= 3:
        trigger += 7.0
    if base.get("bearish_rejection"):
        trigger += 5.0

    setup_type = str((setup or {}).get("v42_setup") or "")
    if setup_type == "BEAR_CONTINUATION_RETEST":
        if continuation.get("ready"):
            trigger += 12.0
        elif breakdown.get("breakdown"):
            # A raw breakdown is context, not a trigger.
            trigger += 1.0
    elif setup is not None:
        trigger += 3.0

    return (
        _clamp(location, 0.0, 30.0),
        _clamp(trigger, 0.0, 20.0),
        None if distance is None else round(distance, 4),
    )


def _reference_plan(zone, a1):
    if zone is None:
        return {}

    lower = float(zone["lower"])
    upper = float(zone["upper"])
    entry = lower * 0.35 + upper * 0.65
    stop = max(upper, entry) + V422_REFERENCE_STOP_BUFFER_ATR * a1
    risk = stop - entry
    if risk <= 0:
        return {}

    fee_r = (
        entry * float(BACKTEST_FEE_BPS_ROUND_TRIP) / 10000.0
    ) / risk
    slippage_r = (
        entry * float(V422_SLIPPAGE_BPS_REFERENCE) / 10000.0
    ) / risk

    return {
        "reference_entry": entry,
        "reference_stop": stop,
        "reference_risk": risk,
        "reference_tp1": entry - 2.0 * risk,
        "reference_tp2": entry - 3.0 * risk,
        "reference_runner": entry - 5.0 * risk,
        "fee_cost_r": round(fee_r, 4),
        "slippage_advisory_r": round(slippage_r, 4),
        "slippage_is_hard_gate": False,
    }


def build_v422_candidate(base, one, four, btc_one, eth_one):
    if one is None or four is None or len(one) < 60 or len(four) < 60:
        return None

    current = float(one["close"].iloc[-1])
    a1 = float(atr(one).iloc[-1])
    if not math.isfinite(a1) or a1 <= 0:
        return None

    s1 = structure_snapshot(one)
    s4 = structure_snapshot(four)
    regime = route_v4_regime(btc_one, eth_one, one)

    market_r4 = float(regime.get("market_r4") or 0.0)
    market_r24 = float(regime.get("market_r24") or 0.0)
    r4 = float(return_pct(one["close"], 4))
    r24 = float(return_pct(one["close"], 24))
    relative_4h = r4 - market_r4
    relative_24h = r24 - market_r24

    setup = route_v42_setup(base, one, four, btc_one, eth_one)

    bearish_context = bool(
        s4["ema_bear"]
        or s4["lower_high"]
        or relative_24h <= -3.0
    )
    if setup is None and not bearish_context:
        return None

    zone = _preferred_zone(base, setup, one)
    continuation = _continuation_pullback(base, one, a1)
    risk = _rebound_bottom_risk(
        base,
        one,
        current,
        a1,
        base.get("nearest_support"),
    )

    directional = _directional_bias_score(
        s1,
        s4,
        regime,
        relative_4h,
        relative_24h,
    )
    location, trigger, zone_distance = _location_and_trigger(
        base,
        zone,
        one,
        setup,
        continuation,
    )

    raw_score = (
        directional
        + location
        + trigger
        - float(risk["anti_bottom_total"])
    )
    score = _clamp(raw_score, 0.0, 100.0)

    setup_type = str((setup or {}).get("v42_setup") or "BEARISH_BIAS_WATCH")
    subtype = str((setup or {}).get("v42_subtype") or "CONTEXT_ONLY")

    if directional >= 15.0:
        bias = "STRONG_SHORT_BIAS"
    elif directional >= 9.0:
        bias = "SHORT_BIAS"
    else:
        bias = "WEAK_SHORT_BIAS"

    anti_bottom_block = (
        float(risk["anti_bottom_total"]) >= V422_BOTTOM_BLOCK_SCORE
    )

    location_ready = bool(
        zone_distance is not None
        and zone_distance <= V422_READY_ZONE_DISTANCE_ATR
    )

    if setup_type == "BEAR_CONTINUATION_RETEST":
        setup_ready = bool(continuation.get("ready"))
        wait_reason = continuation.get("reason")
    else:
        setup_ready = bool(
            setup is not None
            and trigger >= 5.0
            and location_ready
        )
        wait_reason = (
            "REVERSAL_LOCATION_NOT_READY"
            if not setup_ready
            else "READY"
        )

    if anti_bottom_block:
        action = "AVOID_BOTTOM_SHORT"
    elif (
        score >= V422_MIN_SHORT_NOW_SCORE
        and location_ready
        and setup_ready
    ):
        action = "SHORT_NOW"
    elif bias in ("SHORT_BIAS", "STRONG_SHORT_BIAS"):
        action = "WAIT_PULLBACK"
    else:
        action = "WATCH_ONLY"

    if score < V422_MIN_EMIT_SCORE and action == "WATCH_ONLY":
        return None

    reference = _reference_plan(zone, a1)

    return {
        "v422_bias": bias,
        "v422_action": action,
        "v422_score": round(score, 3),
        "v422_thesis": setup_type,
        "v422_subtype": subtype,
        "directional_score": round(directional, 3),
        "location_score": round(location, 3),
        "trigger_score": round(trigger, 3),
        "bottom_risk": risk["bottom_risk"],
        "rebound_risk": risk["rebound_risk"],
        "anti_bottom_total": risk["anti_bottom_total"],
        "bottom_reasons": risk["bottom_reasons"],
        "continuation_pullback_ready": bool(continuation.get("ready")),
        "continuation_pullback_reason": continuation.get("reason"),
        "relative_4h_pct": round(relative_4h, 4),
        "relative_24h_pct": round(relative_24h, 4),
        "regime": regime,
        "current_price": current,
        "atr_1h": a1,
        "zone_source": None if zone is None else zone.get("source"),
        "preferred_zone_lower": None if zone is None else zone.get("lower"),
        "preferred_zone_upper": None if zone is None else zone.get("upper"),
        "preferred_zone_distance_atr": zone_distance,
        **risk,
        **reference,
        "execution_note": (
            "Entry/SL/TP are reference levels. Slippage is advisory only."
        ),
    }
