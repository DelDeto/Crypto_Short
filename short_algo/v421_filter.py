"""V4.2.1 market filter for discretionary Short decisions.

Primary objective: rank coins whose price is likely to continue lower while
penalizing already-extended / near-support "short the bottom" situations.

No future data is used here. Slippage is execution advice, never a hard gate.
"""

import math

from .config import BACKTEST_FEE_BPS_ROUND_TRIP
from .indicators import atr, ema, return_pct, structure_snapshot, volume_ratio
from .v4_regime import route_v4_regime
from .v42_entry import build_v42_zone
from .v42_setup import route_v42_setup
from .v421_config import (
    V421_BOTTOM_AVOID_SCORE,
    V421_EMA_EXTENDED_ATR,
    V421_EMA_VERY_EXTENDED_ATR,
    V421_MIN_WATCH_SCORE,
    V421_PULLBACK_EMA_BUFFER_ATR,
    V421_RANGE_BOTTOM_PCT,
    V421_READY_ZONE_DISTANCE_ATR,
    V421_REFERENCE_STOP_BUFFER_ATR,
    V421_SHORT_CANDIDATE_SCORE,
    V421_SLIPPAGE_BPS_REFERENCE,
    V421_SUPPORT_CAUTION_ATR,
    V421_SUPPORT_NEAR_ATR,
)


def _clamp(value, lo, hi):
    return max(lo, min(hi, float(value)))


def _range_position(one, bars=48):
    view = one.tail(max(10, bars))
    low = float(view["low"].min())
    high = float(view["high"].max())
    close = float(view["close"].iloc[-1])
    width = high - low
    if width <= 0:
        return 0.5
    return _clamp((close - low) / width, 0.0, 1.0)


def _preferred_zone(base, setup, one):
    """Return a reference pullback zone, not an automatic order price."""
    zone = build_v42_zone(setup, base, one) if setup is not None else None
    if zone is not None:
        return dict(zone)

    current = float(one["close"].iloc[-1])
    a1 = float(atr(one).iloc[-1])

    # Bias-only candidates should wait for a pullback. Prefer known supply;
    # otherwise use EMA20 as a dynamic reference, never as a reversal proof.
    supplies = []
    for source, raw, priority in (
        ("SUPPLY_1H", base.get("supply_1h") or {}, 1),
        ("SUPPLY_4H", base.get("supply_4h") or {}, 2),
    ):
        if raw.get("lower") is None or raw.get("upper") is None:
            continue
        upper = float(raw["upper"])
        lower = float(raw["lower"])
        if upper >= current - 0.20 * a1:
            distance = 0.0 if lower <= current <= upper else max(0.0, lower - current) / max(a1, 1e-12)
            supplies.append({
                "lower": lower,
                "upper": upper,
                "mid": (lower + upper) / 2.0,
                "source": source,
                "distance_atr1h": distance,
                "priority": priority,
                "signal_price": current,
                "atr_1h": a1,
            })
    if supplies:
        supplies.sort(key=lambda z: (z["priority"], z["distance_atr1h"]))
        return supplies[0]

    e20 = float(ema(one["close"].astype(float), 20).iloc[-1])
    return {
        "lower": e20 - V421_PULLBACK_EMA_BUFFER_ATR * a1,
        "upper": e20 + V421_PULLBACK_EMA_BUFFER_ATR * a1,
        "mid": e20,
        "source": "EMA20_PULLBACK_REFERENCE",
        "distance_atr1h": abs(e20 - current) / max(a1, 1e-12),
        "priority": 9,
        "signal_price": current,
        "atr_1h": a1,
    }


def _directional_score(s1, s4, regime, relative_4h, relative_24h):
    score = 0.0
    if s4["ema_bear"]:
        score += 8.0
    if s4["lower_high"]:
        score += 5.0
    if s4["lower_low"]:
        score += 4.0
    if s1["ema_bear"]:
        score += 5.0
    if s1["lower_high"]:
        score += 3.0
    if s1["lower_low"]:
        score += 2.0
    if relative_4h <= -1.0:
        score += 2.0
    if relative_24h <= -3.0:
        score += 2.0
    if regime.get("risk_state") == "RISK_OFF":
        score += 3.0
    if regime.get("trend_state") == "BEAR":
        score += 3.0
    if regime.get("trend_state") == "BULL":
        score -= 5.0
    return _clamp(score, 0.0, 30.0)


