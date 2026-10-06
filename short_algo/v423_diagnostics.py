"""V4.2.3 directional follow-through diagnostics."""

from .v423_config import (
    V423_DIRECTION_HOURS,
    V423_FIRST_MOVE_ATR,
    V423_FIRST_MOVE_WINDOW_HOURS,
)


def directional_followthrough(signal_price, atr_1h, future15):
    result = {}
    if future15 is None or future15.empty or atr_1h <= 0:
        return result

    price = float(signal_price)
    a1 = float(atr_1h)

    for hours in V423_DIRECTION_HOURS:
        view = future15.head(max(1, int(hours) * 4))
        if view.empty:
            continue
        close = float(view["close"].iloc[-1])
        low = float(view["low"].min())
        high = float(view["high"].max())

        result[f"dir_{hours}h_close_pct"] = round(
            (close / price - 1.0) * 100.0, 4
        )
        result[f"dir_{hours}h_close_atr"] = round(
            (price - close) / a1, 4
        )
        result[f"dir_{hours}h_mfe_atr"] = round(
            max(0.0, price - low) / a1, 4
        )
        result[f"dir_{hours}h_mae_atr"] = round(
            max(0.0, high - price) / a1, 4
        )
        result[f"dir_{hours}h_short"] = bool(close < price)

    threshold = float(V423_FIRST_MOVE_ATR) * a1
    first = "NONE"
    for _, row in future15.head(
        max(1, int(V423_FIRST_MOVE_WINDOW_HOURS) * 4)
    ).iterrows():
        good = float(row["low"]) <= price - threshold
        bad = float(row["high"]) >= price + threshold
        if good and bad:
            first = "AMBIGUOUS"
            break
        if good:
            first = "SHORT_0.5ATR_FIRST"
            break
        if bad:
            first = "ADVERSE_0.5ATR_FIRST"
            break

    result["dir_first_0_5atr_move"] = first
    short_votes = sum(
        1
        for hours in V423_DIRECTION_HOURS
        if result.get(f"dir_{hours}h_short") is True
    )
    result["dir_short_votes"] = short_votes

    if (
        first == "SHORT_0.5ATR_FIRST"
        and short_votes >= 2
        and float(result.get("dir_4h_close_atr") or 0.0) > 0.0
    ):
        label = "STRONG_SHORT_FOLLOWTHROUGH"
    elif short_votes >= 2:
        label = "SHORT_FOLLOWTHROUGH"
    elif first == "ADVERSE_0.5ATR_FIRST" and short_votes <= 1:
        label = "BOTTOM_OR_WRONG_TIMING"
    else:
        label = "MIXED"
    result["dir_label"] = label
    return result
