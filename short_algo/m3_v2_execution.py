"""M3 V2 — retest entry engine + 3%/24h path outcome study.

Research only. The user remains the live entry/exit decision maker.
"""
import math
import pandas as pd

from .indicators import atr, swing_points
from .m3_v1_execution import _four_bear_context, _find_impulse_pullback, _resistance_and_rejection
from .m3_v1_config import M3_MIN_4H_BEAR_SCORE
from .m3_v2_config import (
    M3_V2_DISPLACEMENT_WINDOW_MIN,
    M3_V2_MAX_CHASE_ATR15,
    M3_V2_MAX_TARGET_ATR,
    M3_V2_RETEST_ABOVE_ATR15,
    M3_V2_RETEST_BARS,
    M3_V2_RETEST_BELOW_ATR15,
    M3_V2_MIN_DISPLACEMENT_ATR15,
    M3_V2_ROOM_GATE_PCT,
    M3_V2_TARGET_PCT,
)

STEP = pd.Timedelta(minutes=15)


def _num(x):
    try:
        y = float(x)
        return y if math.isfinite(y) else None
    except (TypeError, ValueError):
        return None


def _nearest_known_demand(one_closed, entry):
    """Nearest confirmed 1H swing low below entry, using only closed bars."""
    _, lows = swing_points(one_closed, left=2, right=2)
    below = [float(x["price"]) for x in lows if float(x["price"]) < float(entry)]
    if not below:
        return None
    return max(below)


def _find_displacement_retest(fifteen, signal_time):
    """Causal 15m micro-BOS -> retest failure -> next-bar benchmark entry."""
    if fifteen is None or len(fifteen) < 30:
        return {"state": "NO_15M_DATA"}

    frame = fifteen.sort_index().copy()
    a15 = atr(frame, 14)
    start = pd.Timestamp(signal_time)
    deadline = start + pd.Timedelta(minutes=int(M3_V2_DISPLACEMENT_WINDOW_MIN))

    positions = [i for i, ts in enumerate(frame.index) if start <= ts + STEP <= deadline]
    for i in positions:
        if i < 8 or i + 2 >= len(frame):
            continue
        row = frame.iloc[i]
        o, h, l, c = (float(row[k]) for k in ("open", "high", "low", "close"))
        a = _num(a15.iloc[i])
        if not a or a <= 0:
            continue

        prior = frame.iloc[i-4:i]
        micro_low = float(prior["low"].astype(float).min())
        body = max(0.0, o - c)
        bearish_displacement = (
            c < o
            and c < micro_low
            and body / a >= float(M3_V2_MIN_DISPLACEMENT_ATR15)
        )
        if not bearish_displacement:
            continue

        break_level = micro_low
        displacement_close_time = frame.index[i] + STEP

        for j in range(i + 1, min(i + 1 + int(M3_V2_RETEST_BARS), len(frame) - 1)):
            r = frame.iloc[j]
            ro, rh, rl, rc = (float(r[k]) for k in ("open", "high", "low", "close"))
            aj = _num(a15.iloc[j]) or a

            # A decisive reclaim invalidates this break/retest sequence.
            if rc > break_level + float(M3_V2_RETEST_ABOVE_ATR15) * aj:
                break

            touched = (
                rh >= break_level - float(M3_V2_RETEST_BELOW_ATR15) * aj
                and rl <= break_level + float(M3_V2_RETEST_ABOVE_ATR15) * aj
            )
            failed = touched and rc < break_level and rc <= ro
            if not failed:
                continue

            entry_i = j + 1
            entry = float(frame.iloc[entry_i]["open"])
            chase_atr = max(0.0, break_level - entry) / max(aj, 1e-12)
            if chase_atr > float(M3_V2_MAX_CHASE_ATR15):
                continue

            return {
                "state": "RETEST_ENTRY",
                "displacement_time": displacement_close_time,
                "retest_time": frame.index[j] + STEP,
                "entry_time": frame.index[entry_i],
                "entry_idx": entry_i,
                "entry": entry,
                "break_level": break_level,
                "atr15": aj,
                "displacement_body_atr15": body / a,
                "retest_high": rh,
                "retest_close": rc,
                "chase_atr15": chase_atr,
            }

    return {"state": "NO_RETEST_ENTRY"}


