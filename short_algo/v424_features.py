"""Signal-time-safe V4.2.4 feature extraction."""

import math

from .config import BACKTEST_FEE_BPS_ROUND_TRIP
from .indicators import atr, ema, return_pct, structure_snapshot, volume_ratio
from .v4_regime import route_v4_regime
from .v42_setup import route_v42_setup
from .v422_filter import _preferred_zone, _rebound_bottom_risk
from .v423_filter import (
    _continuation_quality,
    _relative_recovery,
    _squeeze_risk,
)
from .v424_config import (
    V424_BOTTOM_EMA_DISTANCE_ATR,
    V424_BOTTOM_FAST_DROP_ATR,
    V424_BOTTOM_LOW_DISTANCE_ATR,
    V424_BOTTOM_SUPPORT_DISTANCE_ATR,
    V424_REFERENCE_STOP_BUFFER_ATR,
    V424_SLIPPAGE_BPS_REFERENCE,
)


def _range_position(frame, bars):
    view = frame.tail(max(5, int(bars)))
    low = float(view["low"].min())
    high = float(view["high"].max())
    current = float(view["close"].iloc[-1])
    if high <= low:
        return 0.5
    return max(0.0, min(1.0, (current - low) / (high - low)))


def _market_return(frame, bars):
    if frame is None or len(frame) <= bars:
        return 0.0
    return float(return_pct(frame["close"], bars))


def _zone_distance(zone, current, a1):
    if zone is None:
        return None
    lower = float(zone["lower"])
    upper = float(zone["upper"])
    if lower <= current <= upper:
        return 0.0
    if current < lower:
        return (lower - current) / max(a1, 1e-12)
    return (current - upper) / max(a1, 1e-12)


