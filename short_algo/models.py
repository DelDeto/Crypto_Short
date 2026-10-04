"""Exclusive V2 setup classification for Short signals.

Models:
A - TREND_CONTINUATION: breakdown/retest in an established bearish structure.
B - LIQUIDITY_REVERSAL: pump/sweep of highs followed by failure/rejection.
C - SUPPLY_FADE: rally into supply followed by bearish rejection/lower-high.
"""


def classify_short_model(result, return_24h_pct=0.0):
    sweep = result.get("liquidity_sweep") or {}
    breakdown = result.get("breakdown_retest") or {}
    filters = result.get("filters") or {}
    supply_distance = result.get("supply_distance_atr")
    rejection = bool(result.get("bearish_rejection"))
    score_breakdown = result.get("score_breakdown") or {}

    mtf_ok = bool(filters.get("mtf_ok"))
    structure_strength = (
        float(score_breakdown.get("structure_4h") or 0)
        + float(score_breakdown.get("structure_1h") or 0)
    )

    # Model B gets priority when the market first ran buy-side liquidity.
    # "Top gainer" is context, not the trigger itself.
    liquidity_reversal = (
        bool(sweep.get("detected"))
        and (
            rejection
            or (supply_distance is not None and float(supply_distance) <= 1.0)
        )
        and float(return_24h_pct or 0.0) > 0.0
    )

    trend_continuation = (
        bool(breakdown.get("breakdown"))
        and (
            bool(breakdown.get("retest"))
            or bool(filters.get("location_ok"))
        )
        and mtf_ok
        and structure_strength >= 28
    )

    supply_fade = (
        supply_distance is not None
        and float(supply_distance) <= 0.75
        and (
            rejection
            or float(score_breakdown.get("structure_1h") or 0) >= 17
        )
        and not bool(breakdown.get("retest"))
    )

    if liquidity_reversal:
        model = "LIQUIDITY_REVERSAL"
    elif trend_continuation:
        model = "TREND_CONTINUATION"
    elif supply_fade:
        model = "SUPPLY_FADE"
    else:
        model = "UNCLASSIFIED"

    return {
        "model": model,
        "model_flags": {
            "trend_continuation": trend_continuation,
            "liquidity_reversal": liquidity_reversal,
            "supply_fade": supply_fade,
        },
        "top_gainer_context": float(return_24h_pct or 0.0) >= 5.0,
        "return_24h_pct": round(float(return_24h_pct or 0.0), 3),
    }
