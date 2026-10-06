"""V4.2.3 continuation-first Short scanner.

SHORT_NOW is intentionally restricted to bear-continuation setups that:
1) genuinely broke support,
2) departed below it,
3) later pulled back into the broken level,
4) rejected without reclaim/acceptance,
5) are not in an obvious local-bottom or squeeze/recovery condition.

Reversal setups remain visible as WAIT_REVERSAL / WATCH only. Score ranks
candidates; structural readiness is the primary SHORT_NOW gate.
"""

import math

from .config import BACKTEST_FEE_BPS_ROUND_TRIP
from .indicators import atr, ema, return_pct, structure_snapshot, volume_ratio
from .v4_regime import route_v4_regime
from .v42_setup import route_v42_setup
from .v422_filter import _preferred_zone, _rebound_bottom_risk
from .v423_config import (
    V423_BREAKDOWN_MAX_AGE_1H,
    V423_MAX_ANTI_BOTTOM_FOR_SHORT_NOW,
    V423_MAX_BULLISH_RETEST_BODY_ATR,
    V423_MAX_MARKET_BOUNCE_4H_PCT,
    V423_MAX_REBOUND_FROM_BREAK_LOW_ATR,
    V423_MAX_RELATIVE_RECOVERY_1H_PCT,
    V423_MAX_RELATIVE_RECOVERY_3H_PCT,
    V423_MAX_RETEST_ACCEPTANCE_BARS,
    V423_MAX_SQUEEZE_RISK,
    V423_MIN_BREAK_BODY_ATR,
    V423_MIN_BREAK_DEPARTURE_ATR,
    V423_MIN_EMIT_SCORE,
    V423_MIN_REJECTION_UPPER_WICK_RATIO,
    V423_MIN_SHORT_NOW_SCORE,
    V423_RECLAIM_INVALIDATION_ATR,
    V423_RECENT_LOW_BLOCK_ATR,
    V423_REFERENCE_STOP_BUFFER_ATR,
    V423_RETEST_CLOSE_BELOW_ATR,
    V423_RETEST_TOUCH_ATR,
    V423_SLIPPAGE_BPS_REFERENCE,
    V423_SUPPORT_BLOCK_ATR,
)


def _clamp(value, lo=0.0, hi=100.0):
    return max(lo, min(hi, float(value)))


def _market_return(frame, bars):
    if frame is None or len(frame) <= bars:
        return 0.0
    return float(return_pct(frame["close"], bars))


def _relative_recovery(one, btc_one, eth_one):
    coin1 = _market_return(one, 1)
    coin3 = _market_return(one, 3)
    btc1 = _market_return(btc_one, 1)
    eth1 = _market_return(eth_one, 1)
    btc3 = _market_return(btc_one, 3)
    eth3 = _market_return(eth_one, 3)
    market1 = (btc1 + eth1) / 2.0
    market3 = (btc3 + eth3) / 2.0
    return {
        "coin_return_1h_pct": round(coin1, 4),
        "coin_return_3h_pct": round(coin3, 4),
        "market_return_1h_pct": round(market1, 4),
        "market_return_3h_pct": round(market3, 4),
        "relative_recovery_1h_pct": round(coin1 - market1, 4),
        "relative_recovery_3h_pct": round(coin3 - market3, 4),
    }


def _bar_metrics(row, a1):
    o = float(row["open"])
    h = float(row["high"])
    l = float(row["low"])
    c = float(row["close"])
    rng = max(h - l, 1e-12)
    body = abs(c - o)
    upper_wick = h - max(o, c)
    return {
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "bearish": c < o,
        "body_atr": body / max(a1, 1e-12),
        "range_atr": rng / max(a1, 1e-12),
        "upper_wick_ratio": upper_wick / rng,
        "close_position": (c - l) / rng,
    }


