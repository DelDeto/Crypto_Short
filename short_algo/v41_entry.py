"""V4.1 location-first Short entry engine.

Rule engines identify *what* may be shortable. This module decides *where*
and *when* to enter. Zones are built only from information available at the
signal timestamp. Future 15m candles are used solely to simulate subsequent
retest, structure shift, confirmation, and execution.
"""

import math

import pandas as pd

from .config import (
    BACKTEST_FEE_BPS_ROUND_TRIP,
    BACKTEST_SLIPPAGE_BPS_ROUND_TRIP,
    V3_MAX_COST_R,
)
from .indicators import atr, ema
from .v41_config import (
    V41_BOS_BUFFER_ATR1H,
    V41_BOS_LOOKBACK_BARS,
    V41_BOS_WINDOW_BARS,
    V41_CONFIRM_MIN_SCORE,
    V41_ENTRY_WAIT_HOURS,
    V41_MAX_BREAKDOWN_AGE_1H_BARS,
    V41_MAX_CHASE_ATR,
    V41_MAX_STOP_PCT,
    V41_MAX_SUPPLY_PRIOR_TOUCHES,
    V41_MAX_SWEEP_AGE_1H_BARS,
    V41_MIN_SUPPORT_ROOM_R,
    V41_RECLAIM_INVALIDATION_ATR1H,
    V41_RETEST_TOLERANCE_ATR1H,
    V41_RETEST_WINDOW_BARS,
    V41_STOP_BUFFER_ATR,
    V41_UNKNOWN_SUPPORT_POLICY,
    V41_ZONE_BUFFER_ATR,
    V41_ZONE_INVALIDATION_ATR,
)


def _zone(lower, upper, source, priority, **extra):
    lower, upper = sorted((float(lower), float(upper)))
    return {
        "valid": True,
        "lower": lower,
        "upper": upper,
        "mid": (lower + upper) / 2.0,
        "source": source,
        "priority": int(priority),
        **extra,
    }


def _touch_episodes(frame, lower, upper):
    if frame is None or frame.empty:
        return 0
    touched = (
        (frame["high"].astype(float) >= float(lower))
        & (frame["low"].astype(float) <= float(upper))
    )
    episodes = 0
    active = False
    for value in touched.tolist():
        if value and not active:
            episodes += 1
        active = bool(value)
    return episodes


def _slice_after_time(frame, time_value):
    if frame is None or frame.empty or not time_value:
        return frame.iloc[0:0] if frame is not None else None
    try:
        ts = pd.Timestamp(time_value)
        index = frame.index
        if getattr(index, "tz", None) is not None and ts.tzinfo is None:
            ts = ts.tz_localize(index.tz)
        elif getattr(index, "tz", None) is None and ts.tzinfo is not None:
            ts = ts.tz_convert(None)
        return frame.loc[frame.index > ts]
    except Exception:
        return frame.iloc[0:0]


def _assess_supply(raw_zone, one, a1):
    lower = float(raw_zone["lower"])
    upper = float(raw_zone["upper"])
    after = _slice_after_time(one, raw_zone.get("time"))
    invalidated = bool(
        not after.empty
        and (
            after["close"].astype(float)
            > upper + V41_ZONE_INVALIDATION_ATR * a1
        ).any()
    )

    # The current signal bar may itself be the first retest, so only completed
    # prior bars count against freshness.
    prior = after.iloc[:-1] if len(after) > 1 else after.iloc[0:0]
    prior_touches = _touch_episodes(prior, lower, upper)
    fresh = (
        not invalidated
        and prior_touches <= V41_MAX_SUPPLY_PRIOR_TOUCHES
    )
    return {
        "fresh": fresh,
        "invalidated": invalidated,
        "prior_touch_count": int(prior_touches),
        "age_1h_bars": int(len(after)),
        "freshness_reason": (
            "INVALIDATED_CLOSE_ABOVE"
            if invalidated
            else (
                "TOO_MANY_PRIOR_TOUCHES"
                if prior_touches > V41_MAX_SUPPLY_PRIOR_TOUCHES
                else "FRESH"
            )
        ),
    }


