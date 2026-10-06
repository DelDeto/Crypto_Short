"""V4.2.8 future labels, including confirmed-entry 2R outcome."""

from .v425_diagnostics import future_path_24h


def _confirmed_2r_outcome(features,future15):
    out={
        "y_confirmed_2r_success":None,
        "confirmed_trade_outcome":"NO_CONFIRMATION",
    }
    if not bool(features.get("v428_entry_confirmed")):
        return out

    entry=features.get("v428_confirm_entry_reference")
    stop=features.get("v428_confirm_stop_reference")
    tp=features.get("v428_confirm_tp2r_reference")
    if any(v is None for v in (entry,stop,tp)):
        out["confirmed_trade_outcome"]="INVALID_PLAN"
        out["y_confirmed_2r_success"]=False
        return out

    entry=float(entry); stop=float(stop); tp=float(tp)
    if stop<=entry or tp>=entry:
        out["confirmed_trade_outcome"]="INVALID_PLAN"
        out["y_confirmed_2r_success"]=False
        return out

    for _,bar in future15.head(24*4).iterrows():
        hit_sl=float(bar["high"])>=stop
        hit_tp=float(bar["low"])<=tp
        if hit_sl and hit_tp:
            out["confirmed_trade_outcome"]="SL_SAME_BAR"
            out["y_confirmed_2r_success"]=False
            return out
        if hit_sl:
            out["confirmed_trade_outcome"]="SL_FIRST"
            out["y_confirmed_2r_success"]=False
            return out
        if hit_tp:
            out["confirmed_trade_outcome"]="TP2R_FIRST"
            out["y_confirmed_2r_success"]=True
            return out

    out["confirmed_trade_outcome"]="UNRESOLVED_24H"
    out["y_confirmed_2r_success"]=False
    return out


def future_labels_v428(
    features,signal_time,future15,
    btc_start,eth_start,btc_future,eth_future,
):
    path=future_path_24h(
        features["current_price"],features["atr_1h"],signal_time,future15,
        btc_start=btc_start,eth_start=eth_start,
        btc_future=btc_future,eth_future=eth_future,
    )
    y4=path.get("y_4h_lower")
    y12=path.get("y_12h_lower")
    y24=path.get("y_24h_lower")
    path["y_persistent_short"]=(
        None if any(v is None for v in (y4,y12,y24))
        else bool(y4 and y12 and y24)
    )

    block_keys=[
        "block_0_4h_short","block_4_8h_short","block_8_12h_short",
        "block_12_16h_short","block_16_20h_short","block_20_24h_short",
    ]
    vals=[path.get(k) for k in block_keys if path.get(k) is not None]
    path["trend_stable_block_count"]=sum(bool(v) for v in vals)
    path["y_trend_stable"]=(
        None if len(vals)<6
        else bool(sum(bool(v) for v in vals)>=4 and bool(y24))
    )

    max_downside=float(path.get("max_downside_24h_atr") or 0.0)
    reclaimed=bool(path.get("reclaimed_signal_after_mfe"))
    path["y_reversal_after_short"]=bool(
        max_downside>=0.5 and reclaimed
    )
    path.update(_confirmed_2r_outcome(features,future15))
    return path
