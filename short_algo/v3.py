"""V3 multi-strategy Short engine.

V3 is research-only and intentionally separate from the live V1 scanner.
It routes market conditions into multiple Short setup engines instead of
forcing every trade through one global score.
"""

import math

from .config import (
    BACKTEST_FEE_BPS_ROUND_TRIP,
    BACKTEST_SLIPPAGE_BPS_ROUND_TRIP,
    V3_MAX_COST_R,
    V3_MAX_STOP_PCT,
    V3_MIN_SUPPORT_ROOM_R,
)
from .indicators import atr, bearish_rejection, ema, return_pct, structure_snapshot, volume_ratio


ENGINE_THRESHOLDS = {
    "EXTREME_PUMP_REVERSAL": 68.0,
    "EXHAUSTION_REVERSAL": 66.0,
    "BREAKDOWN_RETEST": 65.0,
    "RELATIVE_WEAKNESS": 64.0,
    "FAILED_BREAKOUT_SUPPLY_FADE": 65.0,
}


def _bollinger_state(frame, period=20, width=2.0):
    close = frame["close"].astype(float)
    if len(close) < period + 2:
        return {"z": 0.0, "failed_upper": False}
    mean = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    m = float(mean.iloc[-1])
    s = float(std.iloc[-1])
    if not math.isfinite(s) or s <= 0:
        return {"z": 0.0, "failed_upper": False}
    upper = m + width * s
    return {
        "z": (float(close.iloc[-1]) - m) / s,
        "failed_upper": bool(
            float(frame["high"].iloc[-1]) > upper
            and float(close.iloc[-1]) < upper
        ),
    }


def _rolling_vwap(frame, bars=24):
    view = frame.tail(max(5, bars))
    vol = view["volume"].astype(float)
    typical = (
        view["high"].astype(float)
        + view["low"].astype(float)
        + view["close"].astype(float)
    ) / 3.0
    denom = float(vol.sum())
    if denom <= 0:
        return float(view["close"].iloc[-1])
    return float((typical * vol).sum() / denom)


def _micro_trigger(frame):
    if frame is None or len(frame) < 40:
        return {
            "score": 0,
            "close_below_ema20": False,
            "lower_high": False,
            "lower_low": False,
            "breakdown": False,
            "failed_reclaim": False,
            "rejection": False,
            "sweep": False,
        }

    snap = structure_snapshot(frame)
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    e20 = ema(close, 20)

    prior_low = float(low.iloc[-9:-1].min())
    breakdown = float(close.iloc[-1]) < prior_low

    recent = frame.tail(4)
    rejection = any(bearish_rejection(recent.iloc[i]) for i in range(len(recent)))

    recent_high = high.tail(5)
    recent_e20 = e20.tail(5)
    failed_reclaim = bool(
        float(close.iloc[-1]) < float(e20.iloc[-1])
        and bool((recent_high >= recent_e20 * 0.995).any())
    )

    prior_high = float(high.iloc[-13:-1].max())
    sweep = bool(
        float(high.iloc[-1]) > prior_high * 1.0005
        and float(close.iloc[-1]) < prior_high
    )

    score = 0
    if float(close.iloc[-1]) < float(e20.iloc[-1]):
        score += 4
    if snap["lower_high"]:
        score += 5
    if snap["lower_low"]:
        score += 4
    if failed_reclaim:
        score += 5
    if rejection:
        score += 3
    if breakdown:
        score += 2
    if sweep:
        score += 2

    return {
        "score": min(20, score),
        "close_below_ema20": bool(float(close.iloc[-1]) < float(e20.iloc[-1])),
        "lower_high": bool(snap["lower_high"]),
        "lower_low": bool(snap["lower_low"]),
        "breakdown": breakdown,
        "failed_reclaim": failed_reclaim,
        "rejection": rejection,
        "sweep": sweep,
    }


