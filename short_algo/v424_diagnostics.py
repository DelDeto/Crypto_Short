"""Future-only labels and diagnostics for V4.2.4 research replay."""

from .v424_config import (
    V424_FIRST_MOVE_ATR,
    V424_FIRST_MOVE_WINDOW_HOURS,
)


def future_direction_labels(signal_price, atr_1h, future15):
    result = {
        "y_4h_lower": None,
        "y_12h_lower": None,
        "y_first_short": None,
        "dir_first_0_5atr_move": "NONE",
    }
    if future15 is None or future15.empty or atr_1h <= 0:
        return result

    price = float(signal_price)
    a1 = float(atr_1h)

    for hours in (1, 4, 12):
        view = future15.head(max(1, hours * 4))
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

    result["y_4h_lower"] = result.get("dir_4h_short")
    result["y_12h_lower"] = result.get("dir_12h_short")

    threshold = float(V424_FIRST_MOVE_ATR) * a1
    first = "NONE"
    for _, row in future15.head(
        max(1, int(V424_FIRST_MOVE_WINDOW_HOURS) * 4)
    ).iterrows():
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

    short_votes = sum(
        1 for h in (1, 4, 12)
        if result.get(f"dir_{h}h_short") is True
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
