"""24h future-path labels for V4.2.5 research only."""

from .v425_config import (
    V425_BLOCK_HOURS,
    V425_FIRST_MOVE_ATR,
    V425_FIRST_MOVE_WINDOW_HOURS,
    V425_PATH_HOURS,
)


def _future_market_return(start_price, future1h, hours):
    if (
        start_price is None
        or future1h is None
        or future1h.empty
        or len(future1h) < hours
    ):
        return None
    end = float(future1h.head(hours)["close"].iloc[-1])
    start = float(start_price)
    if start <= 0:
        return None
    return (end / start - 1.0) * 100.0


def _market_average_return(
    btc_start,
    eth_start,
    btc_future,
    eth_future,
    hours,
):
    vals = []
    for start, future in (
        (btc_start, btc_future),
        (eth_start, eth_future),
    ):
        value = _future_market_return(start, future, hours)
        if value is not None:
            vals.append(value)
    return sum(vals) / len(vals) if vals else None


def _coin_snapshot(price, a1, future15, hours):
    need = int(hours) * 4
    if len(future15) < need:
        return None
    view = future15.head(need)
    end = float(view["close"].iloc[-1])
    low = float(view["low"].min())
    high = float(view["high"].max())
    return {
        "close_pct": (end / price - 1.0) * 100.0,
        "close_atr": (price - end) / a1,
        "mfe_atr": max(0.0, price - low) / a1,
        "mae_atr": max(0.0, high - price) / a1,
        "short": bool(end < price),
        "end_price": end,
    }