def _assess_breakdown(level, breakdown, one, a1):
    bars_ago = int(breakdown.get("bars_ago") or 999)
    pos = max(0, len(one) - 1 - bars_ago)
    after = one.iloc[pos + 1:]
    invalidated = bool(
        not after.empty
        and (
            after["close"].astype(float)
            > float(level) + V41_RECLAIM_INVALIDATION_ATR1H * a1
        ).any()
    )
    prior = after.iloc[:-1] if len(after) > 1 else after.iloc[0:0]
    prior_touches = _touch_episodes(
        prior,
        float(level) - 0.10 * a1,
        float(level) + V41_ZONE_BUFFER_ATR * a1,
    )
    fresh = (
        bars_ago <= V41_MAX_BREAKDOWN_AGE_1H_BARS
        and not invalidated
    )
    return {
        "fresh": fresh,
        "invalidated": invalidated,
        "prior_touch_count": int(prior_touches),
        "age_1h_bars": bars_ago,
        "freshness_reason": (
            "BREAKDOWN_RECLAIMED"
            if invalidated
            else (
                "BREAKDOWN_TOO_OLD"
                if bars_ago > V41_MAX_BREAKDOWN_AGE_1H_BARS
                else "FRESH"
            )
        ),
    }


def _assess_sweep(level, sweep, one, a1):
    bars_ago = int(sweep.get("bars_ago") or 999)
    pos = max(0, len(one) - 1 - bars_ago)
    after = one.iloc[pos + 1:]
    invalidated = bool(
        not after.empty
        and (
            after["close"].astype(float)
            > float(level) + V41_ZONE_INVALIDATION_ATR * a1
        ).any()
    )
    fresh = (
        bars_ago <= V41_MAX_SWEEP_AGE_1H_BARS
        and not invalidated
    )
    return {
        "fresh": fresh,
        "invalidated": invalidated,
        "prior_touch_count": 0,
        "age_1h_bars": bars_ago,
        "freshness_reason": (
            "SWEEP_INVALIDATED"
            if invalidated
            else (
                "SWEEP_TOO_OLD"
                if bars_ago > V41_MAX_SWEEP_AGE_1H_BARS
                else "FRESH"
            )
        ),
    }


