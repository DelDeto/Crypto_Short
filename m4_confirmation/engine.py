"""Time-causal confirmation/rebased short labels for already-frozen M4 H1 events.

Nothing from any future candle is consulted until AFTER H2 decision is fixed.
No orders, fees model, liquidity claims, signals or tuning.
"""
import math
import pandas as pd
from m4_research.events import future_labels
from .config import CONFIRM_WITHIN_HOURS

H=pd.Timedelta(hours=1)

def _ts(x):
    t=pd.Timestamp(x)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")

def _at(frame,ts):
    if ts not in frame.index:return None
    row=frame.loc[ts]
    if isinstance(row,pd.DataFrame):raise RuntimeError("Duplicate MEXC candle index")
    return row

def case_study(event,frame,last_closed_open):
    t=_ts(event["signal_time_utc"])
    closed=_ts(last_closed_open)
    result={"symbol":event["symbol"],"event_signal_utc":t.isoformat(),
            "source_short_24h_pct":float(event["short_24h_pct"]),
            "confirmation_status":None,"confirmation_lag_hours":None,
            "confirmation_time_utc":None}
    if frame is None or frame.empty:
        return {**result,"confirmation_status":"DATA_MISSING"}
    frame=frame.sort_index()
    trigger=_at(frame,t-H)
    next_bar=_at(frame,t)
    if trigger is None or next_bar is None:
        return {**result,"confirmation_status":"DATA_MISSING"}
    old_high=float(event["previous_48h_high"])
    low=float(trigger["low"])
    original_next_open=float(event["reference_next_open"])
    # Do not silently accept a changed source candle; retain and disclose attrition.
    if not math.isclose(float(next_bar["open"]),original_next_open,rel_tol=0.0001,abs_tol=1e-12):
        return {**result,"confirmation_status":"SOURCE_PRICE_MISMATCH"}
    if not math.isfinite(old_high) or old_high<=0 or low<=0:
        return {**result,"confirmation_status":"DATA_INVALID"}
    for lag in range(1,CONFIRM_WITHIN_HOURS+1):
        candle_open=t+(lag-1)*H
        if candle_open>closed:
            return {**result,"confirmation_status":"NOT_MATURED"}
        bar=_at(frame,candle_open)
        if bar is None:return {**result,"confirmation_status":"DATA_GAP"}
        c=float(bar["close"])
        if c>=old_high:
            return {**result,"confirmation_status":"RECLAIMED_BEFORE_CONFIRM"}
        if c<low:
            # First confirmation is fixed by present/past 1h closes.
            confirmation_close=t+lag*H
            entry_bar=_at(frame,confirmation_close)
            if entry_bar is None:
                status="NOT_MATURED" if confirmation_close>closed else "DATA_GAP"
                return {**result,"confirmation_status":status,
                        "confirmation_lag_hours":lag,
                        "confirmation_time_utc":confirmation_close.isoformat()}
            outcome_end_open=candle_open+48*H
            if outcome_end_open>closed:
                status="NOT_MATURED"
                return {**result,"confirmation_status":status,
                        "confirmation_lag_hours":lag,
                        "confirmation_time_utc":confirmation_close.isoformat()}
            i=frame.index.get_loc(candle_open)
            labels=future_labels(frame,i)
            if labels is None:
                return {**result,"confirmation_status":"DATA_GAP",
                        "confirmation_lag_hours":lag,
                        "confirmation_time_utc":confirmation_close.isoformat()}
            return {**result,"confirmation_status":"CONFIRMED",
                    "confirmation_lag_hours":lag,
                    "confirmation_time_utc":confirmation_close.isoformat(),
                    "sweep_low":low,"old_high":old_high,
                    "entry_reference_open":labels["reference_next_open"],
                    **{k:v for k,v in labels.items() if k!="reference_next_open"}}
    return {**result,"confirmation_status":"NO_CONFIRMATION_6H"}

def control_study(symbol,event_time,lag,frame,last_closed_open):
    """Control selection is pre-frozen at original H1 timestamp; align outcomes
    to that case's ACTUAL confirmation time, without matching on outcomes."""
    t=_ts(event_time);closed=_ts(last_closed_open)
    trigger_open=t+(int(lag)-1)*H
    base={"symbol":symbol,"event_signal_utc":t.isoformat(),
          "lag_hours":int(lag),"entry_time_utc":(trigger_open+H).isoformat()}
    if frame is None or frame.empty:return {**base,"outcome_status":"DATA_MISSING"}
    if trigger_open+48*H>closed:
        return {**base,"outcome_status":"NOT_MATURED"}
    if trigger_open not in frame.index:
        return {**base,"outcome_status":"DATA_GAP"}
    i=frame.index.get_loc(trigger_open)
    label=future_labels(frame,i)
    if label is None:return {**base,"outcome_status":"DATA_GAP"}
    return {**base,"outcome_status":"OK","entry_reference_open":label["reference_next_open"],
            **{k:v for k,v in label.items() if k!="reference_next_open"}}
