"""M3 V3.3 — compare three causal retest entry styles.

A = V2.1 baseline: next 15m open after failed retest.
B = POI limit: after retest closes, rest sell limit at broken support for up to
    N subsequent bars; fill only if price trades back to POI.
C = rejection close: benchmark at failed-retest close only if that close is
    within an anti-chase ATR distance from POI.

Research only; no live signaling or order placement.
"""
import math
import pandas as pd

from .indicators import atr
from .m3_v21_execution import evaluate_m3_v21
from .m3_v2_execution import _find_displacement_retest, _three_pct_outcome
from .m3_v33_config import (
    M3_V33_LIMIT_FILL_BARS,
    M3_V33_MAX_REJECTION_CLOSE_DISTANCE_ATR15,
    M3_V33_MAX_TARGET_ATR,
    M3_V33_MIN_RETEST_QUALITY,
)

STEP = pd.Timedelta(minutes=15)


def _num(x):
    try:
        y = float(x)
        return y if math.isfinite(y) else None
    except (TypeError, ValueError):
        return None


def _rename_outcome(outcome, prefix):
    return {k.replace("m3v2_", prefix): v for k, v in outcome.items()}


def _entry_a(fifteen, seq):
    if seq.get("state") != "RETEST_ENTRY":
        return {"state": "NO_ENTRY"}
    return {
        "state": "FILLED",
        "entry": float(seq["entry"]),
        "entry_idx": int(seq["entry_idx"]),
        "entry_time": pd.Timestamp(seq["entry_time"]),
        "distance_atr15": max(
            0.0, float(seq["break_level"]) - float(seq["entry"])
        ) / max(float(seq.get("atr15") or 0.0), 1e-12),
    }


def _entry_b(fifteen, seq):
    if seq.get("state") != "RETEST_ENTRY":
        return {"state": "NO_ENTRY"}

    frame = fifteen.sort_index()
    immediate_i = int(seq["entry_idx"])
    poi = float(seq["break_level"])
    max_i = min(len(frame) - 1, immediate_i + int(M3_V33_LIMIT_FILL_BARS) - 1)

    for i in range(immediate_i, max_i + 1):
        row = frame.iloc[i]
        if float(row["high"]) >= poi:
            return {
                "state": "FILLED",
                "entry": poi,
                "entry_idx": i,
                "entry_time": frame.index[i],
                "wait_bars": i - immediate_i,
            }

    return {"state": "NO_FILL"}


def _entry_c(fifteen, seq):
    if seq.get("state") != "RETEST_ENTRY":
        return {"state": "NO_ENTRY"}

    frame = fifteen.sort_index()
    entry_i = int(seq["entry_idx"])
    retest_i = entry_i - 1
    if retest_i < 0:
        return {"state": "NO_ENTRY"}

    close = float(frame.iloc[retest_i]["close"])
    poi = float(seq["break_level"])
    a = float(seq.get("atr15") or 0.0)
    if a <= 0:
        a15 = atr(frame, 14)
        a = _num(a15.iloc[retest_i]) or 0.0
    if a <= 0:
        return {"state": "NO_ATR"}

    distance = max(0.0, poi - close) / a
    if distance > float(M3_V33_MAX_REJECTION_CLOSE_DISTANCE_ATR15):
        return {"state": "TOO_CHASED", "distance_atr15": distance}

    return {
        "state": "FILLED",
        "entry": close,
        "entry_idx": entry_i,
        "entry_time": frame.index[retest_i] + STEP,
        "distance_atr15": distance,
    }


def evaluate_m3_v33(one_closed, four_closed, fifteen, signal_time):
    out = evaluate_m3_v21(one_closed, four_closed, fifteen, signal_time)
    if out.get("m3v21_state") != "ENTRY_BENCHMARK":
        out["m3v33_state"] = "NO_BASE_ENTRY"
        return out

    quality = int(out.get("m3v21_retest_quality_score") or 0)
    target_atr = float(out.get("m3v2_target3_atr") or 99.0)
    core = bool(
        out.get("m3v2_poi_source") == "BROKEN_SUPPORT_1H"
        and quality >= int(M3_V33_MIN_RETEST_QUALITY)
        and target_atr <= float(M3_V33_MAX_TARGET_ATR)
    )
    out["m3v33_core_gate_pass"] = int(core)
    if not core:
        out["m3v33_state"] = "FAIL_CORE"
        return out

    seq = _find_displacement_retest(fifteen, signal_time)
    if seq.get("state") != "RETEST_ENTRY":
        out["m3v33_state"] = "NO_RETEST"
        return out

    out["m3v33_state"] = "CORE_CANDIDATE"
    out["m3v33_poi"] = round(float(seq["break_level"]), 10)
    out["m3v33_retest_close"] = round(float(seq["retest_close"]), 10)
    out["m3v33_atr15"] = round(float(seq["atr15"]), 10)

    variants = {"a": _entry_a(fifteen, seq), "b": _entry_b(fifteen, seq), "c": _entry_c(fifteen, seq)}
    for code, entry in variants.items():
        prefix = f"m3v33_{code}_"
        out[prefix + "state"] = entry.get("state")
        if entry.get("state") != "FILLED":
            if "distance_atr15" in entry:
                out[prefix + "distance_atr15"] = round(float(entry["distance_atr15"]), 5)
            continue

        price = float(entry["entry"])
        idx = int(entry["entry_idx"])
        out[prefix + "entry"] = round(price, 10)
        out[prefix + "entry_time"] = pd.Timestamp(entry["entry_time"]).isoformat()
        if "wait_bars" in entry:
            out[prefix + "wait_bars"] = int(entry["wait_bars"])
        if "distance_atr15" in entry:
            out[prefix + "distance_atr15"] = round(float(entry["distance_atr15"]), 5)

        out.update(_rename_outcome(_three_pct_outcome(fifteen, idx, price), prefix))

    return out
