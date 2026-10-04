from .config import (
    DEVELOPING_SCORE,
    ENTRY_READY_SCORE,
    MAX_ABS_24H_CHANGE_PCT,
    MAX_ATR_PCT,
    MAX_ENTRY_DISTANCE_ATR,
    MAX_SPREAD_BPS,
    MAX_STOP_PCT,
    MIN_ATR_PCT,
    MIN_STOP_ATR,
    RUNNER_R,
    TP1_R,
    TP2_R,
    WATCH_SCORE,
)
from .indicators import (
    atr,
    bearish_rejection,
    return_pct,
    safe_float,
    structure_snapshot,
    volume_ratio,
)


def _change_pct(ticker):
    value = safe_float((ticker or {}).get("change_rate_24h"), 0.0) or 0.0
    return value * 100.0 if abs(value) <= 2 else value


def _liquidity_points(ticker):
    turnover = safe_float((ticker or {}).get("turnover_24h"), 0.0) or 0.0
    if turnover >= 50_000_000:
        return 12
    if turnover >= 10_000_000:
        return 10
    if turnover >= 2_000_000:
        return 7
    if turnover >= 500_000:
        return 4
    return 0


def _spread_penalty(ticker):
    spread = safe_float((ticker or {}).get("spread_bps"))
    if spread is None:
        return 0
    if spread > 60:
        return -20
    if spread > 40:
        return -12
    if spread > 25:
        return -6
    return 0


def _funding_points(ticker):
    funding = safe_float((ticker or {}).get("funding_rate"))
    if funding is None:
        return 0
    if funding >= 0.0008:
        return 5
    if funding >= 0.0002:
        return 3
    if funding <= -0.001:
        return -8
    if funding <= -0.0004:
        return -4
    return 0


def score_fast_short(symbol, frame, ticker):
    snap = structure_snapshot(frame)
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)

    current = snap["close"]
    a = max(snap["atr"], 1e-12)
    r4 = return_pct(close, 4)
    r12 = return_pct(close, 12)
    r24 = return_pct(close, 24)
    vratio = volume_ratio(frame)
    change24 = _change_pct(ticker)

    prior_high = float(high.iloc[-21:-1].max()) if len(high) >= 21 else float(high.max())
    high_distance_atr = max(0.0, prior_high - current) / a
    ema20_distance_atr = (snap["ema20"] - current) / a

    breakdown_points = 0
    if snap["ema_bear"]:
        breakdown_points += 18
    elif current < snap["ema20"]:
        breakdown_points += 9
    if snap["lower_high"]:
        breakdown_points += 8
    if snap["lower_low"]:
        breakdown_points += 8
    if snap["macro_bear"]:
        breakdown_points += 5
    breakdown_points = min(34, breakdown_points)

    momentum_points = 0
    if -6.0 <= r4 <= -0.25:
        momentum_points += 8
    elif -10.0 <= r4 < -6.0:
        momentum_points += 4
    if -12.0 <= r12 <= -0.5:
        momentum_points += 6
    if r4 > 0 and high_distance_atr <= 1.0:
        momentum_points += 5

    location_points = 0
    abs_ema_distance = abs(current - snap["ema20"]) / a
    if abs_ema_distance <= 0.45:
        location_points = 12
    elif abs_ema_distance <= 0.9:
        location_points = 8
    elif high_distance_atr <= 0.8:
        location_points = 7
    elif high_distance_atr <= 1.5:
        location_points = 4

    atr_pct = snap["atr_pct"]
    if 0.35 <= atr_pct <= 5.0:
        volatility_points = 10
    elif MIN_ATR_PCT <= atr_pct <= MAX_ATR_PCT:
        volatility_points = 6
    else:
        volatility_points = 0

    volume_points = 8 if vratio >= 1.5 else (5 if vratio >= 1.0 else 2)
    liquidity_points = _liquidity_points(ticker)
    participation_points = _funding_points(ticker)

    chase_penalty = 0
    if r4 < -8:
        chase_penalty -= 8
    if r12 < -18:
        chase_penalty -= 10
    if ema20_distance_atr > 2.2:
        chase_penalty -= min(20, int((ema20_distance_atr - 2.2) * 6))
    if change24 < -30:
        chase_penalty -= 12
    if abs(change24) > MAX_ABS_24H_CHANGE_PCT:
        chase_penalty -= 15

    score = max(
        0.0,
        min(
            100.0,
            breakdown_points
            + momentum_points
            + location_points
            + volatility_points
            + volume_points
            + liquidity_points
            + participation_points
            + _spread_penalty(ticker)
            + chase_penalty,
        ),
    )

    return {
        "symbol": symbol,
        "fast_score": round(score, 2),
        "return_4h_pct": round(r4, 3),
        "return_12h_pct": round(r12, 3),
        "return_24h_pct": round(r24, 3),
        "ticker_change_24h_pct": round(change24, 3),
        "atr_pct_1h": round(atr_pct, 3),
        "volume_ratio_1h": round(vratio, 3),
        "ema20_distance_atr": round(ema20_distance_atr, 3),
        "high_distance_atr": round(high_distance_atr, 3),
        "turnover_24h": safe_float((ticker or {}).get("turnover_24h"), 0.0) or 0.0,
        "spread_bps": safe_float((ticker or {}).get("spread_bps")),
        "funding_rate": safe_float((ticker or {}).get("funding_rate")),
        "fast_breakdown": {
            "bear_structure": breakdown_points,
            "momentum": momentum_points,
            "location": location_points,
            "volatility": volatility_points,
            "volume": volume_points,
            "liquidity": liquidity_points,
            "funding": participation_points,
            "spread_penalty": _spread_penalty(ticker),
            "chase_penalty": chase_penalty,
        },
    }


