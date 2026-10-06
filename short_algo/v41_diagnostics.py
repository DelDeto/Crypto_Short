"""Entry follow-through and post-stop path diagnostics for V4.1."""

import pandas as pd

from .v41_config import V41_FOLLOWTHROUGH_HOURS, V41_POST_SL_HOURS


def entry_followthrough(entry, risk, future15):
    result = {}
    if future15 is None or future15.empty or risk <= 0:
        return result

    entry = float(entry)
    risk = float(risk)

    for hours in V41_FOLLOWTHROUGH_HOURS:
        view = future15.head(max(1, int(hours) * 4))
        if view.empty:
            continue
        min_low = float(view["low"].min())
        max_high = float(view["high"].max())
        close = float(view["close"].iloc[-1])
        result[f"ft_{hours}h_close_r"] = round((entry - close) / risk, 4)
        result[f"ft_{hours}h_mfe_r"] = round(max(0.0, entry - min_low) / risk, 4)
        result[f"ft_{hours}h_mae_r"] = round(max(0.0, max_high - entry) / risk, 4)
        result[f"ft_{hours}h_short"] = bool(close < entry)

    # Which meaningful move occurred first after entry?
    first = "NONE"
    for _, row in future15.head(16).iterrows():  # first 4h
        hit_good = float(row["low"]) <= entry - 0.5 * risk
        hit_bad = float(row["high"]) >= entry + 0.5 * risk
        if hit_good and hit_bad:
            first = "AMBIGUOUS"
            break
        if hit_good:
            first = "SHORT_0.5R_FIRST"
            break
        if hit_bad:
            first = "ADVERSE_0.5R_FIRST"
            break
    result["ft_first_0_5r_move"] = first
    return result


def post_stop_reversal(entry, stop, tp1, future15, bars_to_stop):
    """Continue observing after a stopped trade.

    The stop bar itself is excluded because intrabar ordering after the stop is
    unknowable from OHLC. Classification begins with the next 15m candle.
    """
    if future15 is None or future15.empty:
        return {}

    bars_to_stop = int(bars_to_stop or 0)
    if bars_to_stop <= 0:
        return {}

    entry = float(entry)
    stop = float(stop)
    tp1 = float(tp1)
    risk = stop - entry
    if risk <= 0:
        return {}

    after = future15.iloc[bars_to_stop:].head(max(1, V41_POST_SL_HOURS * 4))
    if after.empty:
        return {
            "post_sl_class": "NO_DATA",
            "post_sl_observed_hours": 0.0,
        }

    levels = {
        "entry": entry,
        "plus_1r": entry - risk,
        "tp2r": tp1,
    }
    hits = {}
    for name, level in levels.items():
        hit_pos = None
        for i, (_, row) in enumerate(after.iterrows(), start=1):
            if float(row["low"]) <= level:
                hit_pos = i
                break
        hits[f"post_sl_reached_{name}"] = hit_pos is not None
        hits[f"post_sl_hours_to_{name}"] = (
            round(hit_pos / 4.0, 2) if hit_pos is not None else None
        )

    min_low = float(after["low"].min())
    max_high = float(after["high"].max())
    hits["post_sl_mfe_r"] = round(max(0.0, entry - min_low) / risk, 4)
    hits["post_sl_additional_adverse_r"] = round(
        max(0.0, max_high - stop) / risk, 4
    )
    hits["post_sl_observed_hours"] = round(len(after) / 4.0, 2)

    if hits["post_sl_reached_tp2r"]:
        cls = "FALSE_STOP_THEN_TP2R"
    elif hits["post_sl_reached_plus_1r"]:
        cls = "FALSE_STOP_THEN_1R"
    elif hits["post_sl_reached_entry"]:
        cls = "STOP_THEN_RECLAIM_ENTRY"
    else:
        cls = "VALID_STOP_CONTINUED_WRONG"
    hits["post_sl_class"] = cls
    return hits
