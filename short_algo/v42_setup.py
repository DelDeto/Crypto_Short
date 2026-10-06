"""V4.2 setup router.

The old five engines are collapsed into:
1) REVERSAL_AT_LOCATION
2) BEAR_CONTINUATION_RETEST

Relative weakness, exhaustion and extreme-pump context are features/subtypes,
not independent entry engines. One symbol/timestamp produces at most one setup.
"""

import math

from .indicators import atr, return_pct, structure_snapshot, volume_ratio
from .v4_regime import route_v4_regime
from .v42_config import (
    V42_MAX_BREAKDOWN_AGE_1H,
    V42_MAX_SUPPLY_DISTANCE_ATR,
    V42_MAX_SWEEP_AGE_1H,
)


def _relative_context(one, regime):
    r4 = float(return_pct(one["close"], 4))
    r24 = float(return_pct(one["close"], 24))
    market_r4 = float(regime.get("market_r4") or 0.0)
    market_r24 = float(regime.get("market_r24") or 0.0)
    return {
        "return_4h_pct": round(r4, 4),
        "return_24h_pct": round(r24, 4),
        "relative_4h_pct": round(r4 - market_r4, 4),
        "relative_24h_pct": round(r24 - market_r24, 4),
    }


def _location_flags(base):
    supply_distance = base.get("supply_distance_atr")
    sweep = base.get("liquidity_sweep") or {}
    breakdown = base.get("breakdown_retest") or {}
    return {
        "near_supply": bool(
            supply_distance is not None
            and float(supply_distance) <= V42_MAX_SUPPLY_DISTANCE_ATR
        ),
        "fresh_sweep": bool(
            sweep.get("detected")
            and int(sweep.get("bars_ago") or 999) <= V42_MAX_SWEEP_AGE_1H
        ),
        "fresh_breakdown": bool(
            breakdown.get("breakdown")
            and int(breakdown.get("bars_ago") or 999) <= V42_MAX_BREAKDOWN_AGE_1H
            and breakdown.get("level") is not None
        ),
    }


def route_v42_setup(base, one, four, btc_one, eth_one):
    if one is None or four is None or len(one) < 60 or len(four) < 60:
        return None

    s1 = structure_snapshot(one)
    s4 = structure_snapshot(four)
    a1 = float(atr(one).iloc[-1])
    if not math.isfinite(a1) or a1 <= 0:
        return None

    regime = route_v4_regime(btc_one, eth_one, one)
    rel = _relative_context(one, regime)
    loc = _location_flags(base)
    sweep = base.get("liquidity_sweep") or {}
    breakdown = base.get("breakdown_retest") or {}
    rejection = bool(base.get("bearish_rejection"))
    vol_ratio = float(volume_ratio(one))

    # Context features. They influence priority/quality but cannot create a
    # standalone trade by themselves.
    extreme_pump = bool(
        rel["return_24h_pct"] >= 10.0
        and (
            loc["fresh_sweep"]
            or rel["return_24h_pct"] >= 18.0
        )
    )
    exhaustion = bool(
        rejection
        or (
            rel["return_24h_pct"] >= 4.0
            and vol_ratio >= 1.4
        )
    )
    relative_weakness = bool(
        rel["relative_4h_pct"] <= -1.0
        or rel["relative_24h_pct"] <= -3.0
    )

    strong_bull_market = bool(
        regime.get("risk_state") == "RISK_ON"
        and regime.get("trend_state") == "BULL"
    )

    # Reversal must begin from a real HTF location and a failed-auction clue.
    reversal_location = bool(loc["near_supply"] or loc["fresh_sweep"])
    reversal_event = bool(loc["fresh_sweep"] or rejection)
    reversal_allowed = bool(
        reversal_location
        and reversal_event
        and (
            not strong_bull_market
            or (
                extreme_pump
                and loc["fresh_sweep"]
            )
        )
    )

    reversal_quality = 0.0
    if loc["near_supply"]:
        reversal_quality += 30.0
    if loc["fresh_sweep"]:
        reversal_quality += 30.0
    if rejection:
        reversal_quality += 12.0
    if extreme_pump:
        reversal_quality += 10.0
    if exhaustion:
        reversal_quality += 6.0
    if relative_weakness:
        reversal_quality += 8.0
    if strong_bull_market:
        reversal_quality -= 20.0

    # Continuation requires bearish HTF structure plus a fresh broken support.
    htf_bear = bool(
        s4["ema_bear"]
        or (s4["lower_high"] and s4["lower_low"])
    )
    local_bear = bool(
        s1["ema_bear"]
        or (s1["lower_high"] and s1["close"] < s1["ema20"])
    )
    continuation_allowed = bool(
        loc["fresh_breakdown"]
        and htf_bear
        and local_bear
        and regime.get("trend_state") != "BULL"
        and rel["return_24h_pct"] > -18.0
    )

    continuation_quality = 0.0
    if loc["fresh_breakdown"]:
        continuation_quality += 35.0
    if htf_bear:
        continuation_quality += 25.0
    if local_bear:
        continuation_quality += 15.0
    if regime.get("risk_state") == "RISK_OFF":
        continuation_quality += 12.0
    if relative_weakness:
        continuation_quality += 8.0
    if rel["return_24h_pct"] <= -12.0:
        continuation_quality -= 10.0

    options = []
    if reversal_allowed:
        options.append(("REVERSAL_AT_LOCATION", reversal_quality))
    if continuation_allowed:
        options.append(("BEAR_CONTINUATION_RETEST", continuation_quality))
    if not options:
        return None

    # Exactly one setup per symbol/timestamp. If both are valid, take the
    # higher-quality structural thesis instead of double-counting one event.
    setup_type, quality = sorted(
        options,
        key=lambda x: (-float(x[1]), x[0]),
    )[0]

    subtype = "STANDARD"
    if setup_type == "REVERSAL_AT_LOCATION" and extreme_pump:
        subtype = "EXTREME_PUMP_REVERSAL"
    elif setup_type == "REVERSAL_AT_LOCATION" and exhaustion:
        subtype = "FAILED_AUCTION_EXHAUSTION"
    elif setup_type == "BEAR_CONTINUATION_RETEST" and relative_weakness:
        subtype = "RELATIVE_WEAK_CONTINUATION"

    return {
        "v42_setup": setup_type,
        "v42_subtype": subtype,
        "v42_setup_quality": round(max(0.0, min(100.0, quality)), 3),
        "v42_regime": regime,
        "v42_context": {
            **rel,
            "volume_ratio_1h": round(vol_ratio, 4),
            "extreme_pump": extreme_pump,
            "exhaustion": exhaustion,
            "relative_weakness": relative_weakness,
            "near_supply": loc["near_supply"],
            "fresh_sweep": loc["fresh_sweep"],
            "fresh_breakdown": loc["fresh_breakdown"],
            "htf_bear": htf_bear,
            "local_bear": local_bear,
        },
        "preferred_location": (
            "REVERSAL_ZONE"
            if setup_type == "REVERSAL_AT_LOCATION"
            else "BROKEN_SUPPORT"
        ),
        "breakdown_level": breakdown.get("level"),
        "sweep_level": sweep.get("level"),
    }
