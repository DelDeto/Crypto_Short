"""V4.2 structural execution engine.

Sequence:
HTF location -> touch -> meaningful bearish displacement/BOS ->
failed retest of broken swing -> Short.

A BOS reference is frozen before the touch. A moving micro-low cannot become
the reference after price has already started falling.
"""

import math

import pandas as pd

from .config import (
    BACKTEST_FEE_BPS_ROUND_TRIP,
    BACKTEST_SLIPPAGE_BPS_ROUND_TRIP,
)
from .indicators import atr
from .v42_config import (
    V42_BOS_BUFFER_ATR15,
    V42_ENTRY_WAIT_HOURS,
    V42_MAX_BREAKDOWN_AGE_1H,
    V42_MAX_CHASE_ATR1H,
    V42_MAX_COST_R,
    V42_MAX_PIVOT_AGE_15M,
    V42_MAX_STOP_PCT,
    V42_MAX_SUPPLY_PRIOR_TOUCHES,
    V42_MAX_SWEEP_AGE_1H,
    V42_MIN_DISPLACEMENT_BODY_ATR15,
    V42_MIN_DISPLACEMENT_RANGE_ATR15,
    V42_MIN_DISPLACEMENT_VOL_RATIO,
    V42_MIN_SUPPORT_ROOM_R,
    V42_PIVOT_LEFT,
    V42_PIVOT_RIGHT,
    V42_RECLAIM_INVALIDATION_ATR15,
    V42_RETEST_TOLERANCE_ATR15,
    V42_RETEST_WINDOW_BARS,
    V42_STOP_BUFFER_ATR15,
    V42_ZONE_INVALIDATION_ATR1H,
)


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
        if getattr(frame.index, "tz", None) is not None and ts.tzinfo is None:
            ts = ts.tz_localize(frame.index.tz)
        elif getattr(frame.index, "tz", None) is None and ts.tzinfo is not None:
            ts = ts.tz_convert(None)
        return frame.loc[frame.index > ts]
    except Exception:
        return frame.iloc[0:0]


def _supply_quality(raw_zone, one, a1):
    lower = float(raw_zone["lower"])
    upper = float(raw_zone["upper"])
    after = _slice_after_time(one, raw_zone.get("time"))
    invalidated = bool(
        not after.empty
        and (
            after["close"].astype(float)
            > upper + V42_ZONE_INVALIDATION_ATR1H * a1
        ).any()
    )
    prior = after.iloc[:-1] if len(after) > 1 else after.iloc[0:0]
    touches = _touch_episodes(prior, lower, upper)
    return {
        "fresh": (
            not invalidated
            and touches <= V42_MAX_SUPPLY_PRIOR_TOUCHES
        ),
        "invalidated": invalidated,
        "prior_touch_count": int(touches),
        "age_1h_bars": int(len(after)),
    }


def _zone(lower, upper, source, priority, **extra):
    lower, upper = sorted((float(lower), float(upper)))
    return {
        "lower": lower,
        "upper": upper,
        "mid": (lower + upper) / 2.0,
        "source": source,
        "priority": int(priority),
        **extra,
    }