def _find_supply_zone(frame):
    atr_series = atr(frame)
    start = max(5, len(frame) - 75)
    current = float(frame["close"].iloc[-1])
    candidates = []

    for i in range(start, len(frame) - 4):
        row = frame.iloc[i]
        a = float(atr_series.iloc[i]) if atr_series.iloc[i] == atr_series.iloc[i] else 0.0
        if a <= 0:
            continue
        o, h, l, c = map(float, [row["open"], row["high"], row["low"], row["close"]])
        next_slice = frame.iloc[i + 1:i + 5]
        future_low = float(next_slice["low"].min())
        displacement = (l - future_low) / a
        body = abs(c - o)
        candle_range = max(h - l, 1e-12)
        base_like = c >= o or body / candle_range <= 0.45
        if base_like and displacement >= 1.15:
            lower = min(o, c)
            upper = h
            distance = 0.0 if lower <= current <= upper else min(abs(current - lower), abs(current - upper))
            candidates.append({
                "lower": lower,
                "upper": upper,
                "time": frame.index[i].isoformat(),
                "displacement_atr": displacement,
                "distance": distance,
            })

    if not candidates:
        return None

    above_or_near = [z for z in candidates if z["upper"] >= current * 0.995]
    pool = above_or_near or candidates
    return min(pool, key=lambda z: z["distance"])


def _detect_liquidity_sweep(frame):
    if len(frame) < 35:
        return {"detected": False, "level": None, "bars_ago": None}

    high = frame["high"].astype(float)
    close = frame["close"].astype(float)
    for pos in range(len(frame) - 1, max(20, len(frame) - 9), -1):
        prior_high = float(high.iloc[pos - 20:pos].max())
        if float(high.iloc[pos]) > prior_high * 1.001 and float(close.iloc[pos]) < prior_high:
            return {
                "detected": True,
                "level": prior_high,
                "bars_ago": len(frame) - 1 - pos,
            }
    return {"detected": False, "level": None, "bars_ago": None}


def _detect_breakdown_retest(frame):
    if len(frame) < 45:
        return {"breakdown": False, "retest": False, "level": None, "bars_ago": None}

    low = frame["low"].astype(float)
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    a = float(atr(frame).iloc[-1])

    for pos in range(len(frame) - 1, max(22, len(frame) - 13), -1):
        level = float(low.iloc[pos - 20:pos].min())
        if float(close.iloc[pos]) < level - 0.10 * a:
            later = frame.iloc[pos + 1:]
            retest = False
            if not later.empty:
                retest = bool(
                    ((later["high"].astype(float) >= level - 0.15 * a)
                     & (later["close"].astype(float) <= level + 0.10 * a)).any()
                )
            current = float(close.iloc[-1])
            near_level = abs(current - level) / max(a, 1e-12) <= 0.55
            return {
                "breakdown": True,
                "retest": bool(retest or near_level),
                "level": level,
                "bars_ago": len(frame) - 1 - pos,
            }

    return {"breakdown": False, "retest": False, "level": None, "bars_ago": None}