def _continuation_quality(base, one, a1):
    breakdown = base.get("breakdown_retest") or {}
    level = breakdown.get("level")
    bars_ago = int(breakdown.get("bars_ago") or 999)

    out = {
        "eligible": False,
        "ready": False,
        "quality_score": 0.0,
        "reason": "NO_FRESH_BREAKDOWN",
        "level": level,
        "bars_ago": bars_ago,
        "break_departure_atr": None,
        "break_body_atr": None,
        "retest_touched": False,
        "retest_rejection": False,
        "reclaim_seen": False,
        "acceptance_bars": 0,
        "rebound_from_break_low_atr": None,
    }

    if (
        not breakdown.get("breakdown")
        or level is None
        or bars_ago > V423_BREAKDOWN_MAX_AGE_1H
    ):
        return out

    level = float(level)
    break_pos = len(one) - 1 - bars_ago
    if break_pos < 1 or break_pos >= len(one):
        return out

    break_row = one.iloc[break_pos]
    bm = _bar_metrics(break_row, a1)
    break_departure_atr = max(
        0.0,
        (level - float(break_row["close"])) / max(a1, 1e-12),
    )

    later = one.iloc[break_pos + 1:]
    if later.empty:
        return out

    post_low = float(later["low"].min())
    current = float(one["close"].iloc[-1])
    rebound_from_low = (
        current - post_low
    ) / max(a1, 1e-12)

    reclaim_seen = bool(
        (
            later["close"].astype(float)
            > level + V423_RECLAIM_INVALIDATION_ATR * a1
        ).any()
    )

    touch_mask = (
        later["high"].astype(float)
        >= level - V423_RETEST_TOUCH_ATR * a1
    )
    touch_positions = [
        i for i, value in enumerate(touch_mask.tolist())
        if value
    ]
    touched = bool(touch_positions)

    acceptance_bars = int(
        (
            (
                later["close"].astype(float)
                >= level - V423_RETEST_TOUCH_ATR * a1
            )
            & (
                later["close"].astype(float)
                <= level + V423_RECLAIM_INVALIDATION_ATR * a1
            )
        ).sum()
    )

    last = _bar_metrics(one.iloc[-1], a1)
    latest_touch = (
        last["high"]
        >= level - V423_RETEST_TOUCH_ATR * a1
    )
    closes_back_below = (
        last["close"]
        <= level - V423_RETEST_CLOSE_BELOW_ATR * a1
    )
    bearish_rejection = bool(
        last["bearish"]
        and (
            last["upper_wick_ratio"]
            >= V423_MIN_REJECTION_UPPER_WICK_RATIO
            or last["close_position"] <= 0.40
        )
    )
    bullish_retest_too_strong = bool(
        not last["bearish"]
        and last["body_atr"] >= V423_MAX_BULLISH_RETEST_BODY_ATR
    )

    departure_ok = (
        break_departure_atr >= V423_MIN_BREAK_DEPARTURE_ATR
        and bm["body_atr"] >= V423_MIN_BREAK_BODY_ATR
    )
    rejection_ok = bool(
        latest_touch
        and closes_back_below
        and bearish_rejection
        and not bullish_retest_too_strong
    )
    acceptance_ok = (
        acceptance_bars <= V423_MAX_RETEST_ACCEPTANCE_BARS
    )

    quality = 0.0
    quality += min(25.0, break_departure_atr * 20.0)
    quality += min(15.0, bm["body_atr"] * 15.0)
    if touched:
        quality += 15.0
    if rejection_ok:
        quality += 25.0
    if not reclaim_seen:
        quality += 10.0
    if acceptance_ok:
        quality += 10.0

    ready = bool(
        departure_ok
        and touched
        and rejection_ok
        and not reclaim_seen
        and acceptance_ok
    )

    if reclaim_seen:
        reason = "BROKEN_SUPPORT_RECLAIMED"
    elif not departure_ok:
        reason = "WEAK_BREAKDOWN_DEPARTURE"
    elif not touched:
        reason = "WAIT_PULLBACK_TO_BROKEN_SUPPORT"
    elif not latest_touch:
        reason = "RETEST_WAS_NOT_CURRENT"
    elif not closes_back_below:
        reason = "RETEST_FAILED_TO_CLOSE_BELOW"
    elif not bearish_rejection:
        reason = "NO_CLEAR_BEARISH_REJECTION"
    elif not acceptance_ok:
        reason = "TOO_MUCH_ACCEPTANCE_AT_LEVEL"
    else:
        reason = "CONTINUATION_RETEST_CONFIRMED"

    out.update({
        "eligible": True,
        "ready": ready,
        "quality_score": round(_clamp(quality, 0.0, 100.0), 3),
        "reason": reason,
        "level": level,
        "break_departure_atr": round(break_departure_atr, 4),
        "break_body_atr": round(bm["body_atr"], 4),
        "break_volume_ratio": round(
            float(
                one["volume"].iloc[break_pos]
                / max(
                    float(
                        one["volume"].iloc[
                            max(0, break_pos - 20):break_pos
                        ].median()
                    ),
                    1e-12,
                )
            ),
            4,
        ) if break_pos > 0 else 1.0,
        "retest_touched": touched,
        "retest_rejection": rejection_ok,
        "reclaim_seen": reclaim_seen,
        "acceptance_bars": acceptance_bars,
        "rebound_from_break_low_atr": round(rebound_from_low, 4),
        "latest_retest_body_atr": round(last["body_atr"], 4),
        "latest_retest_upper_wick_ratio": round(
            last["upper_wick_ratio"], 4
        ),
        "latest_retest_close_position": round(
            last["close_position"], 4
        ),
    })
    return out