def build_short_entry_zone(candidate, base, one):
    """Build and validate an engine-aware Short location at signal time."""
    if one is None or len(one) < 30:
        return None

    current = float(one["close"].iloc[-1])
    a1 = float(atr(one).iloc[-1])
    if not math.isfinite(a1) or a1 <= 0:
        return None

    engine = str(candidate.get("v3_engine") or "")
    zones = []

    supply1 = base.get("supply_1h") or {}
    supply4 = base.get("supply_4h") or {}
    breakdown = base.get("breakdown_retest") or {}
    sweep = base.get("liquidity_sweep") or {}

    if supply1.get("lower") is not None and supply1.get("upper") is not None:
        quality = _assess_supply(supply1, one, a1)
        if quality["fresh"]:
            zones.append(_zone(
                supply1["lower"],
                supply1["upper"],
                "SUPPLY_1H",
                1 if engine in (
                    "FAILED_BREAKOUT_SUPPLY_FADE",
                    "EXHAUSTION_REVERSAL",
                ) else 3,
                **quality,
            ))

    if supply4.get("lower") is not None and supply4.get("upper") is not None:
        quality = _assess_supply(supply4, one, a1)
        if quality["fresh"]:
            zones.append(_zone(
                supply4["lower"],
                supply4["upper"],
                "SUPPLY_4H",
                2,
                **quality,
            ))

    level = breakdown.get("level")
    if level is not None:
        quality = _assess_breakdown(level, breakdown, one, a1)
        if quality["fresh"]:
            zones.append(_zone(
                float(level) - 0.10 * a1,
                float(level) + V41_ZONE_BUFFER_ATR * a1,
                "BREAKDOWN_RETEST",
                1 if engine == "BREAKDOWN_RETEST" else 4,
                **quality,
            ))

    sweep_level = sweep.get("level")
    if sweep_level is not None:
        quality = _assess_sweep(sweep_level, sweep, one, a1)
        if quality["fresh"]:
            zones.append(_zone(
                float(sweep_level) - 0.08 * a1,
                float(sweep_level) + 0.30 * a1,
                "SWEEP_RETEST",
                1 if engine in (
                    "EXTREME_PUMP_REVERSAL",
                    "FAILED_BREAKOUT_SUPPLY_FADE",
                ) else 4,
                **quality,
            ))

    # EMA is a pullback location, not a reversal zone. Keep it only for
    # continuation / relative-weakness contexts.
    if engine in ("BREAKDOWN_RETEST", "RELATIVE_WEAKNESS"):
        e20 = float(ema(one["close"].astype(float), 20).iloc[-1])
        zones.append(_zone(
            e20 - 0.08 * a1,
            e20 + 0.18 * a1,
            "EMA20_PULLBACK",
            2 if engine == "BREAKDOWN_RETEST" else 3,
            fresh=True,
            invalidated=False,
            prior_touch_count=0,
            age_1h_bars=0,
            freshness_reason="DYNAMIC_LEVEL",
        ))

    # Do not chase a zone already materially below the signal price.
    usable = [
        z for z in zones
        if z["upper"] >= current - V41_MAX_CHASE_ATR * a1
    ]
    if not usable:
        return None

    for z in usable:
        if z["lower"] <= current <= z["upper"]:
            distance = 0.0
        elif current < z["lower"]:
            distance = (z["lower"] - current) / a1
        else:
            distance = (current - z["upper"]) / a1
        z["distance_atr"] = float(distance)

        freshness_bonus = max(
            0.0,
            2.0 - float(z.get("prior_touch_count") or 0.0),
        )
        z["location_quality"] = round(
            10.0
            - 2.0 * float(z["priority"])
            - min(4.0, float(distance))
            + freshness_bonus,
            3,
        )

    usable.sort(key=lambda z: (
        z["priority"],
        -float(z.get("location_quality") or 0.0),
        z["distance_atr"],
    ))
    chosen = dict(usable[0])
    chosen["signal_price"] = current
    chosen["atr_1h"] = a1
    chosen["ideal_entry"] = (
        chosen["lower"] * 0.35 + chosen["upper"] * 0.65
    )
    return chosen


def _confirmation_score(row, prev, zone):
    o = float(row["open"])
    h = float(row["high"])
    l = float(row["low"])
    c = float(row["close"])
    candle_range = max(h - l, 1e-12)
    upper_wick = h - max(o, c)

    score = 0
    if c < o:
        score += 1
    if c < zone["mid"]:
        score += 1
    if upper_wick / candle_range >= 0.35:
        score += 1
    if prev is not None and c < float(prev["close"]):
        score += 1
    return score


def _rejection(reason, zone=None, **extra):
    return {
        "filled": False,
        "reject_reason": reason,
        "zone_source": None if zone is None else zone.get("source"),
        **extra,
    }


