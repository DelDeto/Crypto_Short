"""V2.1 model-specific execution gates.

The V1 score/status is preserved for comparison. V2.1 deliberately gives
LIQUIDITY_REVERSAL its own gate because the 90-day V2 study showed that forcing
a full 4H+1H bearish regime can suppress the reversal setups that had the best
historical expectancy.

Trend Continuation and Supply Fade remain research-only until they demonstrate
positive out-of-sample expectancy.
"""


def classify_v21_status(result):
    model = result.get("model", "UNCLASSIFIED")
    sweep = result.get("liquidity_sweep") or {}
    breakdown = result.get("breakdown_retest") or {}
    score_breakdown = result.get("score_breakdown") or {}
    filters = result.get("filters") or {}

    return_24h = float(result.get("return_24h_pct") or 0.0)
    supply_distance = result.get("supply_distance_atr")
    supply_near = (
        supply_distance is not None
        and float(supply_distance) <= 1.0
    )
    rejection = bool(result.get("bearish_rejection"))
    one_hour_structure = float(score_breakdown.get("structure_1h") or 0.0)
    ema_reclaimed_bearish = float(result.get("ema20_distance_atr") or 0.0) >= 0.0

    stop_pct = float(result.get("stop_pct") or 999.0)
    support_room_r = float(result.get("support_room_r") or 0.0)
    volatility_ok = bool(filters.get("volatility_ok"))

    reversal_confirmation = bool(
        rejection
        or breakdown.get("retest")
        or one_hour_structure >= 10
        or ema_reclaimed_bearish
    )
    location_ok = bool(supply_near or rejection)
    risk_ok = stop_pct <= 8.0 and support_room_r >= 1.7

    liquidity_ready = bool(
        model == "LIQUIDITY_REVERSAL"
        and sweep.get("detected")
        and return_24h > 0.0
        and reversal_confirmation
        and location_ok
        and volatility_ok
        and risk_ok
    )

    if liquidity_ready:
        status = "ENTRY_READY"
    elif model == "LIQUIDITY_REVERSAL":
        status = "DEVELOPING"
    elif model in ("TREND_CONTINUATION", "SUPPLY_FADE"):
        status = "WATCH"
    else:
        status = "IGNORE"

    return {
        "v21_status": status,
        "v21_priority": (
            "HIGH"
            if liquidity_ready and return_24h >= 5.0
            else "NORMAL"
        ),
        "v21_gate": {
            "model_allowed": model == "LIQUIDITY_REVERSAL",
            "sweep": bool(sweep.get("detected")),
            "positive_24h_context": return_24h > 0.0,
            "top_gainer_context": return_24h >= 5.0,
            "reversal_confirmation": reversal_confirmation,
            "location_ok": location_ok,
            "volatility_ok": volatility_ok,
            "risk_ok": risk_ok,
        },
    }
