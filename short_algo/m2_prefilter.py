"""M2-specific fast prefilter.

Purpose: rank the whole 1H fast universe by proximity to the live M2 lifecycle
without paying the cost of a full 4H deep fetch for every symbol.

This is only a routing layer. It does not create a trade signal and does not
replace the full V4.4.18 M2 evaluator.
"""
from .indicators import atr, return_pct, structure_snapshot, volume_ratio


def _recent_breakdown_proxy(frame, a):
    close = frame["close"].astype(float)
    low = frame["low"].astype(float)
    if len(frame) < 36:
        return {
            "broken": False,
            "bars_ago": None,
            "level": None,
            "closes_below": 0,
            "near_support_atr": 99.0,
        }

    current = float(close.iloc[-1])
    # Use only prior bars when forming each support proxy.
    best = None
    for pos in range(max(24, len(frame) - 16), len(frame)):
        prior = low.iloc[max(0, pos - 24):pos]
        if len(prior) < 12:
            continue
        level = float(prior.min())
        if float(close.iloc[pos]) < level - 0.05 * a:
            best = (pos, level)

    if best is None:
        prior = low.iloc[-25:-1] if len(low) >= 25 else low.iloc[:-1]
        level = float(prior.min()) if len(prior) else current
        return {
            "broken": False,
            "bars_ago": None,
            "level": level,
            "closes_below": int((close.iloc[-8:] < level).sum()),
            "near_support_atr": abs(current - level) / max(a, 1e-12),
        }

    pos, level = best
    later = close.iloc[pos:]
    return {
        "broken": True,
        "bars_ago": len(frame) - 1 - pos,
        "level": level,
        "closes_below": int((later < level).sum()),
        "near_support_atr": abs(current - level) / max(a, 1e-12),
    }


def score_m2_prefilter(symbol, frame, ticker=None, market_risk_off=False):
    snap = structure_snapshot(frame)
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)

    current = float(snap["close"])
    a = max(float(snap["atr"]), 1e-12)
    r4 = return_pct(close, 4)
    r12 = return_pct(close, 12)
    r24 = return_pct(close, 24)
    vratio = volume_ratio(frame)

    breakdown = _recent_breakdown_proxy(frame, a)

    score = 0.0
    reasons = []

    # 1H bearish context proxy for the later 4H macro-bear gate.
    if snap["macro_bear"]:
        score += 16
        reasons.append("1H macro-bear proxy")
    if snap["ema_bear"]:
        score += 14
        reasons.append("1H bearish EMA")
    elif current < float(snap["ema20"]):
        score += 7
    if snap["lower_high"]:
        score += 9
        reasons.append("lower high")
    if snap["lower_low"]:
        score += 8
        reasons.append("lower low")

    # Structural-location proxy: M2 wants price near/below an important support,
    # not a random momentum short far from structure.
    near = float(breakdown["near_support_atr"])
    if breakdown["broken"]:
        score += 20
        reasons.append("recent support-break proxy")
        bars_ago = breakdown["bars_ago"]
        if bars_ago is not None and bars_ago <= 8:
            score += 8
        elif bars_ago is not None and bars_ago <= 16:
            score += 4
    elif near <= 0.40:
        score += 13
        reasons.append("pressing support proxy")
    elif near <= 0.80:
        score += 8
    elif near <= 1.25:
        score += 4

    # Persistence / pressure proxy.
    closes_below = int(breakdown["closes_below"])
    if closes_below >= 5:
        score += 10
        reasons.append("persistent closes below proxy")
    elif closes_below >= 3:
        score += 6
    elif closes_below >= 1:
        score += 2

    # Compression / pressure: repeated lows and limited upside expansion.
    recent = frame.iloc[-12:]
    recent_range_atr = (
        float(recent["high"].max()) - float(recent["low"].min())
    ) / a
    low_band = float(low.iloc[-12:].max() - low.iloc[-12:].min()) / a
    if low_band <= 1.2:
        score += 6
        reasons.append("compressed lows")
    if recent_range_atr <= 4.0:
        score += 3

    # M2 favors active bearish continuation, but avoid selecting already
    # exhausted dumps purely because they rank high on momentum.
    if -6.0 <= r4 <= -0.2:
        score += 8
    elif r4 < -6.0:
        score += 3
    if -12.0 <= r12 <= -0.5:
        score += 6

    ema_distance_atr = (float(snap["ema20"]) - current) / a
    if 0.4 <= ema_distance_atr <= 2.5:
        score += 6
    elif ema_distance_atr > 3.5:
        score -= 10
        reasons.append("overextended below EMA")

    # Participation helps distinguish real pressure from thin noise.
    if vratio >= 1.5:
        score += 5
    elif vratio >= 1.0:
        score += 3

    # Global market risk-off is useful routing context, but not a hard fast gate:
    # keeping some non-risk-off names preserves coverage if regime flips before
    # the next hourly run.
    if market_risk_off:
        score += 8
        reasons.append("market risk-off")

    # Chase / manipulation guardrails.
    if r4 < -10:
        score -= 10
    if r12 < -20:
        score -= 10
    if r24 < -35:
        score -= 8

    turnover = float((ticker or {}).get("turnover_24h") or 0.0)
    if turnover >= 2_000_000:
        score += 3
    elif turnover < 250_000:
        score -= 5

    return {
        "symbol": symbol,
        "m2_prefilter_score": round(max(0.0, min(100.0, score)), 2),
        "m2_proxy_breakdown": bool(breakdown["broken"]),
        "m2_proxy_break_bars_ago": breakdown["bars_ago"],
        "m2_proxy_support_level": breakdown["level"],
        "m2_proxy_near_support_atr": round(near, 3),
        "m2_proxy_closes_below": closes_below,
        "m2_proxy_macro_bear": bool(snap["macro_bear"]),
        "m2_proxy_ema_bear": bool(snap["ema_bear"]),
        "m2_proxy_lower_high": bool(snap["lower_high"]),
        "m2_proxy_lower_low": bool(snap["lower_low"]),
        "m2_proxy_ema20_distance_atr": round(ema_distance_atr, 3),
        "m2_proxy_return_4h_pct": round(r4, 3),
        "m2_proxy_return_12h_pct": round(r12, 3),
        "m2_proxy_return_24h_pct": round(r24, 3),
        "m2_proxy_volume_ratio": round(vratio, 3),
        "m2_proxy_reasons": reasons,
    }