def _support_room_rr(entry, risk, snap_1h, snap_4h):
    levels = []
    for snap in (snap_1h, snap_4h):
        for point in snap["swing_lows"][-6:]:
            price = float(point["price"])
            if price < entry:
                levels.append(price)
    if not levels:
        return 5.0, None
    nearest = max(levels)
    return max(0.0, (entry - nearest) / max(risk, 1e-12)), nearest


def _supply_distance_atr(zone, current, a):
    if not zone:
        return None
    if zone["lower"] <= current <= zone["upper"]:
        return 0.0
    return min(abs(current - zone["lower"]), abs(current - zone["upper"])) / max(a, 1e-12)


def analyze_short(symbol, frames, ticker, fast_row=None):
    one = frames["1H"]
    four = frames["4H"]
    s1 = structure_snapshot(one)
    s4 = structure_snapshot(four)
    current = s1["close"]
    a = max(s1["atr"], 1e-12)

    supply_1h = _find_supply_zone(one)
    supply_4h = _find_supply_zone(four)
    sweep = _detect_liquidity_sweep(one)
    breakdown = _detect_breakdown_retest(one)
    rejection = bearish_rejection(one.iloc[-1])

    d1 = _supply_distance_atr(supply_1h, current, a)
    d4 = _supply_distance_atr(supply_4h, current, a)

    structure_4h = 0
    if s4["ema_bear"]:
        structure_4h += 11
    if s4["lower_high"]:
        structure_4h += 6
    if s4["lower_low"]:
        structure_4h += 5
    if s4["macro_bear"]:
        structure_4h += 3
    structure_4h = min(25, structure_4h)

    structure_1h = 0
    if s1["ema_bear"]:
        structure_1h += 10
    if s1["lower_high"]:
        structure_1h += 7
    if s1["lower_low"]:
        structure_1h += 5
    if current < s1["ema20"]:
        structure_1h += 3
    structure_1h = min(25, structure_1h)

    trigger_points = 0
    if breakdown["breakdown"]:
        trigger_points += 7
    if breakdown["retest"]:
        trigger_points += 5
    if sweep["detected"]:
        trigger_points += 6
    if rejection:
        trigger_points += 4
    trigger_points = min(20, trigger_points)

    location_points = 0
    nearest_supply_distance = min([x for x in (d1, d4) if x is not None], default=None)
    ema_pullback_distance = abs(current - s1["ema20"]) / a
    if nearest_supply_distance is not None and nearest_supply_distance <= 0.35:
        location_points = 15
    elif nearest_supply_distance is not None and nearest_supply_distance <= 0.75:
        location_points = 11
    elif ema_pullback_distance <= 0.45:
        location_points = 9
    elif ema_pullback_distance <= 0.9:
        location_points = 5

    recent_high = float(one["high"].iloc[-12:].max())
    stop_anchor = recent_high
    for zone in (supply_1h, supply_4h):
        if zone and zone["upper"] >= current:
            stop_anchor = max(stop_anchor, float(zone["upper"]))

    raw_risk = stop_anchor + 0.15 * a - current
    risk = max(raw_risk, MIN_STOP_ATR * a)
    stop = current + risk
    stop_pct = risk / max(current, 1e-12) * 100.0

    support_rr, nearest_support = _support_room_rr(current, risk, s1, s4)
    if support_rr >= 3.0:
        rr_points = 15
    elif support_rr >= 2.2:
        rr_points = 12
    elif support_rr >= 1.7:
        rr_points = 7
    elif support_rr >= 1.2:
        rr_points = 3
    else:
        rr_points = -8

    participation_points = min(8, _liquidity_points(ticker) // 2 + max(0, _funding_points(ticker)))
    if volume_ratio(one) >= 1.2:
        participation_points += 2
    participation_points = min(10, participation_points)

    r4 = return_pct(one["close"], 4)
    r12 = return_pct(one["close"], 12)
    ema_distance = (s1["ema20"] - current) / a
    chase_penalty = 0
    if r4 < -8:
        chase_penalty -= 8
    if r12 < -18:
        chase_penalty -= 8
    if ema_distance > 2.2:
        chase_penalty -= 12
    if stop_pct > MAX_STOP_PCT:
        chase_penalty -= 15

    manipulation_penalty = 0
    change24 = _change_pct(ticker)
    last_range_atr = (
        float(one["high"].iloc[-1]) - float(one["low"].iloc[-1])
    ) / a
    if abs(change24) > 55:
        manipulation_penalty -= 8
    if last_range_atr > 4.0:
        manipulation_penalty -= 8
    spread_penalty = _spread_penalty(ticker)

    score_breakdown = {
        "structure_4h": structure_4h,
        "structure_1h": structure_1h,
        "trigger": trigger_points,
        "location": location_points,
        "rr_room": rr_points,
        "participation": participation_points,
        "spread_penalty": spread_penalty,
        "chase_penalty": chase_penalty,
        "manipulation_penalty": manipulation_penalty,
    }
    score = max(0.0, min(100.0, sum(score_breakdown.values())))

    trigger_present = bool(
        sweep["detected"]
        or rejection
        or breakdown["retest"]
        or (breakdown["breakdown"] and ema_pullback_distance <= 0.8)
    )
    mtf_ok = structure_4h >= 14 and structure_1h >= 14
    volatility_ok = MIN_ATR_PCT <= s1["atr_pct"] <= MAX_ATR_PCT
    location_ok = (
        nearest_supply_distance is not None and nearest_supply_distance <= MAX_ENTRY_DISTANCE_ATR
    ) or ema_pullback_distance <= MAX_ENTRY_DISTANCE_ATR or breakdown["retest"]
    risk_ok = stop_pct <= MAX_STOP_PCT and support_rr >= 1.7

    if (
        score >= ENTRY_READY_SCORE
        and trigger_present
        and mtf_ok
        and volatility_ok
        and location_ok
        and risk_ok
    ):
        status = "ENTRY_READY"
    elif score >= DEVELOPING_SCORE and mtf_ok and volatility_ok and risk_ok:
        status = "DEVELOPING"
    elif score >= WATCH_SCORE:
        status = "WATCH"
    else:
        status = "IGNORE"

    reasons = []
    if s4["ema_bear"]:
        reasons.append("4H bearish EMA structure")
    if s4["lower_high"] and s4["lower_low"]:
        reasons.append("4H lower-high/lower-low")
    if s1["lower_high"]:
        reasons.append("1H lower-high")
    if sweep["detected"]:
        reasons.append("upper liquidity sweep")
    if breakdown["retest"]:
        reasons.append("breakdown + retest")
    elif breakdown["breakdown"]:
        reasons.append("fresh breakdown")
    if rejection:
        reasons.append("bearish rejection candle")
    if supply_1h and d1 is not None and d1 <= 0.75:
        reasons.append("near 1H supply")
    if chase_penalty < 0:
        reasons.append("short-chase penalty active")

    return {
        "symbol": symbol,
        "direction": "SHORT",
        "status": status,
        "score": round(score, 2),
        "score_breakdown": score_breakdown,
        "reasons": reasons,
        "current_price": current,
        "entry": current,
        "stop": stop,
        "stop_pct": round(stop_pct, 3),
        "risk_per_unit": risk,
        "tp1": current - TP1_R * risk,
        "tp1_r": TP1_R,
        "tp2": current - TP2_R * risk,
        "tp2_r": TP2_R,
        "runner": current - RUNNER_R * risk,
        "runner_r": RUNNER_R,
        "support_room_r": round(support_rr, 3),
        "nearest_support": nearest_support,
        "atr_pct_1h": round(s1["atr_pct"], 3),
        "supply_1h": supply_1h,
        "supply_4h": supply_4h,
        "supply_distance_atr": None if nearest_supply_distance is None else round(nearest_supply_distance, 3),
        "ema20_distance_atr": round(ema_distance, 3),
        "liquidity_sweep": sweep,
        "breakdown_retest": breakdown,
        "bearish_rejection": rejection,
        "ticker_change_24h_pct": round(change24, 3),
        "turnover_24h": safe_float((ticker or {}).get("turnover_24h"), 0.0) or 0.0,
        "spread_bps": safe_float((ticker or {}).get("spread_bps")),
        "funding_rate": safe_float((ticker or {}).get("funding_rate")),
        "fast_score": None if not fast_row else fast_row.get("fast_score"),
        "filters": {
            "trigger_present": trigger_present,
            "mtf_ok": mtf_ok,
            "volatility_ok": volatility_ok,
            "location_ok": location_ok,
            "risk_ok": risk_ok,
        },
    }