def _trigger_score(base, setup, one):
    score = 0.0
    sweep = base.get("liquidity_sweep") or {}
    breakdown = base.get("breakdown_retest") or {}

    if sweep.get("detected") and int(sweep.get("bars_ago") or 999) <= 3:
        score += 6.0
    if base.get("bearish_rejection"):
        score += 4.0
    if breakdown.get("breakdown"):
        score += 4.0
    if breakdown.get("retest"):
        score += 3.0
    vr = float(volume_ratio(one))
    if vr >= 1.2:
        score += 2.0
    if setup is not None:
        score += 3.0
    return _clamp(score, 0.0, 20.0)


def _location_score(zone, current, a1, nearest_support):
    score = 0.0
    distance = None
    if zone is not None:
        lower = float(zone["lower"])
        upper = float(zone["upper"])
        if lower <= current <= upper:
            distance = 0.0
            score += 14.0
        elif current < lower:
            distance = (lower - current) / max(a1, 1e-12)
            if distance <= 0.40:
                score += 12.0
            elif distance <= 0.80:
                score += 8.0
            elif distance <= 1.50:
                score += 4.0
        else:
            distance = (current - upper) / max(a1, 1e-12)
            if distance <= 0.25:
                score += 8.0

        source = str(zone.get("source") or "")
        if source in ("SUPPLY_1H", "SWEEP_RETEST", "BROKEN_SUPPORT_RETEST"):
            score += 8.0
        elif source == "SUPPLY_4H":
            score += 7.0
        elif source == "EMA20_PULLBACK_REFERENCE":
            score += 3.0

    support_distance_atr = None
    if nearest_support is not None and float(nearest_support) < current:
        support_distance_atr = (
            current - float(nearest_support)
        ) / max(a1, 1e-12)
        if support_distance_atr >= 2.0:
            score += 8.0
        elif support_distance_atr >= 1.25:
            score += 5.0
        elif support_distance_atr >= 0.8:
            score += 2.0

    return (
        _clamp(score, 0.0, 30.0),
        distance,
        support_distance_atr,
    )


def _bottom_and_chase_risk(one, current, a1, nearest_support):
    r4 = float(return_pct(one["close"], 4))
    r12 = float(return_pct(one["close"], 12))
    r24 = float(return_pct(one["close"], 24))
    e20 = float(ema(one["close"].astype(float), 20).iloc[-1])
    below_ema_atr = max(0.0, (e20 - current) / max(a1, 1e-12))
    range_pos = _range_position(one, 48)

    bottom = 0.0
    reasons = []

    if r4 <= -8.0:
        bottom += 8.0
        reasons.append("4H_DROP_EXTREME")
    elif r4 <= -5.0:
        bottom += 4.0
        reasons.append("4H_DROP_LARGE")

    if r12 <= -18.0:
        bottom += 8.0
        reasons.append("12H_DROP_EXTREME")
    elif r12 <= -12.0:
        bottom += 4.0
        reasons.append("12H_DROP_LARGE")

    if r24 <= -25.0:
        bottom += 6.0
        reasons.append("24H_COLLAPSE")

    if below_ema_atr >= V421_EMA_VERY_EXTENDED_ATR:
        bottom += 8.0
        reasons.append("VERY_FAR_BELOW_EMA20")
    elif below_ema_atr >= V421_EMA_EXTENDED_ATR:
        bottom += 4.0
        reasons.append("FAR_BELOW_EMA20")

    if range_pos <= V421_RANGE_BOTTOM_PCT:
        bottom += 6.0
        reasons.append("NEAR_48H_RANGE_LOW")

    support_distance_atr = None
    if nearest_support is not None and float(nearest_support) < current:
        support_distance_atr = (
            current - float(nearest_support)
        ) / max(a1, 1e-12)
        if support_distance_atr < V421_SUPPORT_NEAR_ATR:
            bottom += 9.0
            reasons.append("SUPPORT_VERY_CLOSE")
        elif support_distance_atr < V421_SUPPORT_CAUTION_ATR:
            bottom += 4.0
            reasons.append("SUPPORT_CLOSE")
    else:
        # Unknown support is uncertainty, never interpreted as unlimited room.
        bottom += 3.0
        reasons.append("SUPPORT_UNKNOWN")

    last = one.iloc[-1]
    candle_range_atr = (
        float(last["high"]) - float(last["low"])
    ) / max(a1, 1e-12)
    vr = float(volume_ratio(one))
    if r24 <= -8.0 and candle_range_atr >= 2.0 and vr >= 2.0:
        bottom += 5.0
        reasons.append("POSSIBLE_CAPITULATION")

    chase = 0.0
    if below_ema_atr >= 1.2:
        chase += min(8.0, (below_ema_atr - 1.2) * 4.0)
    if r4 <= -6.0:
        chase += 3.0

    return {
        "bottom_risk": round(bottom, 3),
        "chase_risk": round(chase, 3),
        "bottom_reasons": reasons,
        "return_4h_pct": round(r4, 4),
        "return_12h_pct": round(r12, 4),
        "return_24h_pct": round(r24, 4),
        "below_ema20_atr": round(below_ema_atr, 4),
        "range_position_48h": round(range_pos, 4),
        "support_distance_atr": (
            None
            if support_distance_atr is None
            else round(support_distance_atr, 4)
        ),
    }