def future_path_24h(
    signal_price,
    atr_1h,
    signal_time,
    future15,
    btc_start=None,
    eth_start=None,
    btc_future=None,
    eth_future=None,
):
    result = {
        "y_4h_lower": None,
        "y_12h_lower": None,
        "y_24h_lower": None,
        "y_first_short": None,
        "y_rel_4h_underperform": None,
        "y_rel_12h_underperform": None,
        "y_rel_24h_underperform": None,
        "dir_first_0_5atr_move": "NONE",
        "path_class_24h": "UNKNOWN",
    }
    if future15 is None or future15.empty or atr_1h <= 0:
        return result

    price = float(signal_price)
    a1 = float(atr_1h)

    snapshots = {}
    for hours in V425_PATH_HOURS:
        snap = _coin_snapshot(price, a1, future15, hours)
        if snap is None:
            continue
        snapshots[hours] = snap
        result[f"dir_{hours}h_close_pct"] = round(
            snap["close_pct"], 4
        )
        result[f"dir_{hours}h_close_atr"] = round(
            snap["close_atr"], 4
        )
        result[f"dir_{hours}h_mfe_atr"] = round(
            snap["mfe_atr"], 4
        )
        result[f"dir_{hours}h_mae_atr"] = round(
            snap["mae_atr"], 4
        )
        result[f"dir_{hours}h_short"] = snap["short"]

        market_ret = _market_average_return(
            btc_start,
            eth_start,
            btc_future,
            eth_future,
            int(hours),
        )
        if market_ret is not None:
            relative = snap["close_pct"] - market_ret
            result[f"market_{hours}h_return_pct"] = round(
                market_ret, 4
            )
            result[f"relative_{hours}h_future_pct"] = round(
                relative, 4
            )

    result["y_4h_lower"] = (
        None if 4 not in snapshots else snapshots[4]["short"]
    )
    result["y_12h_lower"] = (
        None if 12 not in snapshots else snapshots[12]["short"]
    )
    result["y_24h_lower"] = (
        None if 24 not in snapshots else snapshots[24]["short"]
    )

    for hours in (4, 12, 24):
        key = f"relative_{hours}h_future_pct"
        if result.get(key) is not None:
            result[f"y_rel_{hours}h_underperform"] = bool(
                float(result[key]) < 0.0
            )

    threshold = float(V425_FIRST_MOVE_ATR) * a1
    first = "NONE"
    max_first_bars = int(V425_FIRST_MOVE_WINDOW_HOURS) * 4
    for _, row in future15.head(max_first_bars).iterrows():
        short_hit = float(row["low"]) <= price - threshold
        adverse_hit = float(row["high"]) >= price + threshold
        if short_hit and adverse_hit:
            first = "AMBIGUOUS"
            break
        if short_hit:
            first = "SHORT_0.5ATR_FIRST"
            result["y_first_short"] = True
            break
        if adverse_hit:
            first = "ADVERSE_0.5ATR_FIRST"
            result["y_first_short"] = False
            break
    result["dir_first_0_5atr_move"] = first

    # Six sequential 4h blocks. Positive return_atr means movement in Short direction.
    previous_price = price
    previous_market = 0.0
    total_blocks = 24 // int(V425_BLOCK_HOURS)
    for block in range(total_blocks):
        start_h = block * int(V425_BLOCK_HOURS)
        end_h = start_h + int(V425_BLOCK_HOURS)
        start_bar = start_h * 4
        end_bar = end_h * 4
        if len(future15) < end_bar:
            break
        view = future15.iloc[start_bar:end_bar]
        end_price = float(view["close"].iloc[-1])
        low = float(view["low"].min())
        high = float(view["high"].max())
        prefix = f"block_{start_h}_{end_h}h"
        result[f"{prefix}_return_atr"] = round(
            (previous_price - end_price) / a1, 4
        )
        result[f"{prefix}_mfe_atr"] = round(
            max(0.0, previous_price - low) / a1, 4
        )
        result[f"{prefix}_mae_atr"] = round(
            max(0.0, high - previous_price) / a1, 4
        )
        result[f"{prefix}_short"] = bool(end_price < previous_price)

        market_end = _market_average_return(
            btc_start,
            eth_start,
            btc_future,
            eth_future,
            end_h,
        )
        if market_end is not None:
            market_block = market_end - previous_market
            coin_block_pct = (
                end_price / previous_price - 1.0
            ) * 100.0
            result[f"{prefix}_relative_pct"] = round(
                coin_block_pct - market_block, 4
            )
            previous_market = market_end
        previous_price = end_price

    # Best downside opportunity and subsequent reversal behavior.
    view24 = future15.head(24 * 4)
    if not view24.empty:
        low_series = view24["low"].astype(float)
        high_series = view24["high"].astype(float)
        min_time = low_series.idxmin()
        max_time = high_series.idxmax()
        min_price = float(low_series.loc[min_time])
        max_price = float(high_series.loc[max_time])

        result["max_downside_24h_atr"] = round(
            max(0.0, price - min_price) / a1, 4
        )
        result["max_adverse_24h_atr"] = round(
            max(0.0, max_price - price) / a1, 4
        )

        try:
            signal_ts = signal_time
            hours_to_mfe = (
                (min_time - signal_ts).total_seconds() / 3600.0
                + 0.25
            )
            hours_to_mae = (
                (max_time - signal_ts).total_seconds() / 3600.0
                + 0.25
            )
            result["hours_to_max_downside"] = round(
                max(0.0, hours_to_mfe), 3
            )
            result["hours_to_max_adverse"] = round(
                max(0.0, hours_to_mae), 3
            )
        except Exception:
            pass

        after_mfe = view24.loc[view24.index > min_time]
        reclaimed = False
        reclaim_hours = None
        rebound_from_mfe_atr = 0.0
        if not after_mfe.empty:
            rebound_from_mfe_atr = max(
                0.0,
                float(after_mfe["high"].max()) - min_price,
            ) / a1
            reclaim_rows = after_mfe[
                after_mfe["close"].astype(float) >= price
            ]
            if not reclaim_rows.empty:
                reclaimed = True
                try:
                    reclaim_time = reclaim_rows.index[0]
                    reclaim_hours = (
                        (reclaim_time - min_time).total_seconds()
                        / 3600.0
                        + 0.25
                    )
                except Exception:
                    reclaim_hours = None

        result["reclaimed_signal_after_mfe"] = reclaimed
        result["rebound_from_mfe_atr"] = round(
            rebound_from_mfe_atr, 4
        )
        if reclaim_hours is not None:
            result["hours_mfe_to_signal_reclaim"] = round(
                max(0.0, reclaim_hours), 3
            )

    mfe4 = float(result.get("dir_4h_mfe_atr") or 0.0)
    mfe24 = float(result.get("dir_24h_mfe_atr") or 0.0)
    mae4 = float(result.get("dir_4h_mae_atr") or 0.0)
    short24 = result.get("dir_24h_short")
    reclaimed = bool(result.get("reclaimed_signal_after_mfe"))

    if mfe4 >= 0.5 and short24 is True and not reclaimed:
        path_class = "PERSISTENT_SHORT"
    elif mfe4 >= 0.5 and (short24 is False or reclaimed):
        path_class = "SHORT_THEN_REVERSE"
    elif mfe4 < 0.5 and mfe24 >= 1.0 and short24 is True:
        path_class = "DELAYED_SHORT"
    elif mae4 >= 0.5 and mfe4 < 0.5:
        path_class = "WRONG_WAY_EARLY"
    else:
        path_class = "MIXED"
    result["path_class_24h"] = path_class

    result["dir_short_votes_24h"] = sum(
        1
        for h in V425_PATH_HOURS
        if result.get(f"dir_{h}h_short") is True
    )
    return result