def _market_leg(frame):
    if frame is None or len(frame) < 60:
        return None
    snap = structure_snapshot(frame)
    close = frame["close"].astype(float)
    return {
        "r4": return_pct(close, 4),
        "r24": return_pct(close, 24),
        "above_ema20": bool(snap["close"] > snap["ema20"]),
        "below_ema20": bool(snap["close"] < snap["ema20"]),
        "ema_bear": bool(snap["ema_bear"]),
    }


def market_router(btc_one, eth_one):
    btc = _market_leg(btc_one)
    eth = _market_leg(eth_one)
    if btc is None or eth is None:
        return {
            "state": "UNKNOWN",
            "avg_r4": 0.0,
            "avg_r24": 0.0,
            "btc": btc,
            "eth": eth,
        }

    avg_r4 = (btc["r4"] + eth["r4"]) / 2.0
    avg_r24 = (btc["r24"] + eth["r24"]) / 2.0
    both_above = btc["above_ema20"] and eth["above_ema20"]
    both_below = btc["below_ema20"] and eth["below_ema20"]

    if avg_r4 >= 1.2 and avg_r24 >= 2.5 and both_above:
        state = "RISK_ON"
    elif avg_r4 <= -0.8 and avg_r24 <= 0.0 and both_below:
        state = "RISK_OFF"
    else:
        state = "NEUTRAL"

    return {
        "state": state,
        "avg_r4": round(avg_r4, 3),
        "avg_r24": round(avg_r24, 3),
        "btc": btc,
        "eth": eth,
    }


def _execution_plan(result, fifteen):
    if fifteen is None or len(fifteen) < 20:
        return None

    entry = float(fifteen["close"].iloc[-1])
    a15 = float(atr(fifteen).iloc[-1])
    if not math.isfinite(a15) or a15 <= 0:
        return None

    recent_high = float(fifteen["high"].iloc[-12:].max())
    risk = max(recent_high + 0.10 * a15 - entry, 1.0 * a15)
    if risk <= 0:
        return None

    stop = entry + risk
    stop_pct = risk / max(entry, 1e-12) * 100.0

    nearest_support = result.get("nearest_support")
    if nearest_support is not None and float(nearest_support) < entry:
        support_room_r = (entry - float(nearest_support)) / risk
    else:
        support_room_r = 5.0

    total_cost_bps = (
        float(BACKTEST_FEE_BPS_ROUND_TRIP)
        + float(BACKTEST_SLIPPAGE_BPS_ROUND_TRIP)
    )
    projected_cost_r = (entry * total_cost_bps / 10000.0) / risk

    risk_ok = bool(
        stop_pct <= V3_MAX_STOP_PCT
        and support_room_r >= V3_MIN_SUPPORT_ROOM_R
        and projected_cost_r <= V3_MAX_COST_R
    )

    return {
        "entry": entry,
        "stop": stop,
        "risk": risk,
        "stop_pct": round(stop_pct, 3),
        "support_room_r": round(support_room_r, 3),
        "projected_cost_r": round(projected_cost_r, 4),
        "risk_ok": risk_ok,
        "tp1": entry - 2.0 * risk,
        "tp2": entry - 3.0 * risk,
        "runner": entry - 5.0 * risk,
    }


def _cap(value, lo=0.0, hi=100.0):
    return max(lo, min(hi, float(value)))


def _make_candidate(engine, score, hard_ok, components, reasons, common):
    threshold = ENGINE_THRESHOLDS[engine]
    if hard_ok and common["plan"]["risk_ok"] and score >= threshold:
        status = "ENTRY_READY"
    elif score >= 50.0:
        status = "WATCH"
    else:
        status = "IGNORE"

    return {
        "v3_engine": engine,
        "v3_status": status,
        "v3_score": round(_cap(score), 2),
        "v3_threshold": threshold,
        "v3_primary": False,
        "v3_components": components,
        "v3_reasons": reasons,
        "v3_regime": common["regime"]["state"],
        "v3_regime_detail": common["regime"],
        "v3_micro": common["micro"],
        "v3_relative_4h_pct": round(common["relative_4h"], 3),
        "v3_relative_24h_pct": round(common["relative_24h"], 3),
        "v3_projected_cost_r": common["plan"]["projected_cost_r"],
        "v3_gate": {
            "engine_hard_gate": bool(hard_ok),
            "risk_ok": bool(common["plan"]["risk_ok"]),
            "cost_ok": bool(common["plan"]["projected_cost_r"] <= V3_MAX_COST_R),
            "support_room_ok": bool(common["plan"]["support_room_r"] >= V3_MIN_SUPPORT_ROOM_R),
        },
        "entry": common["plan"]["entry"],
        "stop": common["plan"]["stop"],
        "stop_pct": common["plan"]["stop_pct"],
        "tp1": common["plan"]["tp1"],
        "tp2": common["plan"]["tp2"],
        "runner": common["plan"]["runner"],
        "support_room_r": common["plan"]["support_room_r"],
    }


