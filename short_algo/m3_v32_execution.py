"""M3 V3.2 — causal post-retest continuation trigger research.

Builds on M3 V2.1. The setup/POI/retest logic stays frozen; V3.2 changes only
entry timing. After a confirmed failed retest, it waits up to N completed 15m
bars for a bearish continuation close below the retest low, then benchmarks
entry at the next 15m open.

Research only. The user remains the real entry/exit decision maker.
"""
import math
import pandas as pd

from .indicators import atr
from .m3_v21_execution import evaluate_m3_v21
from .m3_v2_execution import _find_displacement_retest, _three_pct_outcome
from .m3_v32_config import (
    M3_V32_MAX_TARGET_ATR,
    M3_V32_MAX_TRIGGER_CHASE_ATR15,
    M3_V32_MIN_RETEST_QUALITY,
    M3_V32_TIGHT_MAX_PENETRATION_ATR15,
    M3_V32_TIGHT_MIN_UPPER_WICK_RATIO,
    M3_V32_TRIGGER_BARS,
    M3_V32_TRIGGER_CLOSE_BUFFER_ATR15,
)

STEP = pd.Timedelta(minutes=15)


def _num(x):
    try:
        y = float(x)
        return y if math.isfinite(y) else None
    except (TypeError, ValueError):
        return None


def _post_retest_trigger(fifteen, seq):
    if seq.get("state") != "RETEST_ENTRY":
        return {"state": "NO_RETEST"}

    frame = fifteen.sort_index()
    entry_time = pd.Timestamp(seq["entry_time"])
    if entry_time not in frame.index:
        return {"state": "ENTRY_TIME_MISSING"}

    immediate_i = int(frame.index.get_loc(entry_time))
    retest_i = immediate_i - 1
    if retest_i < 0:
        return {"state": "NO_RETEST_BAR"}

    retest = frame.iloc[retest_i]
    retest_low = float(retest["low"])
    break_level = float(seq["break_level"])
    a15 = atr(frame, 14)

    last_i = min(len(frame) - 2, retest_i + int(M3_V32_TRIGGER_BARS))
    for i in range(retest_i + 1, last_i + 1):
        row = frame.iloc[i]
        a = _num(a15.iloc[i]) or _num(seq.get("atr15")) or 0.0
        if a <= 0:
            continue

        close = float(row["close"])
        open_ = float(row["open"])
        trigger_level = retest_low - float(M3_V32_TRIGGER_CLOSE_BUFFER_ATR15) * a
        confirmed = close < trigger_level and close < open_
        if not confirmed:
            continue

        next_i = i + 1
        entry = float(frame.iloc[next_i]["open"])
        chase = max(0.0, break_level - entry) / max(a, 1e-12)
        if chase > float(M3_V32_MAX_TRIGGER_CHASE_ATR15):
            continue

        return {
            "state": "TRIGGER_ENTRY",
            "trigger_time": frame.index[i] + STEP,
            "entry_time": frame.index[next_i],
            "entry_idx": next_i,
            "entry": entry,
            "retest_low": retest_low,
            "trigger_level": trigger_level,
            "trigger_close": close,
            "trigger_atr15": a,
            "trigger_chase_atr15": chase,
            "wait_bars": i - retest_i,
        }

    return {"state": "NO_TRIGGER"}


def evaluate_m3_v32(one_closed, four_closed, fifteen, signal_time):
    out = evaluate_m3_v21(one_closed, four_closed, fifteen, signal_time)
    if out.get("m3v21_state") != "ENTRY_BENCHMARK":
        out["m3v32_state"] = "NO_BASE_ENTRY"
        return out

    quality = int(out.get("m3v21_retest_quality_score") or 0)
    target_atr = float(out.get("m3v2_target3_atr") or 99.0)
    is_broken_support = out.get("m3v2_poi_source") == "BROKEN_SUPPORT_1H"
    core = bool(
        is_broken_support
        and quality >= int(M3_V32_MIN_RETEST_QUALITY)
        and target_atr <= float(M3_V32_MAX_TARGET_ATR)
    )
    out["m3v32_core_gate_pass"] = int(core)

    penetration = float(out.get("m3v21_retest_penetration_atr15") or 99.0)
    wick = float(out.get("m3v21_retest_upper_wick_ratio") or 0.0)
    lower_high = int(out.get("m3v21_retest_lower_high") or 0)
    tight = bool(
        core
        and penetration <= float(M3_V32_TIGHT_MAX_PENETRATION_ATR15)
        and wick >= float(M3_V32_TIGHT_MIN_UPPER_WICK_RATIO)
        and lower_high == 1
    )
    out["m3v32_tight_gate_pass"] = int(tight)

    seq = _find_displacement_retest(fifteen, signal_time)
    trig = _post_retest_trigger(fifteen, seq)
    out["m3v32_trigger_state"] = trig.get("state")
    if trig.get("state") != "TRIGGER_ENTRY":
        out["m3v32_state"] = "NO_TRIGGER"
        return out

    entry = float(trig["entry"])
    entry_idx = int(trig["entry_idx"])
    out.update({
        "m3v32_state": "TRIGGER_ENTRY",
        "m3v32_trigger_time": pd.Timestamp(trig["trigger_time"]).isoformat(),
        "m3v32_entry_time": pd.Timestamp(trig["entry_time"]).isoformat(),
        "m3v32_entry": round(entry, 10),
        "m3v32_retest_low": round(float(trig["retest_low"]), 10),
        "m3v32_trigger_level": round(float(trig["trigger_level"]), 10),
        "m3v32_trigger_close": round(float(trig["trigger_close"]), 10),
        "m3v32_trigger_chase_atr15": round(float(trig["trigger_chase_atr15"]), 5),
        "m3v32_trigger_wait_bars": int(trig["wait_bars"]),
    })

    # Same 3%/24h outcome definition as V2/V2.1, but measured from V3.2 entry.
    outcome = _three_pct_outcome(fifteen, entry_idx, entry)
    for key, value in outcome.items():
        out[key.replace("m3v2_", "m3v32_")] = value
    return out
