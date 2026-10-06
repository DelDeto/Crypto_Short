"""V4.2.9 future diagnostics for confirmed Short entries."""

from .v428_diagnostics import future_labels_v428
from .v429_config import V429_FOLLOWTHROUGH_R, V429_POST_SL_HOURS


def _confirmed_path(features, future15):
    out = {
        "ft_first_0_5r_move": None,
        "ft_close_r_1h": None,
        "ft_close_r_4h": None,
        "ft_close_r_12h": None,
        "ft_close_r_24h": None,
        "ft_mfe_r_4h": None,
        "ft_mae_r_4h": None,
        "ft_mfe_r_24h": None,
        "ft_mae_r_24h": None,
        "post_sl_class": None,
        "post_sl_reclaim_entry": None,
        "post_sl_plus_1r": None,
        "post_sl_plus_2r": None,
        "post_sl_mfe_r": None,
        "post_sl_additional_adverse_r": None,
    }
    if not bool(features.get("v428_entry_confirmed")):
        return out

    entry = features.get("v428_confirm_entry_reference")
    stop = features.get("v428_confirm_stop_reference")
    if entry is None or stop is None:
        return out
    entry = float(entry)
    stop = float(stop)
    risk = stop - entry
    if risk <= 0:
        return out

    bars24 = future15.head(24 * 4)
    for hours in (1, 4, 12, 24):
        block = bars24.head(hours * 4)
        if len(block) >= hours * 4:
            close = float(block["close"].iloc[-1])
            out[f"ft_close_r_{hours}h"] = round((entry - close) / risk, 4)

    block4 = bars24.head(4 * 4)
    if not block4.empty:
        out["ft_mfe_r_4h"] = round(
            max(0.0, (entry - float(block4["low"].min())) / risk), 4
        )
        out["ft_mae_r_4h"] = round(
            max(0.0, (float(block4["high"].max()) - entry) / risk), 4
        )
    if not bars24.empty:
        out["ft_mfe_r_24h"] = round(
            max(0.0, (entry - float(bars24["low"].min())) / risk), 4
        )
        out["ft_mae_r_24h"] = round(
            max(0.0, (float(bars24["high"].max()) - entry) / risk), 4
        )

    trigger = float(V429_FOLLOWTHROUGH_R)
    fav = entry - trigger * risk
    adv = entry + trigger * risk
    first = "NONE"
    for _, bar in block4.iterrows():
        hit_fav = float(bar["low"]) <= fav
        hit_adv = float(bar["high"]) >= adv
        if hit_fav and hit_adv:
            first = "AMBIGUOUS"
            break
        if hit_fav:
            first = "SHORT_0.5R_FIRST"
            break
        if hit_adv:
            first = "ADVERSE_0.5R_FIRST"
            break
    out["ft_first_0_5r_move"] = first

    loss_outcomes = {"SL_FIRST", "SL_SAME_BAR"}
    # The base label is added later, so independently locate a stop in first 24h.
    stop_pos = None
    for pos, (_, bar) in enumerate(bars24.iterrows()):
        if float(bar["high"]) >= stop:
            stop_pos = pos
            break
    if stop_pos is None:
        return out

    after = future15.iloc[stop_pos + 1 : stop_pos + 1 + int(V429_POST_SL_HOURS) * 4]
    if after.empty:
        return out

    reclaim = bool((after["low"].astype(float) <= entry).any())
    plus1 = bool((after["low"].astype(float) <= entry - risk).any())
    plus2 = bool((after["low"].astype(float) <= entry - 2.0 * risk).any())
    out["post_sl_reclaim_entry"] = reclaim
    out["post_sl_plus_1r"] = plus1
    out["post_sl_plus_2r"] = plus2
    out["post_sl_mfe_r"] = round(
        max(0.0, (entry - float(after["low"].min())) / risk), 4
    )
    out["post_sl_additional_adverse_r"] = round(
        max(0.0, (float(after["high"].max()) - stop) / risk), 4
    )

    if plus2:
        out["post_sl_class"] = "FALSE_STOP_THEN_TP2R"
    elif plus1:
        out["post_sl_class"] = "FALSE_STOP_THEN_1R"
    elif reclaim:
        out["post_sl_class"] = "STOP_THEN_RECLAIM_ENTRY"
    else:
        out["post_sl_class"] = "VALID_STOP_CONTINUED_WRONG"
    return out


def future_labels_v429(
    features, signal_time, future15,
    btc_start, eth_start, btc_future, eth_future,
):
    path = future_labels_v428(
        features, signal_time, future15,
        btc_start, eth_start, btc_future, eth_future,
    )
    extra = _confirmed_path(features, future15)
    # Post-SL diagnostics only make sense when the 24h outcome is a stop.
    if path.get("confirmed_trade_outcome") not in {"SL_FIRST", "SL_SAME_BAR"}:
        for key in (
            "post_sl_class", "post_sl_reclaim_entry", "post_sl_plus_1r",
            "post_sl_plus_2r", "post_sl_mfe_r",
            "post_sl_additional_adverse_r",
        ):
            extra[key] = None
    path.update(extra)
    return path