def simulate_confirmed_retest(
    zone,
    fifteen_future,
    nearest_support=None,
    fifteen_history=None,
):
    """State machine: zone touch -> bearish BOS -> failed retest -> Short."""
    if zone is None:
        return _rejection("NO_VALID_FRESH_ZONE")
    if fifteen_future is None or fifteen_future.empty:
        return _rejection("NO_FUTURE_DATA", zone)

    if nearest_support is None and V41_UNKNOWN_SUPPORT_POLICY == "REJECT":
        return _rejection("UNKNOWN_SUPPORT", zone)

    a1 = float(zone["atr_1h"])
    signal_price = float(zone["signal_price"])
    max_bars = max(1, int(V41_ENTRY_WAIT_HOURS) * 4)
    view = fifteen_future.head(max_bars)

    history = []
    if fifteen_history is not None and not fifteen_history.empty:
        history = [
            row for _, row in fifteen_history.tail(
                max(20, V41_BOS_LOOKBACK_BARS + 4)
            ).iterrows()
        ]

    state = "WAIT_TOUCH"
    touch_bar = None
    bos_bar = None
    bos_level = None
    attempt_high = None
    last_reason = "NO_ZONE_TOUCH"

    for bars, (ts, row) in enumerate(view.iterrows(), start=1):
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        prev = history[-1] if history else None

        # A close materially above supply/resistance invalidates the location.
        if close > float(zone["upper"]) + V41_ZONE_INVALIDATION_ATR * a1:
            return _rejection(
                "ZONE_INVALIDATED_AFTER_SIGNAL",
                zone,
                state=state,
                bars_waited=bars,
            )

        touched = (
            high >= float(zone["lower"])
            and low <= float(zone["upper"])
        )

        if state == "WAIT_TOUCH":
            if touched:
                state = "WAIT_BOS"
                touch_bar = bars
                attempt_high = high
                last_reason = "NO_BEARISH_BOS"
            history.append(row)
            continue

        if state == "WAIT_BOS":
            attempt_high = max(float(attempt_high or high), high)

            # If price leaves the location downward without structure shift,
            # reset the attempt. A later retouch must start a new sequence.
            if (
                close < float(zone["lower"]) - V41_MAX_CHASE_ATR * a1
                and not touched
            ):
                state = "WAIT_TOUCH"
                touch_bar = None
                attempt_high = None
                last_reason = "LEFT_ZONE_BEFORE_BOS"
                history.append(row)
                continue

            if touch_bar is not None and bars - touch_bar > V41_BOS_WINDOW_BARS:
                state = "WAIT_TOUCH"
                touch_bar = None
                attempt_high = None
                last_reason = "BOS_WINDOW_EXPIRED"
                history.append(row)
                continue

            prior = history[-V41_BOS_LOOKBACK_BARS:]
            if len(prior) >= V41_BOS_LOOKBACK_BARS:
                prior_low = min(float(x["low"]) for x in prior)
                broke = (
                    close
                    < prior_low - V41_BOS_BUFFER_ATR1H * a1
                )
                if broke:
                    state = "WAIT_RETEST"
                    bos_bar = bars
                    bos_level = prior_low
                    last_reason = "NO_FAILED_RETEST"

            history.append(row)
            continue

        if state == "WAIT_RETEST":
            attempt_high = max(float(attempt_high or high), high)

            if bos_bar is not None and bars - bos_bar > V41_RETEST_WINDOW_BARS:
                state = "WAIT_TOUCH"
                touch_bar = None
                bos_bar = None
                bos_level = None
                attempt_high = None
                last_reason = "RETEST_WINDOW_EXPIRED"
                history.append(row)
                continue

            # A decisive reclaim above the broken micro support cancels this BOS.
            if (
                bos_level is not None
                and close
                > float(bos_level)
                + V41_RECLAIM_INVALIDATION_ATR1H * a1
            ):
                state = "WAIT_BOS" if touched else "WAIT_TOUCH"
                touch_bar = bars if touched else None
                bos_bar = None
                bos_level = None
                attempt_high = high if touched else None
                last_reason = "MICRO_BOS_RECLAIMED"
                history.append(row)
                continue

            retested = bool(
                bos_level is not None
                and high
                >= float(bos_level) - V41_RETEST_TOLERANCE_ATR1H * a1
                and low
                <= float(bos_level) + V41_RETEST_TOLERANCE_ATR1H * a1
            )

            if retested:
                score = _confirmation_score(row, prev, zone)
                no_chase = (
                    close
                    >= signal_price - V41_MAX_CHASE_ATR * a1
                )
                closes_below_break = (
                    close
                    <= float(bos_level)
                    + V41_RETEST_TOLERANCE_ATR1H * a1
                )

                if (
                    score >= V41_CONFIRM_MIN_SCORE
                    and no_chase
                    and closes_below_break
                ):
                    entry = close
                    stop_anchor = max(
                        float(zone["upper"]),
                        float(attempt_high or high),
                    )
                    risk = (
                        stop_anchor
                        + V41_STOP_BUFFER_ATR * a1
                        - entry
                    )
                    if risk <= 0:
                        history.append(row)
                        continue

                    stop = entry + risk
                    stop_pct = (
                        risk / max(entry, 1e-12) * 100.0
                    )
                    total_cost_bps = (
                        float(BACKTEST_FEE_BPS_ROUND_TRIP)
                        + float(BACKTEST_SLIPPAGE_BPS_ROUND_TRIP)
                    )
                    projected_cost_r = (
                        entry * total_cost_bps / 10000.0
                    ) / risk

                    support_room_r = None
                    if (
                        nearest_support is not None
                        and float(nearest_support) < entry
                    ):
                        support_room_r = (
                            entry - float(nearest_support)
                        ) / risk

                    if support_room_r is None:
                        return _rejection(
                            "UNKNOWN_SUPPORT",
                            zone,
                            state=state,
                        )
                    if projected_cost_r > V3_MAX_COST_R:
                        return _rejection(
                            "COST_TOO_HIGH",
                            zone,
                            state=state,
                            projected_cost_r=round(projected_cost_r, 4),
                        )
                    if stop_pct > V41_MAX_STOP_PCT:
                        return _rejection(
                            "STOP_TOO_WIDE",
                            zone,
                            state=state,
                            stop_pct=round(stop_pct, 4),
                        )
                    if support_room_r < V41_MIN_SUPPORT_ROOM_R:
                        return _rejection(
                            "SUPPORT_TOO_CLOSE",
                            zone,
                            state=state,
                            support_room_r=round(support_room_r, 4),
                        )

                    return {
                        "filled": True,
                        "reject_reason": None,
                        "entry_time": (
                            pd.Timestamp(ts) + pd.Timedelta(minutes=15)
                        ).isoformat(),
                        "entry_bar": bars,
                        "entry": entry,
                        "stop": stop,
                        "risk": risk,
                        "stop_pct": round(stop_pct, 4),
                        "projected_cost_r": round(projected_cost_r, 4),
                        "tp1": entry - 2.0 * risk,
                        "tp2": entry - 3.0 * risk,
                        "runner": entry - 5.0 * risk,
                        "support_room_r": round(support_room_r, 4),
                        "zone_source": zone["source"],
                        "zone_lower": zone["lower"],
                        "zone_upper": zone["upper"],
                        "zone_mid": zone["mid"],
                        "zone_prior_touch_count": zone.get("prior_touch_count"),
                        "zone_age_1h_bars": zone.get("age_1h_bars"),
                        "zone_location_quality": zone.get("location_quality"),
                        "zone_freshness_reason": zone.get("freshness_reason"),
                        "ideal_entry": zone["ideal_entry"],
                        "signal_price": signal_price,
                        "entry_improvement_atr": round(
                            (entry - signal_price) / max(a1, 1e-12),
                            4,
                        ),
                        "confirmation_score": score,
                        "wait_bars_15m": bars,
                        "bos_level": round(float(bos_level), 12),
                        "bos_bar": int(bos_bar or bars),
                        "touch_bar": int(touch_bar or bars),
                        "structure_sequence": "ZONE_TOUCH>BOS>RETEST>CONFIRM",
                    }

            history.append(row)
            continue

    return _rejection(
        last_reason,
        zone,
        state=state,
        bars_waited=len(view),
        bos_level=bos_level,
    )
