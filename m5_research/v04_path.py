"""M5 V0.4 causal next-bar-open proxy and conservative OHLC path mechanics.

Never calls an exchange or submits an order. Full 15m HIGH/LOW allows true
historical-path MFE/MAE (within OHLC limits); no intrabar path, spreads,
funding, actual fills or order-book liquidity information is available.
"""
import math
import statistics

import numpy as np
import pandas as pd

from .data import STEP, _utc

HORIZONS = (1, 2, 4, 8)
SL_TP = ((1.0, 2.0), (1.5, 3.0), (2.0, 4.0))
COST_BPS = (20, 40)
MAX_ANCHOR_PRICE_REVISION_PCT = 0.25

def _checked_bars(raw):
    if raw is None or raw.empty:
        return None
    if raw.index.tz is None:
        raise ValueError("OHLC candle index must be UTC-aware")
    frame = raw.sort_index()
    if frame.index.duplicated().any():
        raise RuntimeError("Non-unique OHLC bars: do not silently resolve")
    for col in ("open", "high", "low", "close"):
        if col not in frame.columns or frame[col].isna().any():
            return None
        if not np.isfinite(frame[col].to_numpy(dtype=float)).all():
            return None
    if ((frame[["open","high","low","close"]] <= 0).any().any() or
        (frame["high"] < frame[["open","close","low"]].max(axis=1)).any() or
        (frame["low"] > frame[["open","close","high"]].min(axis=1)).any()):
        raise RuntimeError("Invalid OHLC order")
    return frame

def _bars_for_event(raw, bar_open, horizon_hours=8):
    """Event at closed bar T; candidate entry ONLY at T+15m OPEN."""
    f = _checked_bars(raw)
    if f is None:
        return None, "BAD_OR_EMPTY_OHLC"
    t = _utc(bar_open)
    expected = pd.date_range(start=t, periods=1+horizon_hours*4, freq="15min", tz="UTC")
    # t is the closed SIGNAL bar, plus 32 future open-time bars.
    if not expected.isin(f.index).all():
        return None, "MISSING_15M_BAR_IN_8H_PATH"
    ordered = f.loc[expected]
    return ordered, None

def _stop_tp(path, entry, sl_pct, tp_pct):
    """Conservative short exit, if SL and TP touch one 15m bar SL wins.

    Gaps above a stop exit at the worse next bar OPEN, whereas favorable
    gaps beyond TP receive only the stated TP (conservative). No spread.
    """
    stop = entry*(1+sl_pct/100)
    target = entry*(1-tp_pct/100)
    for i, (_, bar) in enumerate(path.iterrows()):
        op=float(bar["open"])
        hit_sl=float(bar["high"])>=stop
        hit_tp=float(bar["low"])<=target
        if op >= stop:
            return {"reason":"GAP_STOP", "exit":op, "bar_index":i}
        if hit_sl:
            return {"reason":"SL_FIRST_SAME_BAR" if hit_tp else "SL",
                    "exit":stop,"bar_index":i}
        if hit_tp:
            return {"reason":"TP", "exit":target,"bar_index":i}
    return {"reason":"HORIZON_CLOSE", "exit":float(path.iloc[-1]["close"]),
            "bar_index":len(path)-1}

def research_path(symbol, event_bar_open, raw_ohlc, *, anchor_close=None):
    """Return full-path metrics per horizon for one symbol at one as-of event.

    Entry proxy is exactly the OPEN of the first subsequent 15m bar.
    There is no assumed chance to trade at the already-known event CLOSE.
    """
    bars, reason = _bars_for_event(raw_ohlc, event_bar_open)
    if reason:
        return None, reason
    observed_anchor = float(bars.iloc[0]["close"])
    if anchor_close is not None:
        baseline = float(anchor_close)
        if baseline <= 0 or not math.isfinite(baseline):
            return None, "INVALID_ASOF_EVENT_CLOSE"
        drift = abs(observed_anchor/baseline - 1)*100
        if drift > MAX_ANCHOR_PRICE_REVISION_PCT:
            return None, "EXCHANGE_REVISED_EVENT_CLOSE"
    future = bars.iloc[1:].copy()
    entry = float(future.iloc[0]["open"])
    if entry <= 0 or not math.isfinite(entry):
        return None, "INVALID_NEXT_BAR_OPEN"
    outputs = {}
    for hours in HORIZONS:
        path = future.iloc[:hours*4]
        minlow = float(path["low"].min())
        maxhigh = float(path["high"].max())
        exit_close = float(path.iloc[-1]["close"])
        gross = (entry-exit_close)/entry*100
        mfe = (entry-minlow)/entry*100
        mae = (maxhigh-entry)/entry*100
        outcomes = {}
        for sl, tp in SL_TP:
            result = _stop_tp(path, entry, sl, tp)
            gross_strategy = (entry-result["exit"])/entry*100
            name=f"sl{sl:g}_tp{tp:g}"
            outcomes[name] = {
                "exit_reason":result["reason"],
                "exit_bar_index":result["bar_index"],
                "gross_pct":round(gross_strategy,6),
                "stress_20bps_pct":round(gross_strategy-0.2,6),
                "stress_40bps_pct":round(gross_strategy-0.4,6),
            }
        outputs[f"{hours}h"] = {
            "close_only_gross_pct":round(gross,6),
            "close_minus_20bps_pct":round(gross-0.2,6),
            "close_minus_40bps_pct":round(gross-0.4,6),
            "mfe_pct":round(mfe,6),
            "mae_pct":round(mae,6),
            "path_sl_tp":outcomes,
        }
    return {
        "symbol":symbol,
        "entry_proxy_time_utc":(_utc(event_bar_open)+STEP).isoformat(),
        "event_bar_close":round(observed_anchor,12),
        "entry_proxy_next_bar_open":round(entry,12),
        "entry_open_gap_vs_signal_close_pct":round((entry/observed_anchor-1)*100,6),
        "hours":outputs,
        "real_trade":False,
        "intrabar_sequence_known":False,
    },None

def distribution(values):
    xs=[float(x) for x in values if x is not None and math.isfinite(float(x))]
    if not xs:
        return {"n":0,"mean":None,"median":None,"min":None,"max":None}
    return {"n":len(xs),"mean":round(statistics.fmean(xs),6),
            "median":round(statistics.median(xs),6),
            "min":round(min(xs),6),"max":round(max(xs),6)}