def _squeeze_risk(
    regime,
    recovery,
    continuation,
):
    score = 0.0
    reasons = []

    market_r4 = float(regime.get("market_r4") or 0.0)
    if market_r4 >= V423_MAX_MARKET_BOUNCE_4H_PCT:
        score += 3.0
        reasons.append("MARKET_4H_BOUNCE")
    if regime.get("risk_state") == "RISK_ON":
        score += 4.0
        reasons.append("MARKET_RISK_ON")
    if regime.get("trend_state") == "BULL":
        score += 3.0
        reasons.append("MARKET_BULL_TREND")

    rr1 = float(recovery.get("relative_recovery_1h_pct") or 0.0)
    rr3 = float(recovery.get("relative_recovery_3h_pct") or 0.0)
    if rr1 >= V423_MAX_RELATIVE_RECOVERY_1H_PCT:
        score += 3.0
        reasons.append("COIN_RELATIVE_RECOVERY_1H")
    if rr3 >= V423_MAX_RELATIVE_RECOVERY_3H_PCT:
        score += 3.0
        reasons.append("COIN_RELATIVE_RECOVERY_3H")

    rebound = float(
        continuation.get("rebound_from_break_low_atr") or 0.0
    )
    if rebound >= V423_MAX_REBOUND_FROM_BREAK_LOW_ATR:
        score += 3.0
        reasons.append("FAST_REBOUND_FROM_BREAK_LOW")

    if continuation.get("reclaim_seen"):
        score += 6.0
        reasons.append("BROKEN_LEVEL_RECLAIM")

    return {
        "squeeze_risk": round(score, 3),
        "squeeze_reasons": reasons,
    }


def _directional_rank(s1, s4, regime, rel4, rel24):
    score = 0.0
    if s4["ema_bear"]:
        score += 4.0
    if s4["lower_high"]:
        score += 3.0
    if s4["lower_low"]:
        score += 2.0
    if s1["ema_bear"]:
        score += 2.0
    if s1["lower_high"]:
        score += 2.0
    if rel4 <= -1.0:
        score += 2.0
    if rel24 <= -3.0:
        score += 2.0
    if regime.get("risk_state") == "RISK_OFF":
        score += 2.0
    if regime.get("trend_state") == "BEAR":
        score += 1.0
    return _clamp(score, 0.0, 20.0)


