"""V4.2.6 future labels: persistent trend, reversal risk and 2R zone outcome."""

from .v425_diagnostics import future_path_24h
from .v426_config import V426_ZONE_WAIT_HOURS


def zone_2r_outcome(features, future15):
    out = {
        "zone_filled": False,
        "zone_fill_hours": None,
        "y_zone_2r_success": False,
        "zone_trade_outcome": "NO_ZONE",
    }

    entry = features.get("v426_entry_reference")
    stop = features.get("v426_stop_reference")
    tp = features.get("v426_tp2r_reference")
    current = features.get("current_price")
    lower = features.get("preferred_zone_lower")
    upper = features.get("preferred_zone_upper")

    if any(v is None for v in (entry, stop, tp, current, lower, upper)):
        return out

    entry = float(entry)
    stop = float(stop)
    tp = float(tp)
    current = float(current)
    lower = float(lower)
    upper = float(upper)

    if stop <= entry or tp >= entry:
        out["zone_trade_outcome"] = "INVALID_PLAN"
        return out

    max_wait_bars = int(V426_ZONE_WAIT_HOURS) * 4
    fill_idx = None

    if lower <= current <= upper:
        fill_idx = 0
    elif current < lower:
        wait = future15.head(max_wait_bars)
        for i, (_, bar) in enumerate(wait.iterrows()):
            if float(bar["high"]) >= entry:
                fill_idx = i
                break
    else:
        # Price is already above the preferred Short zone. Do not pretend
        # the lower reference entry was available after the scan.
        out["zone_trade_outcome"] = "ABOVE_ZONE"
        return out

    if fill_idx is None:
        out["zone_trade_outcome"] = "NO_FILL"
        return out

    out["zone_filled"] = True
    out["zone_fill_hours"] = round(fill_idx * 0.25, 3)

    after = future15.iloc[fill_idx:24 * 4]
    for _, bar in after.iterrows():
        hit_sl = float(bar["high"]) >= stop
        hit_tp = float(bar["low"]) <= tp
        if hit_sl and hit_tp:
            out["zone_trade_outcome"] = "SL_SAME_BAR"
            out["y_zone_2r_success"] = False
            return out
        if hit_sl:
            out["zone_trade_outcome"] = "SL_FIRST"
            out["y_zone_2r_success"] = False
            return out
        if hit_tp:
            out["zone_trade_outcome"] = "TP2R_FIRST"
            out["y_zone_2r_success"] = True
            return out

    out["zone_trade_outcome"] = "UNRESOLVED_24H"
    return out


def future_labels_v426(
    features,
    signal_time,
    future15,
    btc_start,
    eth_start,
    btc_future,
    eth_future,
):
    path = future_path_24h(
        features["current_price"],
        features["atr_1h"],
        signal_time,
        future15,
        btc_start=btc_start,
        eth_start=eth_start,
        btc_future=btc_future,
        eth_future=eth_future,
    )

    y4 = path.get("y_4h_lower")
    y12 = path.get("y_12h_lower")
    y24 = path.get("y_24h_lower")

    path["y_persistent_short"] = (
        None
        if any(v is None for v in (y4, y12, y24))
        else bool(y4 and y12 and y24)
    )

    max_downside = float(path.get("max_downside_24h_atr") or 0.0)
    reclaimed = bool(path.get("reclaimed_signal_after_mfe"))
    path["y_reversal_after_short"] = bool(
        max_downside >= 0.5 and reclaimed
    )

    path.update(zone_2r_outcome(features, future15))
    return path