def _three_pct_outcome(fifteen, entry_idx, entry):
    """Observe whether -3% is reached within 24h and adverse path before target."""
    rows = fifteen.iloc[int(entry_idx):]
    if rows.empty:
        return {}
    start = rows.index[0]
    rows = rows.loc[rows.index < start + pd.Timedelta(hours=24)]
    if rows.empty:
        return {}

    target = float(entry) * (1.0 - float(M3_V2_TARGET_PCT) / 100.0)
    caps = (0.5, 0.75, 1.0, 1.5)
    max_adverse_before_target = 0.0
    max_favorable = 0.0
    max_adverse = 0.0
    target_time = None
    same_bar_ambiguous = False
    first_adverse = {cap: None for cap in caps}

    for t, row in rows.iterrows():
        h = float(row["high"])
        l = float(row["low"])
        fav_pct = max(0.0, (float(entry) - l) / float(entry) * 100.0)
        adv_pct = max(0.0, (h - float(entry)) / float(entry) * 100.0)
        max_favorable = max(max_favorable, fav_pct)
        max_adverse = max(max_adverse, adv_pct)

        for cap in caps:
            if first_adverse[cap] is None and adv_pct >= cap:
                first_adverse[cap] = pd.Timestamp(t) + STEP

        if target_time is None:
            max_adverse_before_target = max(max_adverse_before_target, adv_pct)
            hit_target = l <= target
            if hit_target:
                target_time = pd.Timestamp(t) + STEP
                # Intrabar ordering is unknowable if a cap is also crossed.
                if adv_pct >= 1.0:
                    same_bar_ambiguous = True
                break

    reached = target_time is not None
    minutes = int((target_time - start).total_seconds() // 60) if reached else None

    def clean_at(cap):
        if not reached or same_bar_ambiguous:
            return 0
        adverse_time = first_adverse[cap]
        return int(adverse_time is None or target_time < adverse_time)

    return {
        "m3v2_target_3pct": round(target, 10),
        "m3v2_hit_3pct_24h": int(reached),
        "m3v2_minutes_to_3pct": minutes,
        "m3v2_pre3pct_mae_pct": round(max_adverse_before_target, 5),
        "m3v2_max_favorable_pct_24h": round(max_favorable, 5),
        "m3v2_max_adverse_pct_24h": round(max_adverse, 5),
        "m3v2_same_bar_3pct_vs_1pct_adverse": int(same_bar_ambiguous),
        "m3v2_clean3_adverse_0_5": clean_at(0.5),
        "m3v2_clean3_adverse_0_75": clean_at(0.75),
        "m3v2_clean3_adverse_1_0": clean_at(1.0),
        "m3v2_clean3_adverse_1_5": clean_at(1.5),
    }


def evaluate_m3_v2(one_closed, four_closed, fifteen, signal_time):
    out = {
        "m3v2_state": "NO_SETUP",
        "m3v2_signal_time": pd.Timestamp(signal_time).isoformat(),
    }

    four = _four_bear_context(four_closed)
    if four is None or int(four["bear_score"]) < int(M3_MIN_4H_BEAR_SCORE):
        out["m3v2_state"] = "FAIL_4H"
        return out

    impulse = _find_impulse_pullback(one_closed)
    if impulse is None:
        out["m3v2_state"] = "NO_IMPULSE_PULLBACK"
        return out

    rejection = _resistance_and_rejection(one_closed, impulse)
    if not rejection.get("ok"):
        out["m3v2_state"] = rejection.get("reason") or "NO_POI_REJECTION"
        return out

    out.update({
        "m3v2_4h_bear_score": int(four["bear_score"]),
        "m3v2_impulse_atr": round(float(impulse["impulse_atr"]), 5),
        "m3v2_pullback_retrace": round(float(impulse["pullback_retrace"]), 5),
        "m3v2_pullback_bars": int(impulse["pullback_bars"]),
        "m3v2_poi_source": rejection.get("resistance_source"),
        "m3v2_poi": rejection.get("resistance"),
        "m3v2_failed_reclaim_1h": rejection.get("failed_reclaim"),
        "m3v2_bearish_rejection_1h": rejection.get("bearish_rejection"),
        "m3v2_lower_high_1h": rejection.get("lower_high_proxy"),
        "m3v2_atr1h": round(float(impulse["atr"]), 10),
    })

    seq = _find_displacement_retest(fifteen, signal_time)
    out["m3v2_entry_sequence_state"] = seq.get("state")
    if seq.get("state") != "RETEST_ENTRY":
        out["m3v2_state"] = "NO_RETEST_ENTRY"
        return out

    entry = float(seq["entry"])
    atr1 = float(impulse["atr"])
    atr1_pct = atr1 / max(entry, 1e-12) * 100.0
    target_atr = float(M3_V2_TARGET_PCT) / max(atr1_pct, 1e-12)

    demand = _nearest_known_demand(one_closed, entry)
    room_pct = (
        (entry - demand) / entry * 100.0
        if demand is not None and demand < entry
        else None
    )

    out.update({
        "m3v2_state": "ENTRY_BENCHMARK",
        "m3v2_entry_time": pd.Timestamp(seq["entry_time"]).isoformat(),
        "m3v2_entry": round(entry, 10),
        "m3v2_break_level": round(float(seq["break_level"]), 10),
        "m3v2_displacement_time": pd.Timestamp(seq["displacement_time"]).isoformat(),
        "m3v2_retest_time": pd.Timestamp(seq["retest_time"]).isoformat(),
        "m3v2_displacement_body_atr15": round(float(seq["displacement_body_atr15"]), 5),
        "m3v2_chase_atr15": round(float(seq["chase_atr15"]), 5),
        "m3v2_atr1h_pct": round(atr1_pct, 5),
        "m3v2_target3_atr": round(target_atr, 5),
        "m3v2_demand": round(demand, 10) if demand is not None else None,
        "m3v2_room_to_demand_pct": round(room_pct, 5) if room_pct is not None else None,
        "m3v2_room_gate_pass": int(room_pct is not None and room_pct >= float(M3_V2_ROOM_GATE_PCT)),
        "m3v2_vol_gate_pass": int(target_atr <= float(M3_V2_MAX_TARGET_ATR)),
    })
    out.update(_three_pct_outcome(fifteen, int(seq["entry_idx"]), entry))
    return out