def _reference_plan(zone, a1):
    if zone is None:
        return {}
    lower = float(zone["lower"])
    upper = float(zone["upper"])
    entry = lower * 0.35 + upper * 0.65
    stop = max(upper, entry) + V423_REFERENCE_STOP_BUFFER_ATR * a1
    risk = stop - entry
    if risk <= 0:
        return {}

    fee_r = (
        entry * float(BACKTEST_FEE_BPS_ROUND_TRIP) / 10000.0
    ) / risk
    slippage_r = (
        entry * float(V423_SLIPPAGE_BPS_REFERENCE) / 10000.0
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


def build_v423_candidate(base, one, four, btc_one, eth_one):
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
    rel4 = r4 - market_r4
    rel24 = r24 - market_r24

    setup = route_v42_setup(base, one, four, btc_one, eth_one)
    setup_type = str(
        (setup or {}).get("v42_setup")
        or "BEARISH_BIAS_WATCH"
    )
    subtype = str(
        (setup or {}).get("v42_subtype")
        or "CONTEXT_ONLY"
    )

    bearish_context = bool(
        s4["ema_bear"]
        or s4["lower_high"]
        or rel24 <= -3.0
    )
    if setup is None and not bearish_context:
        return None

    zone = _preferred_zone(base, setup, one)
    continuation = _continuation_quality(base, one, a1)
    recovery = _relative_recovery(one, btc_one, eth_one)
    squeeze = _squeeze_risk(regime, recovery, continuation)
    anti_bottom = _rebound_bottom_risk(
        base,
        one,
        current,
        a1,
        base.get("nearest_support"),
    )

    # Tighten local-bottom protection for manual SHORT_NOW.
    low12 = float(one["low"].tail(12).min())
    distance_12h_low_atr = (
        current - low12
    ) / max(a1, 1e-12)
    support_distance_atr = anti_bottom.get("support_distance_atr")
    bottom_block = bool(
        float(anti_bottom["anti_bottom_total"])
        > V423_MAX_ANTI_BOTTOM_FOR_SHORT_NOW
        or distance_12h_low_atr < V423_RECENT_LOW_BLOCK_ATR
        or (
            support_distance_atr is not None
            and float(support_distance_atr) < V423_SUPPORT_BLOCK_ATR
        )
    )

    directional = _directional_rank(
        s1, s4, regime, rel4, rel24
    )
    continuation_quality = float(
        continuation.get("quality_score") or 0.0
    )

    # Rank score, not an automatic trade probability.
    score = _clamp(
        directional
        + 0.55 * continuation_quality
        - 1.25 * float(anti_bottom["anti_bottom_total"])
        - 1.50 * float(squeeze["squeeze_risk"]),
        0.0,
        100.0,
    )

    if directional >= 13.0:
        bias = "STRONG_SHORT_BIAS"
    elif directional >= 8.0:
        bias = "SHORT_BIAS"
    else:
        bias = "WEAK_SHORT_BIAS"

    continuation_short_now = bool(
        setup_type == "BEAR_CONTINUATION_RETEST"
        and continuation.get("ready")
        and not bottom_block
        and float(squeeze["squeeze_risk"]) <= V423_MAX_SQUEEZE_RISK
        and score >= V423_MIN_SHORT_NOW_SCORE
        and regime.get("risk_state") != "RISK_ON"
    )

    # Reversal is deliberately research/watch-only in V4.2.3.
    if continuation_short_now:
        action = "SHORT_NOW"
        action_reason = "CONTINUATION_RETEST_CONFIRMED"
    elif bottom_block:
        action = "AVOID_BOTTOM_SHORT"
        action_reason = "ANTI_BOTTOM_BLOCK"
    elif setup_type == "REVERSAL_AT_LOCATION":
        action = "WAIT_REVERSAL"
        action_reason = "REVERSAL_NOT_PROMOTED_TO_SHORT_NOW"
    elif setup_type == "BEAR_CONTINUATION_RETEST":
        action = "WAIT_PULLBACK"
        action_reason = str(continuation.get("reason"))
    elif bias in ("SHORT_BIAS", "STRONG_SHORT_BIAS"):
        action = "WAIT_PULLBACK"
        action_reason = "BEARISH_BIAS_NEEDS_LOCATION"
    else:
        action = "WATCH_ONLY"
        action_reason = "WEAK_BIAS"

    if score < V423_MIN_EMIT_SCORE and action == "WATCH_ONLY":
        return None

    reference = _reference_plan(zone, a1)

    return {
        "v423_bias": bias,
        "v423_action": action,
        "v423_action_reason": action_reason,
        "v423_score": round(score, 3),
        "v423_thesis": setup_type,
        "v423_subtype": subtype,
        "directional_score": round(directional, 3),
        "continuation_quality_score": round(
            continuation_quality, 3
        ),
        "bottom_risk": anti_bottom["bottom_risk"],
        "rebound_risk": anti_bottom["rebound_risk"],
        "anti_bottom_total": anti_bottom["anti_bottom_total"],
        "bottom_block": bottom_block,
        "bottom_reasons": anti_bottom["bottom_reasons"],
        "squeeze_risk": squeeze["squeeze_risk"],
        "squeeze_reasons": squeeze["squeeze_reasons"],
        "relative_4h_pct": round(rel4, 4),
        "relative_24h_pct": round(rel24, 4),
        **recovery,
        "regime": regime,
        "current_price": current,
        "atr_1h": a1,
        "zone_source": None if zone is None else zone.get("source"),
        "preferred_zone_lower": None if zone is None else zone.get("lower"),
        "preferred_zone_upper": None if zone is None else zone.get("upper"),
        "continuation_ready": bool(continuation.get("ready")),
        "continuation_reason": continuation.get("reason"),
        "breakdown_level": continuation.get("level"),
        "breakdown_bars_ago": continuation.get("bars_ago"),
        "break_departure_atr": continuation.get("break_departure_atr"),
        "break_body_atr": continuation.get("break_body_atr"),
        "break_volume_ratio": continuation.get("break_volume_ratio"),
        "retest_touched": continuation.get("retest_touched"),
        "retest_rejection": continuation.get("retest_rejection"),
        "reclaim_seen": continuation.get("reclaim_seen"),
        "acceptance_bars": continuation.get("acceptance_bars"),
        "rebound_from_break_low_atr": continuation.get(
            "rebound_from_break_low_atr"
        ),
        "latest_retest_body_atr": continuation.get(
            "latest_retest_body_atr"
        ),
        "latest_retest_upper_wick_ratio": continuation.get(
            "latest_retest_upper_wick_ratio"
        ),
        "distance_12h_low_atr": round(
            distance_12h_low_atr, 4
        ),
        **reference,
        "execution_note": (
            "Reference only. User controls actual entry. "
            "Slippage is advisory, not a filter."
        ),
    }
