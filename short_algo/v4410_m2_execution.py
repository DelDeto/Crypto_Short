"""V4.4.10 M2 — No-stop post-entry path study.

Signal and entry are frozen from V4.4.9:
  break -> confirmed support flip -> 1H bearish confirmation -> next 15m open.

After entry:
- NO stop-loss
- NO take-profit
- NO PnL decision

The engine only records MAE/MFE, time-to-excursion, reclaim diagnostics and
forward path statistics.
"""
import math

import pandas as pd

from .v447_execution import _find_break_event, _future_closed
from .v449_m2_execution import _find_1h_entry, _watch_support_flip
from .v4410_m2_config import (
    V4410_FAVORABLE_THRESHOLDS_ATR,
    V4410_PATH_HORIZONS_HOURS,
    V4410_RECLAIM_BUFFER_ATR,
    V4410_RECLAIM_CONFIRM_4H,
)

STEP = pd.Timedelta(minutes=15)


def _bar_values(bar):
    vals = tuple(float(bar[k]) for k in ("open", "high", "low", "close"))
    return vals if all(math.isfinite(x) for x in vals) else None


def _contiguous_slice(future15, start_idx, bars):
    if future15 is None or future15.empty:
        return None
    end_idx = int(start_idx) + int(bars)
    if end_idx > len(future15):
        return None
    view = future15.iloc[int(start_idx):end_idx]
    if len(view) != int(bars):
        return None
    start_time = view.index[0]
    for i, ts in enumerate(view.index):
        if ts != start_time + i * STEP:
            return None
    return view


def _path_for_horizon(future15, start_idx, entry, atr, hours):
    bars = int(hours) * 4
    view = _contiguous_slice(future15, start_idx, bars)
    if view is None or view.empty:
        return {
            "complete": 0,
            "bars": 0 if view is None else len(view),
        }

    highs = view["high"].astype(float)
    lows = view["low"].astype(float)
    closes = view["close"].astype(float)

    max_high = float(highs.max())
    min_low = float(lows.min())
    max_high_pos = int(highs.values.argmax())
    min_low_pos = int(lows.values.argmin())

    mae_price = max(0.0, max_high - float(entry))
    mfe_price = max(0.0, float(entry) - min_low)

    return {
        "complete": 1,
        "bars": len(view),
        "mae_atr": mae_price / float(atr),
        "mae_pct": 100.0 * mae_price / float(entry),
        "mfe_atr": mfe_price / float(atr),
        "mfe_pct": 100.0 * mfe_price / float(entry),
        "time_to_mae_h": (max_high_pos + 1) / 4.0,
        "time_to_mfe_h": (min_low_pos + 1) / 4.0,
        "forward_close_atr": (
            float(entry) - float(closes.iloc[-1])
        ) / float(atr),
        "forward_close_pct": (
            100.0 * (float(entry) - float(closes.iloc[-1])) / float(entry)
        ),
    }


def _threshold_path(future15, start_idx, entry, atr, threshold_atr, max_hours):
    bars = int(max_hours) * 4
    view = _contiguous_slice(future15, start_idx, bars)
    if view is None or view.empty:
        return {
            "complete": 0,
            "hit": 0,
            "time_to_hit_h": None,
            "mae_before_hit_atr": None,
            "mae_before_hit_pct": None,
        }

    target = float(entry) - float(threshold_atr) * float(atr)
    for i in range(len(view)):
        vals = _bar_values(view.iloc[i])
        if vals is None:
            return {
                "complete": 0,
                "hit": 0,
                "time_to_hit_h": None,
                "mae_before_hit_atr": None,
                "mae_before_hit_pct": None,
            }
        _, _, low, _ = vals
        if low <= target:
            prefix = view.iloc[: i + 1]
            max_high = float(prefix["high"].astype(float).max())
            adverse = max(0.0, max_high - float(entry))
            return {
                "complete": 1,
                "hit": 1,
                "time_to_hit_h": (i + 1) / 4.0,
                "mae_before_hit_atr": adverse / float(atr),
                "mae_before_hit_pct": (
                    100.0 * adverse / float(entry)
                ),
            }

    return {
        "complete": 1,
        "hit": 0,
        "time_to_hit_h": None,
        "mae_before_hit_atr": None,
        "mae_before_hit_pct": None,
    }


def _reclaim_after_entry(event, future4h, entry_time):
    atr = float(event["atr"])
    threshold = (
        float(event["upper"]) + float(V4410_RECLAIM_BUFFER_ATR) * atr
    )
    rows = _future_closed(future4h, entry_time, 4)
    if rows is None or rows.empty:
        return {
            "reclaimed": 0,
            "reclaim_time": None,
            "time_to_reclaim_h": None,
            "max_close_above_zone_atr": None,
        }

    consecutive = 0
    max_close_above = 0.0
    for i in range(len(rows)):
        vals = _bar_values(rows.iloc[i])
        if vals is None:
            continue
        _, _, _, close = vals
        max_close_above = max(
            max_close_above,
            max(0.0, close - float(event["upper"])),
        )
        if close > threshold:
            consecutive += 1
        else:
            consecutive = 0

        if consecutive >= int(V4410_RECLAIM_CONFIRM_4H):
            reclaim_time = rows.index[i] + pd.Timedelta(hours=4)
            return {
                "reclaimed": 1,
                "reclaim_time": reclaim_time,
                "time_to_reclaim_h": (
                    reclaim_time - pd.Timestamp(entry_time)
                ).total_seconds() / 3600.0,
                "max_close_above_zone_atr": (
                    max_close_above / atr
                ),
            }

    return {
        "reclaimed": 0,
        "reclaim_time": None,
        "time_to_reclaim_h": None,
        "max_close_above_zone_atr": max_close_above / atr,
    }