def _reference_plan(zone, a1):
    if zone is None:
        return {}
    lower = float(zone["lower"])
    upper = float(zone["upper"])
    entry = lower * 0.35 + upper * 0.65
    stop = max(upper, entry) + V424_REFERENCE_STOP_BUFFER_ATR * a1
    risk = stop - entry
    if risk <= 0:
        return {}

    fee_r = (
        entry * float(BACKTEST_FEE_BPS_ROUND_TRIP) / 10000.0
    ) / risk
    slippage_r = (
        entry * float(V424_SLIPPAGE_BPS_REFERENCE) / 10000.0
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


def build_v424_features(base, one, four, btc_one, eth_one):
    if one is None or four is None or len(one) < 60 or len(four) < 60:
        return None

    current = float(one["close"].iloc[-1])
    a1 = float(atr(one).iloc[-1])
    if not math.isfinite(a1) or a1 <= 0:
        return None

    s1 = structure_snapshot(one)
    s4 = structure_snapshot(four)
    regime = route_v4_regime(btc_one, eth_one, one)
    setup = route_v42_setup(base, one, four, btc_one, eth_one)
    zone = _preferred_zone(base, setup, one)

    close = one["close"].astype(float)
    high = one["high"].astype(float)
    low = one["low"].astype(float)

    r1 = float(return_pct(close, 1))
    r3 = float(return_pct(close, 3))
    r4 = float(return_pct(close, 4))
    r12 = float(return_pct(close, 12))
    r24 = float(return_pct(close, 24))

    market1 = (_market_return(btc_one, 1) + _market_return(eth_one, 1)) / 2.0
    market3 = (_market_return(btc_one, 3) + _market_return(eth_one, 3)) / 2.0
    market4 = float(regime.get("market_r4") or 0.0)
    market24 = float(regime.get("market_r24") or 0.0)

    e20 = float(ema(close, 20).iloc[-1])
    ema_distance = (e20 - current) / max(a1, 1e-12)

    low12 = float(low.tail(12).min())
    low24 = float(low.tail(24).min())
    high12 = float(high.tail(12).max())

    support = base.get("nearest_support")
    support_distance = None
    if support is not None and float(support) < current:
        support_distance = (
            current - float(support)
        ) / max(a1, 1e-12)

    supply_distance = base.get("supply_distance_atr")
    breakdown = base.get("breakdown_retest") or {}
    sweep = base.get("liquidity_sweep") or {}

    breakdown_level = breakdown.get("level")
    breakdown_distance = None
    if breakdown_level is not None:
        breakdown_distance = (
            float(breakdown_level) - current
        ) / max(a1, 1e-12)

    continuation = _continuation_quality(base, one, a1)
    recovery = _relative_recovery(one, btc_one, eth_one)
    squeeze = _squeeze_risk(regime, recovery, continuation)
    anti_bottom = _rebound_bottom_risk(
        base,
        one,
        current,
        a1,
        support,
    )

    zone_distance = _zone_distance(zone, current, a1)
    zone_source = str((zone or {}).get("source") or "NO_ZONE")

    # Broad bearish candidate universe. This is intentionally much looser
    # than an entry trigger because V4.2.4's job is ranking coins.
    context_points = 0
    context_points += int(bool(s4["ema_bear"]))
    context_points += int(bool(s4["lower_high"]))
    context_points += int(bool(s1["ema_bear"]))
    context_points += int(bool(breakdown.get("breakdown")))
    context_points += int(bool(sweep.get("detected")))
    context_points += int(bool(base.get("bearish_rejection")))
    context_points += int((r4 - market4) <= -1.0)
    context_points += int((r24 - market24) <= -3.0)
    if context_points < 2:
        return None

    distance_12h_low = (current - low12) / max(a1, 1e-12)
    fast_drop_3h = max(
        0.0,
        (float(close.iloc[-4]) - current) / max(a1, 1e-12),
    ) if len(close) >= 4 else 0.0

    severe_bottom = bool(
        (
            distance_12h_low < V424_BOTTOM_LOW_DISTANCE_ATR
            and (
                ema_distance > V424_BOTTOM_EMA_DISTANCE_ATR
                or fast_drop_3h > V424_BOTTOM_FAST_DROP_ATR
            )
        )
        or (
            support_distance is not None
            and support_distance < V424_BOTTOM_SUPPORT_DISTANCE_ATR
        )
    )

    row = {
        "current_price": current,
        "atr_1h": a1,
        "candidate_context_points": context_points,
        "setup_type": str((setup or {}).get("v42_setup") or "CONTEXT_ONLY"),
        "setup_subtype": str((setup or {}).get("v42_subtype") or "CONTEXT_ONLY"),
        "zone_source": zone_source,
        "preferred_zone_lower": None if zone is None else zone.get("lower"),
        "preferred_zone_upper": None if zone is None else zone.get("upper"),
        "zone_distance_atr": None if zone_distance is None else round(zone_distance, 4),
        "severe_bottom_rule": severe_bottom,
        "bottom_reasons": anti_bottom.get("bottom_reasons") or [],
        "return_1h_pct": round(r1, 4),
        "return_3h_pct": round(r3, 4),
        "return_4h_pct": round(r4, 4),
        "return_12h_pct": round(r12, 4),
        "return_24h_pct": round(r24, 4),
        "relative_1h_pct": round(r1 - market1, 4),
        "relative_3h_pct": round(r3 - market3, 4),
        "relative_4h_pct": round(r4 - market4, 4),
        "relative_24h_pct": round(r24 - market24, 4),
        "ema20_distance_atr": round(ema_distance, 4),
        "range_position_12h": round(_range_position(one, 12), 4),
        "range_position_24h": round(_range_position(one, 24), 4),
        "range_position_48h": round(_range_position(one, 48), 4),
        "distance_12h_low_atr": round(distance_12h_low, 4),
        "distance_24h_low_atr": round(
            (current - low24) / max(a1, 1e-12), 4
        ),
        "distance_12h_high_atr": round(
            (high12 - current) / max(a1, 1e-12), 4
        ),
        "support_distance_atr": (
            None if support_distance is None
            else round(support_distance, 4)
        ),
        "supply_distance_atr": supply_distance,
        "atr_pct_1h": round(float(s1["atr_pct"]), 4),
        "volume_ratio_1h": round(float(volume_ratio(one)), 4),
        "s1_ema_bear": int(bool(s1["ema_bear"])),
        "s1_lower_high": int(bool(s1["lower_high"])),
        "s1_lower_low": int(bool(s1["lower_low"])),
        "s4_ema_bear": int(bool(s4["ema_bear"])),
        "s4_lower_high": int(bool(s4["lower_high"])),
        "s4_lower_low": int(bool(s4["lower_low"])),
        "s4_macro_bear": int(bool(s4["macro_bear"])),
        "breakdown_detected": int(bool(breakdown.get("breakdown"))),
        "breakdown_retest": int(bool(breakdown.get("retest"))),
        "breakdown_age_1h": float(breakdown.get("bars_ago") or 99),
        "breakdown_distance_atr": breakdown_distance,
        "sweep_detected": int(bool(sweep.get("detected"))),
        "sweep_age_1h": float(sweep.get("bars_ago") or 99),
        "bearish_rejection": int(bool(base.get("bearish_rejection"))),
        "continuation_quality": float(continuation.get("quality_score") or 0.0),
        "continuation_ready": int(bool(continuation.get("ready"))),
        "break_departure_atr": continuation.get("break_departure_atr"),
        "break_body_atr": continuation.get("break_body_atr"),
        "break_volume_ratio": continuation.get("break_volume_ratio"),
        "retest_touched": int(bool(continuation.get("retest_touched"))),
        "retest_rejection": int(bool(continuation.get("retest_rejection"))),
        "reclaim_seen": int(bool(continuation.get("reclaim_seen"))),
        "acceptance_bars": float(continuation.get("acceptance_bars") or 0),
        "rebound_from_break_low_atr": continuation.get("rebound_from_break_low_atr"),
        "anti_bottom_total": float(anti_bottom.get("anti_bottom_total") or 0.0),
        "squeeze_risk": float(squeeze.get("squeeze_risk") or 0.0),
        "market_r4_pct": round(market4, 4),
        "market_r24_pct": round(market24, 4),
        "market_risk_on": int(regime.get("risk_state") == "RISK_ON"),
        "market_risk_off": int(regime.get("risk_state") == "RISK_OFF"),
        "market_bull": int(regime.get("trend_state") == "BULL"),
        "market_bear": int(regime.get("trend_state") == "BEAR"),
        "zone_supply_1h": int(zone_source == "SUPPLY_1H"),
        "zone_supply_4h": int(zone_source == "SUPPLY_4H"),
        "zone_broken_support": int(zone_source == "BROKEN_SUPPORT_RETEST"),
        "zone_sweep_retest": int(zone_source == "SWEEP_RETEST"),
        **recovery,
        **_reference_plan(zone, a1),
        "execution_note": (
            "Scanner reference only. User decides entry; slippage is advisory."
        ),
    }
    return row