def build_v42_zone(setup, base, one):
    if setup is None or one is None or len(one) < 30:
        return None

    current = float(one["close"].iloc[-1])
    a1 = float(atr(one).iloc[-1])
    if not math.isfinite(a1) or a1 <= 0:
        return None

    zones = []
    setup_type = str(setup.get("v42_setup") or "")

    if setup_type == "REVERSAL_AT_LOCATION":
        for source, raw, priority in (
            ("SUPPLY_1H", base.get("supply_1h") or {}, 1),
            ("SUPPLY_4H", base.get("supply_4h") or {}, 2),
        ):
            if raw.get("lower") is None or raw.get("upper") is None:
                continue
            quality = _supply_quality(raw, one, a1)
            if not quality["fresh"]:
                continue
            zones.append(_zone(
                raw["lower"],
                raw["upper"],
                source,
                priority,
                **quality,
            ))

        sweep = base.get("liquidity_sweep") or {}
        if (
            sweep.get("detected")
            and sweep.get("level") is not None
            and int(sweep.get("bars_ago") or 999) <= V42_MAX_SWEEP_AGE_1H
        ):
            level = float(sweep["level"])
            after_bars = int(sweep.get("bars_ago") or 0)
            pos = max(0, len(one) - 1 - after_bars)
            after = one.iloc[pos + 1:]
            invalidated = bool(
                not after.empty
                and (
                    after["close"].astype(float)
                    > level + V42_ZONE_INVALIDATION_ATR1H * a1
                ).any()
            )
            if not invalidated:
                zones.append(_zone(
                    level - 0.08 * a1,
                    level + 0.25 * a1,
                    "SWEEP_RETEST",
                    1,
                    fresh=True,
                    invalidated=False,
                    prior_touch_count=0,
                    age_1h_bars=after_bars,
                ))

    elif setup_type == "BEAR_CONTINUATION_RETEST":
        breakdown = base.get("breakdown_retest") or {}
        if (
            breakdown.get("level") is not None
            and int(breakdown.get("bars_ago") or 999) <= V42_MAX_BREAKDOWN_AGE_1H
        ):
            level = float(breakdown["level"])
            bars_ago = int(breakdown.get("bars_ago") or 0)
            pos = max(0, len(one) - 1 - bars_ago)
            after = one.iloc[pos + 1:]
            reclaimed = bool(
                not after.empty
                and (
                    after["close"].astype(float)
                    > level + V42_ZONE_INVALIDATION_ATR1H * a1
                ).any()
            )
            if not reclaimed:
                zones.append(_zone(
                    level - 0.12 * a1,
                    level + 0.18 * a1,
                    "BROKEN_SUPPORT_RETEST",
                    1,
                    fresh=True,
                    invalidated=False,
                    prior_touch_count=_touch_episodes(
                        after.iloc[:-1] if len(after) > 1 else after.iloc[0:0],
                        level - 0.12 * a1,
                        level + 0.18 * a1,
                    ),
                    age_1h_bars=bars_ago,
                ))

    usable = [
        z for z in zones
        if z["upper"] >= current - V42_MAX_CHASE_ATR1H * a1
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
        z["distance_atr1h"] = round(float(distance), 4)
        z["atr_1h"] = a1
        z["signal_price"] = current
        z["location_quality"] = round(
            100.0
            - 12.0 * float(z["priority"] - 1)
            - 15.0 * min(2.0, float(distance))
            - 12.0 * float(z.get("prior_touch_count") or 0),
            3,
        )

    usable.sort(key=lambda z: (
        z["priority"],
        -float(z["location_quality"]),
        float(z["distance_atr1h"]),
    ))
    return usable[0]


def _confirmed_pivots(history):
    if history is None or len(history) < V42_PIVOT_LEFT + V42_PIVOT_RIGHT + 5:
        return []
    low = history["low"].astype(float).tolist()
    high = history["high"].astype(float).tolist()
    pivots = []
    n = len(history)

    for i in range(V42_PIVOT_LEFT, n - V42_PIVOT_RIGHT):
        value = low[i]
        left = low[i - V42_PIVOT_LEFT:i]
        right = low[i + 1:i + 1 + V42_PIVOT_RIGHT]
        if not left or not right:
            continue
        if value > min(left) or value > min(right):
            continue

        local_start = max(0, i - V42_PIVOT_LEFT)
        local_end = min(n, i + V42_PIVOT_RIGHT + 1)
        surrounding_high = max(high[local_start:local_end])
        pivots.append({
            "pos": i,
            "price": value,
            "prominence": max(0.0, surrounding_high - value),
            "age_bars": n - 1 - i,
            "time": history.index[i],
        })
    return pivots


def _meaningful_pivot_low(history, a15):
    pivots = _confirmed_pivots(history)
    eligible = [
        p for p in pivots
        if int(p["age_bars"]) <= V42_MAX_PIVOT_AGE_15M
        and float(p["prominence"]) >= 0.35 * a15
    ]
    if not eligible:
        return None
    # Prefer the most recent proven swing; prominence breaks ties.
    eligible.sort(key=lambda p: (
        int(p["age_bars"]),
        -float(p["prominence"]),
    ))
    return eligible[0]


def _volume_ratio(history, row, lookback=20):
    if history is None or history.empty or "volume" not in history.columns:
        return 1.0
    prior = history["volume"].astype(float).tail(lookback)
    mean = float(prior.mean()) if len(prior) else 0.0
    current = float(row.get("volume", 0.0) or 0.0)
    if mean <= 0:
        return 1.0
    return current / mean


def _displacement_metrics(row, history, a15):
    o = float(row["open"])
    h = float(row["high"])
    l = float(row["low"])
    c = float(row["close"])
    body = abs(c - o)
    rng = max(h - l, 1e-12)
    close_pos = (c - l) / rng
    vol_ratio = _volume_ratio(history, row)
    bearish = c < o

    body_atr = body / max(a15, 1e-12)
    range_atr = rng / max(a15, 1e-12)
    quality = bool(
        bearish
        and body_atr >= V42_MIN_DISPLACEMENT_BODY_ATR15
        and range_atr >= V42_MIN_DISPLACEMENT_RANGE_ATR15
        and close_pos <= 0.35
        and vol_ratio >= V42_MIN_DISPLACEMENT_VOL_RATIO
    )
    return {
        "quality": quality,
        "body_atr15": round(body_atr, 4),
        "range_atr15": round(range_atr, 4),
        "close_position": round(close_pos, 4),
        "volume_ratio": round(vol_ratio, 4),
    }


def _retest_rejection(row, prev, level, a15):
    o = float(row["open"])
    h = float(row["high"])
    l = float(row["low"])
    c = float(row["close"])
    rng = max(h - l, 1e-12)
    upper_wick = h - max(o, c)

    touched = bool(
        h >= float(level) - V42_RETEST_TOLERANCE_ATR15 * a15
        and l <= float(level) + V42_RETEST_TOLERANCE_ATR15 * a15
    )
    closes_below = c <= float(level) + 0.05 * a15
    rejection = bool(
        c < o
        or upper_wick / rng >= 0.35
        or (prev is not None and c < float(prev["close"]))
    )
    return touched, closes_below, rejection


def _execution_plan(zone, entry, stop_anchor, a15, nearest_support):
    risk = float(stop_anchor) + V42_STOP_BUFFER_ATR15 * a15 - float(entry)
    if risk <= 0:
        return None

    stop = float(entry) + risk
    stop_pct = risk / max(float(entry), 1e-12) * 100.0

    support_room_r = None
    if nearest_support is not None and float(nearest_support) < float(entry):
        support_room_r = (
            float(entry) - float(nearest_support)
        ) / risk

    total_cost_bps = (
        float(BACKTEST_FEE_BPS_ROUND_TRIP)
        + float(BACKTEST_SLIPPAGE_BPS_ROUND_TRIP)
    )
    projected_cost_r = (
        float(entry) * total_cost_bps / 10000.0
    ) / risk

    reasons = []
    if support_room_r is None:
        reasons.append("UNKNOWN_SUPPORT")
    elif support_room_r < V42_MIN_SUPPORT_ROOM_R:
        reasons.append("SUPPORT_TOO_CLOSE")
    if stop_pct > V42_MAX_STOP_PCT:
        reasons.append("STOP_TOO_WIDE")
    if projected_cost_r > V42_MAX_COST_R:
        reasons.append("COST_TOO_HIGH")

    return {
        "entry": float(entry),
        "stop": stop,
        "risk": risk,
        "stop_pct": round(stop_pct, 4),
        "support_room_r": (
            None if support_room_r is None
            else round(support_room_r, 4)
        ),
        "projected_cost_r": round(projected_cost_r, 4),
        "tp1": float(entry) - 2.0 * risk,
        "tp2": float(entry) - 3.0 * risk,
        "runner": float(entry) - 5.0 * risk,
        "execution_ok": not reasons,
        "execution_reject_reason": ",".join(reasons) if reasons else None,
    }


def simulate_v42_entry(
    setup,
    zone,
    future15,
    history15,
    nearest_support=None,
):
    audit = {
        "zone_touched": False,
        "meaningful_pivot_found": False,
        "displacement_bos": False,
        "retest_seen": False,
        "failed_retest_confirmed": False,
    }
    if setup is None:
        return {"filled": False, "reject_reason": "NO_SETUP", **audit}
    if zone is None:
        return {"filled": False, "reject_reason": "NO_VALID_HTF_ZONE", **audit}
    if future15 is None or future15.empty:
        return {"filled": False, "reject_reason": "NO_FUTURE_DATA", **audit}

    history = (
        history15.copy()
        if history15 is not None
        else pd.DataFrame()
    )
    a15_series = atr(history) if history is not None and len(history) >= 20 else None
    a15 = (
        float(a15_series.iloc[-1])
        if a15_series is not None and math.isfinite(float(a15_series.iloc[-1]))
        else None
    )
    if a15 is None or a15 <= 0:
        return {"filled": False, "reject_reason": "NO_ATR15", **audit}

    max_bars = max(1, V42_ENTRY_WAIT_HOURS * 4)
    view = future15.head(max_bars)

    state = "WAIT_TOUCH"
    pivot = None
    touch_bar = None
    bos_bar = None
    bos_level = None
    stop_anchor = None
    displacement = None
    last_reason = "NO_ZONE_TOUCH"

    for bars, (ts, row) in enumerate(view.iterrows(), start=1):
        h = float(row["high"])
        l = float(row["low"])
        c = float(row["close"])
        prev = history.iloc[-1] if len(history) else None

        # HTF location has failed; do not keep waiting for a later short.
        if c > float(zone["upper"]) + V42_ZONE_INVALIDATION_ATR1H * float(zone["atr_1h"]):
            return {
                "filled": False,
                "reject_reason": "HTF_ZONE_INVALIDATED",
                "state": state,
                **audit,
            }

        touched = bool(
            h >= float(zone["lower"])
            and l <= float(zone["upper"])
        )

        if state == "WAIT_TOUCH":
            if touched:
                audit["zone_touched"] = True
                pivot = _meaningful_pivot_low(history, a15)
                audit["meaningful_pivot_found"] = pivot is not None
                if pivot is None:
                    last_reason = "NO_MEANINGFUL_SWING_LOW"
                else:
                    state = "WAIT_DISPLACEMENT_BOS"
                    touch_bar = bars
                    stop_anchor = h
                    last_reason = "NO_QUALITY_DISPLACEMENT_BOS"
            history = pd.concat([history, row.to_frame().T])
            continue

        if state == "WAIT_DISPLACEMENT_BOS":
            stop_anchor = max(float(stop_anchor or h), h)
            dm = _displacement_metrics(row, history, a15)
            broke = bool(
                pivot is not None
                and c
                < float(pivot["price"]) - V42_BOS_BUFFER_ATR15 * a15
            )
            if broke and dm["quality"]:
                audit["displacement_bos"] = True
                state = "WAIT_FAILED_RETEST"
                bos_bar = bars
                bos_level = float(pivot["price"])
                displacement = dm
                last_reason = "NO_FAILED_RETEST"
            elif (
                c < float(zone["lower"])
                - V42_MAX_CHASE_ATR1H * float(zone["atr_1h"])
            ):
                # Price left without proving seller control. Do not chase.
                return {
                    "filled": False,
                    "reject_reason": "LEFT_LOCATION_WITHOUT_QUALITY_BOS",
                    "state": state,
                    "pivot_price": None if pivot is None else pivot["price"],
                    **audit,
                }
            history = pd.concat([history, row.to_frame().T])
            continue

        if state == "WAIT_FAILED_RETEST":
            stop_anchor = max(float(stop_anchor or h), h)

            if bos_bar is not None and bars - bos_bar > V42_RETEST_WINDOW_BARS:
                return {
                    "filled": False,
                    "reject_reason": "RETEST_WINDOW_EXPIRED",
                    "state": state,
                    "bos_level": bos_level,
                    **audit,
                }

            if c > float(bos_level) + V42_RECLAIM_INVALIDATION_ATR15 * a15:
                return {
                    "filled": False,
                    "reject_reason": "BOS_RECLAIMED",
                    "state": state,
                    "bos_level": bos_level,
                    **audit,
                }

            retested, closes_below, rejection = _retest_rejection(
                row, prev, bos_level, a15
            )
            if retested:
                audit["retest_seen"] = True
            if retested and closes_below and rejection:
                audit["failed_retest_confirmed"] = True
                entry = c
                plan = _execution_plan(
                    zone,
                    entry,
                    stop_anchor,
                    a15,
                    nearest_support,
                )
                if plan is None:
                    return {
                        "filled": False,
                        "reject_reason": "INVALID_EXECUTION_PLAN",
                        **audit,
                    }

                payload = {
                    "filled": bool(plan["execution_ok"]),
                    "execution_candidate": True,
                    "reject_reason": plan["execution_reject_reason"],
                    "entry_time": (
                        pd.Timestamp(ts) + pd.Timedelta(minutes=15)
                    ).isoformat(),
                    "setup": setup.get("v42_setup"),
                    "subtype": setup.get("v42_subtype"),
                    "setup_quality": setup.get("v42_setup_quality"),
                    "zone_source": zone["source"],
                    "zone_lower": zone["lower"],
                    "zone_upper": zone["upper"],
                    "zone_location_quality": zone.get("location_quality"),
                    "zone_prior_touch_count": zone.get("prior_touch_count"),
                    "touch_bar": touch_bar,
                    "bos_bar": bos_bar,
                    "bos_level": bos_level,
                    "pivot_age_bars": None if pivot is None else pivot.get("age_bars"),
                    "pivot_prominence_atr15": (
                        None
                        if pivot is None
                        else round(float(pivot["prominence"]) / a15, 4)
                    ),
                    "displacement": displacement,
                    "wait_bars_15m": bars,
                    **plan,
                    **audit,
                }
                return payload

            history = pd.concat([history, row.to_frame().T])
            continue

    return {
        "filled": False,
        "reject_reason": last_reason,
        "state": state,
        "pivot_price": None if pivot is None else pivot.get("price"),
        "bos_level": bos_level,
        **audit,
    }