def evaluate_v4410_m2_path(
    features,
    signal_time,
    hist4h,
    future4h,
    future1h,
    future15,
):
    prefix = "v4410_m2"
    out = {
        f"{prefix}_state": "NO_STRUCTURAL_BREAK",
        f"{prefix}_lifecycle": "NO_EVENT",
        f"{prefix}_break_time": None,
        f"{prefix}_support_level": None,
        f"{prefix}_support_lower": None,
        f"{prefix}_support_upper": None,
        f"{prefix}_watch_state": None,
        f"{prefix}_ready_reason": None,
        f"{prefix}_ready_time": None,
        f"{prefix}_watch_hours": None,
        f"{prefix}_failed_reclaim_attempts": None,
        f"{prefix}_retest_attempts": None,
        f"{prefix}_entry_selection_state": None,
        f"{prefix}_entry_time": None,
        f"{prefix}_entry": None,
        f"{prefix}_entry_below_support_atr": None,
        f"{prefix}_atr_at_entry": None,
        f"{prefix}_reclaimed_after_entry": None,
        f"{prefix}_reclaim_time": None,
        f"{prefix}_time_to_reclaim_h": None,
        f"{prefix}_max_close_above_zone_atr": None,
    }

    event = _find_break_event(features, hist4h, future4h, signal_time)
    if event is None:
        return out

    out.update({
        f"{prefix}_state": "BREAK_CONFIRMED",
        f"{prefix}_lifecycle": "BREAK_CONFIRMED",
        f"{prefix}_break_time": event["break_time"].isoformat(),
        f"{prefix}_support_level": round(float(event["level"]), 10),
        f"{prefix}_support_lower": round(float(event["lower"]), 10),
        f"{prefix}_support_upper": round(float(event["upper"]), 10),
    })

    watch = _watch_support_flip(event, future4h)
    out.update({
        f"{prefix}_watch_state": watch.get("state"),
        f"{prefix}_ready_reason": watch.get("ready_reason"),
        f"{prefix}_ready_time": (
            watch["ready_time"].isoformat()
            if watch.get("ready_time") is not None
            else None
        ),
        f"{prefix}_watch_hours": watch.get("watch_hours"),
        f"{prefix}_failed_reclaim_attempts": watch.get(
            "failed_reclaim_attempts"
        ),
        f"{prefix}_retest_attempts": watch.get("retest_attempts"),
    })

    if watch.get("state") != "CONFIRMED_SUPPORT_FLIP":
        out[f"{prefix}_state"] = watch.get("state") or "WATCH_ENDED"
        out[f"{prefix}_lifecycle"] = watch.get("state") or "WATCH_ENDED"
        return out

    out[f"{prefix}_lifecycle"] = "CONFIRMED_SUPPORT_FLIP"
    entry_plan = _find_1h_entry(watch, event, future1h, future15)
    out[f"{prefix}_entry_selection_state"] = entry_plan.get("state")
    if entry_plan.get("state") != "ENTRY":
        out[f"{prefix}_state"] = (
            entry_plan.get("state") or "NO_ENTRY"
        )
        return out

    entry_idx = int(entry_plan["entry_idx"])
    entry = float(entry_plan["entry"])
    atr = float(event["atr"])
    entry_time = future15.index[entry_idx]

    out.update({
        f"{prefix}_state": "PATH_STUDY",
        f"{prefix}_lifecycle": "ENTRY_PATH_STUDY",
        f"{prefix}_entry_time": entry_time.isoformat(),
        f"{prefix}_entry": round(entry, 10),
        f"{prefix}_entry_below_support_atr": round(
            float(entry_plan["entry_below_support_atr"]), 4
        ),
        f"{prefix}_atr_at_entry": round(atr, 10),
    })

    for hours in V4410_PATH_HORIZONS_HOURS:
        stats = _path_for_horizon(
            future15, entry_idx, entry, atr, int(hours)
        )
        tag = f"{int(hours)}h"
        for key, value in stats.items():
            out[f"{prefix}_{tag}_{key}"] = (
                round(float(value), 5)
                if isinstance(value, float)
                else value
            )

    max_hours = int(max(V4410_PATH_HORIZONS_HOURS))
    for threshold in V4410_FAVORABLE_THRESHOLDS_ATR:
        stats = _threshold_path(
            future15,
            entry_idx,
            entry,
            atr,
            float(threshold),
            max_hours,
        )
        tag = str(threshold).replace(".", "_")
        for key, value in stats.items():
            out[f"{prefix}_fav_{tag}atr_{key}"] = (
                round(float(value), 5)
                if isinstance(value, float)
                else value
            )

    reclaim = _reclaim_after_entry(event, future4h, entry_time)
    out.update({
        f"{prefix}_reclaimed_after_entry": reclaim["reclaimed"],
        f"{prefix}_reclaim_time": (
            reclaim["reclaim_time"].isoformat()
            if reclaim["reclaim_time"] is not None
            else None
        ),
        f"{prefix}_time_to_reclaim_h": (
            round(float(reclaim["time_to_reclaim_h"]), 5)
            if reclaim["time_to_reclaim_h"] is not None
            else None
        ),
        f"{prefix}_max_close_above_zone_atr": (
            round(float(reclaim["max_close_above_zone_atr"]), 5)
            if reclaim["max_close_above_zone_atr"] is not None
            else None
        ),
    })
    return out