def _reference_plan(zone, current, a1):
    if zone is None:
        return {}
    lower = float(zone["lower"])
    upper = float(zone["upper"])
    entry = lower * 0.35 + upper * 0.65

    stop_anchor = max(upper, entry)
    stop = stop_anchor + V421_REFERENCE_STOP_BUFFER_ATR * a1
    risk = stop - entry
    if risk <= 0:
        return {}

    fee_r = (
        entry * float(BACKTEST_FEE_BPS_ROUND_TRIP) / 10000.0
    ) / risk
    slippage_r = (
        entry * float(V421_SLIPPAGE_BPS_REFERENCE) / 10000.0
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


def build_v421_candidate(base, one, four, btc_one, eth_one):
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

    # Broaden the scanner beyond only entry-ready setups. Strong bearish bias
    # can be returned as WAIT_FOR_PULLBACK rather than chased immediately.
    htf_bearish = bool(
        s4["ema_bear"]
        or (s4["lower_high"] and s4["lower_low"])
    )
    local_bearish = bool(
        s1["ema_bear"]
        or s1["lower_high"]
        or current < float(s1["ema20"])
    )
    relative_weak = bool(
        relative_4h <= -1.0
        or relative_24h <= -3.0
    )
    if setup is None and not (htf_bearish and local_bearish and relative_weak):
        return None

    zone = _preferred_zone(base, setup, one)
    directional = _directional_score(
        s1, s4, regime, relative_4h, relative_24h
    )
    trigger = _trigger_score(base, setup, one)
    location, zone_distance, support_distance = _location_score(
        zone, current, a1, base.get("nearest_support")
    )
    risk = _bottom_and_chase_risk(
        one, current, a1, base.get("nearest_support")
    )

    total = _clamp(
        directional
        + location
        + trigger
        - float(risk["bottom_risk"])
        - float(risk["chase_risk"]),
        0.0,
        100.0,
    )

    if setup is not None:
        thesis = str(setup.get("v42_setup"))
        subtype = str(setup.get("v42_subtype"))
    else:
        thesis = "BEARISH_BIAS_WATCH"
        subtype = "RELATIVE_WEAKNESS_CONTEXT"

    zone_distance = (
        None if zone_distance is None else round(float(zone_distance), 4)
    )

    if float(risk["bottom_risk"]) >= V421_BOTTOM_AVOID_SCORE:
        status = "AVOID_BOTTOM_SHORT"
    elif (
        total >= V421_SHORT_CANDIDATE_SCORE
        and zone_distance is not None
        and zone_distance <= V421_READY_ZONE_DISTANCE_ATR
        and trigger >= 6.0
    ):
        status = "SHORT_CANDIDATE"
    elif total >= V421_MIN_WATCH_SCORE:
        status = "WAIT_FOR_PULLBACK"
    else:
        status = "FILTERED"

    # A low score is not useful to the discretionary shortlist.
    if status == "FILTERED":
        return None

    reference = _reference_plan(zone, current, a1)
    return {
        "v421_status": status,
        "v421_score": round(total, 3),
        "v421_thesis": thesis,
        "v421_subtype": subtype,
        "directional_score": round(directional, 3),
        "location_score": round(location, 3),
        "trigger_score": round(trigger, 3),
        "bottom_risk": risk["bottom_risk"],
        "chase_risk": risk["chase_risk"],
        "bottom_reasons": risk["bottom_reasons"],
        "relative_4h_pct": round(relative_4h, 4),
        "relative_24h_pct": round(relative_24h, 4),
        "regime": regime,
        "current_price": current,
        "atr_1h": a1,
        "zone_source": None if zone is None else zone.get("source"),
        "preferred_zone_lower": None if zone is None else zone.get("lower"),
        "preferred_zone_upper": None if zone is None else zone.get("upper"),
        "preferred_zone_distance_atr": zone_distance,
        "support_distance_atr": support_distance,
        **risk,
        **reference,
        "execution_note": (
            "Slippage is advisory only; user controls actual entry execution."
        ),
    }