def evaluate_v3_engines(result, one, four, fifteen, btc_one, eth_one):
    """Return research candidates from five independent V3 Short engines."""
    if fifteen is None or len(fifteen) < 40:
        return []

    s1 = structure_snapshot(one)
    s4 = structure_snapshot(four)
    current = float(one["close"].iloc[-1])
    a1 = float(atr(one).iloc[-1])
    if not math.isfinite(a1) or a1 <= 0:
        return []

    ret4 = return_pct(one["close"], 4)
    ret12 = return_pct(one["close"], 12)
    ret24 = return_pct(one["close"], 24)
    vol = volume_ratio(one)
    micro = _micro_trigger(fifteen)
    regime = market_router(btc_one, eth_one)
    plan = _execution_plan(result, fifteen)
    if plan is None:
        return []

    bb = _bollinger_state(one)
    vwap = _rolling_vwap(one, 24)
    ema20_now = float(ema(one["close"].astype(float), 20).iloc[-1])
    extension_atr = max(0.0, (current - ema20_now) / a1)
    vwap_extension_atr = max(0.0, (current - vwap) / a1)

    sweep = result.get("liquidity_sweep") or {}
    breakdown = result.get("breakdown_retest") or {}
    supply_distance = result.get("supply_distance_atr")
    rejection = bool(result.get("bearish_rejection"))

    market_r4 = float(regime.get("avg_r4") or 0.0)
    market_r24 = float(regime.get("avg_r24") or 0.0)
    relative_4h = ret4 - market_r4
    relative_24h = ret24 - market_r24

    last_range_atr = (
        float(one["high"].iloc[-1]) - float(one["low"].iloc[-1])
    ) / max(a1, 1e-12)
    manipulation_penalty = 8 if last_range_atr >= 4.0 and vol >= 3.0 else 0

    common = {
        "regime": regime,
        "micro": micro,
        "plan": plan,
        "relative_4h": relative_4h,
        "relative_24h": relative_24h,
    }

    candidates = []

    # A. Extreme pump -> buy-side sweep -> failed reclaim.
    pump_score = min(28.0, max(0.0, (ret24 - 8.0) * 1.8))
    extension_score = min(
        16.0,
        extension_atr * 4.0 + max(0.0, bb["z"] - 1.0) * 3.0 + vwap_extension_atr * 2.0,
    )
    sweep_score = 18.0 if sweep.get("detected") else 0.0
    micro_score = float(micro["score"])
    regime_score = 8.0 if regime["state"] in ("RISK_OFF", "NEUTRAL") else 0.0
    exhaustion_score = 8.0 if (rejection or bb["failed_upper"]) else 0.0
    a_score = pump_score + extension_score + sweep_score + micro_score + regime_score + exhaustion_score - manipulation_penalty
    a_hard = bool(
        ret24 >= 10.0
        and sweep.get("detected")
        and (extension_atr >= 1.5 or bb["z"] >= 1.5 or vwap_extension_atr >= 1.5)
        and micro["failed_reclaim"]
        and (micro["lower_high"] or micro["lower_low"] or micro["rejection"])
        and (
            regime["state"] != "RISK_ON"
            or (ret24 >= 15.0 and micro["score"] >= 12)
        )
    )
    candidates.append(_make_candidate(
        "EXTREME_PUMP_REVERSAL",
        a_score,
        a_hard,
        {
            "pump": round(pump_score, 2),
            "extension": round(extension_score, 2),
            "sweep": sweep_score,
            "micro": micro_score,
            "regime": regime_score,
            "exhaustion": exhaustion_score,
            "manipulation_penalty": -manipulation_penalty,
        },
        ["24h extreme pump", "buy-side liquidity sweep", "15m failed reclaim"],
        common,
    ))

    # B. Exhaustion without requiring an extreme pump.
    exhaustion_flags = [
        rejection,
        bool(bb["failed_upper"]),
        vol >= 1.4,
        vwap_extension_atr >= 1.2,
    ]
    exhaustion_count = sum(1 for x in exhaustion_flags if x)
    b_score = (
        min(18.0, max(0.0, ret24) * 1.5)
        + exhaustion_count * 10.0
        + float(micro["score"])
        + (10.0 if regime["state"] != "RISK_ON" else 0.0)
        + (8.0 if supply_distance is not None and float(supply_distance) <= 0.75 else 0.0)
        - manipulation_penalty
    )
    b_hard = bool(
        4.0 <= ret24 < 18.0
        and exhaustion_count >= 2
        and micro["failed_reclaim"]
        and (micro["lower_high"] or micro["rejection"])
        and regime["state"] != "RISK_ON"
    )
    candidates.append(_make_candidate(
        "EXHAUSTION_REVERSAL",
        b_score,
        b_hard,
        {
            "return_context": round(min(18.0, max(0.0, ret24) * 1.5), 2),
            "exhaustion": exhaustion_count * 10.0,
            "micro": float(micro["score"]),
            "regime": 10.0 if regime["state"] != "RISK_ON" else 0.0,
            "location": 8.0 if supply_distance is not None and float(supply_distance) <= 0.75 else 0.0,
            "manipulation_penalty": -manipulation_penalty,
        },
        ["multi-factor exhaustion", "15m failed reclaim"],
        common,
    ))

    # C. Bear-trend continuation via breakdown + retest.
    structure_score = 0.0
    structure_score += 12.0 if s4["ema_bear"] else 0.0
    structure_score += 8.0 if s4["lower_high"] else 0.0
    structure_score += 7.0 if s4["lower_low"] else 0.0
    structure_score += 10.0 if s1["ema_bear"] else 0.0
    structure_score += 6.0 if s1["lower_high"] else 0.0
    c_score = (
        structure_score
        + (24.0 if breakdown.get("retest") else (10.0 if breakdown.get("breakdown") else 0.0))
        + min(18.0, float(micro["score"]))
        + (12.0 if regime["state"] == "RISK_OFF" else 0.0)
        - (6.0 if ret12 < -18.0 else 0.0)
    )
    c_hard = bool(
        regime["state"] == "RISK_OFF"
        and breakdown.get("breakdown")
        and breakdown.get("retest")
        and (s4["ema_bear"] or (s4["lower_high"] and s4["lower_low"]))
        and (micro["failed_reclaim"] or micro["lower_high"])
        and ret12 > -22.0
    )
    candidates.append(_make_candidate(
        "BREAKDOWN_RETEST",
        c_score,
        c_hard,
        {
            "structure": structure_score,
            "breakdown_retest": 24.0 if breakdown.get("retest") else (10.0 if breakdown.get("breakdown") else 0.0),
            "micro": min(18.0, float(micro["score"])),
            "regime": 12.0 if regime["state"] == "RISK_OFF" else 0.0,
            "chase_penalty": -6.0 if ret12 < -18.0 else 0.0,
        },
        ["risk-off regime", "1H breakdown/retest", "15m bearish confirmation"],
        common,
    ))

    # D. Relative weakness vs BTC/ETH, avoiding already-collapsed coins.
    weakness_score = min(30.0, max(0.0, -relative_24h) * 3.0) + min(15.0, max(0.0, -relative_4h) * 4.0)
    d_structure = (
        (10.0 if s1["lower_high"] else 0.0)
        + (8.0 if s1["close"] < s1["ema20"] else 0.0)
        + (6.0 if s4["lower_high"] else 0.0)
    )
    d_score = (
        weakness_score
        + d_structure
        + min(18.0, float(micro["score"]))
        + (8.0 if regime["state"] != "RISK_ON" else 0.0)
        - (10.0 if ret24 <= -15.0 else 0.0)
    )
    d_hard = bool(
        relative_4h <= -1.0
        and relative_24h <= -3.0
        and ret24 > -15.0
        and (s1["lower_high"] or s1["close"] < s1["ema20"])
        and (micro["failed_reclaim"] or micro["lower_high"])
        and (regime["state"] != "RISK_ON" or relative_24h <= -7.0)
    )
    candidates.append(_make_candidate(
        "RELATIVE_WEAKNESS",
        d_score,
        d_hard,
        {
            "relative_weakness": round(weakness_score, 2),
            "structure": d_structure,
            "micro": min(18.0, float(micro["score"])),
            "regime": 8.0 if regime["state"] != "RISK_ON" else 0.0,
            "chase_penalty": -10.0 if ret24 <= -15.0 else 0.0,
        },
        ["underperforming BTC/ETH", "bearish local structure", "15m confirmation"],
        common,
    ))

    # E. Failed breakout / supply fade for moderate, non-extreme upside moves.
    fresh_sweep = bool(sweep.get("detected") and int(sweep.get("bars_ago") or 99) <= 2)
    location_ok = bool(
        (supply_distance is not None and float(supply_distance) <= 0.75)
        or bb["failed_upper"]
    )
    f_score = (
        (22.0 if fresh_sweep else 0.0)
        + (18.0 if location_ok else 0.0)
        + min(20.0, float(micro["score"]))
        + (12.0 if rejection or bb["failed_upper"] else 0.0)
        + (10.0 if regime["state"] != "RISK_ON" else 0.0)
        + min(10.0, max(0.0, ret24))
        - manipulation_penalty
    )
    f_hard = bool(
        -2.0 <= ret24 < 10.0
        and fresh_sweep
        and location_ok
        and micro["failed_reclaim"]
        and regime["state"] != "RISK_ON"
    )
    candidates.append(_make_candidate(
        "FAILED_BREAKOUT_SUPPLY_FADE",
        f_score,
        f_hard,
        {
            "fresh_sweep": 22.0 if fresh_sweep else 0.0,
            "location": 18.0 if location_ok else 0.0,
            "micro": min(20.0, float(micro["score"])),
            "failure": 12.0 if rejection or bb["failed_upper"] else 0.0,
            "regime": 10.0 if regime["state"] != "RISK_ON" else 0.0,
            "return_context": min(10.0, max(0.0, ret24)),
            "manipulation_penalty": -manipulation_penalty,
        },
        ["fresh failed breakout", "supply/Bollinger location", "15m failed reclaim"],
        common,
    ))

    candidates = [c for c in candidates if c["v3_status"] != "IGNORE"]
    candidates.sort(
        key=lambda x: (
            0 if x["v3_status"] == "ENTRY_READY" else 1,
            -float(x["v3_score"]),
            x["v3_engine"],
        )
    )
    if candidates:
        candidates[0]["v3_primary"] = True

    for candidate in candidates:
        candidate["v3_features"] = {
            "return_4h_pct": round(ret4, 3),
            "return_12h_pct": round(ret12, 3),
            "return_24h_pct": round(ret24, 3),
            "extension_atr": round(extension_atr, 3),
            "vwap_extension_atr": round(vwap_extension_atr, 3),
            "bollinger_z": round(float(bb["z"]), 3),
            "bollinger_failed_upper": bool(bb["failed_upper"]),
            "volume_ratio_1h": round(float(vol), 3),
            "supply_distance_atr": supply_distance,
            "liquidity_sweep": sweep,
            "breakdown_retest": breakdown,
            "bearish_rejection": rejection,
            "last_range_atr": round(last_range_atr, 3),
        }
    return candidates
