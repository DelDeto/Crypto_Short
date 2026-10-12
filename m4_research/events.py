"""M4 V0.2 fixed H1 event definition and point-in-time, non-trading labels.

All predictors are computed using bars up through the CLOSE of bar i.
Outcomes use the OPEN of bar i+1 and subsequent closed bars; none of those
values are used to select events or matched controls.
"""
import math
import numpy as np
import pandas as pd
from .config import (
    RUNUP_24H_MIN_PCT,SWEEP_MIN_PCT,WICK_MIN_RATIO,REQUIRE_BEARISH_CLOSE,
    PREVIOUS_HIGH_HOURS,MIN_ASOF_QUOTE_TURNOVER_24H,
    SAME_SYMBOL_COOLDOWN_HOURS,HORIZONS_HOURS,
)

def _finite(x):
    return x is not None and math.isfinite(float(x))

def _contiguous(frame,i,back=48,forward=48):
    if i-back<0 or i+forward>=len(frame):return False
    return (frame.index[i]-frame.index[i-back]==pd.Timedelta(hours=back)
            and frame.index[i+forward]-frame.index[i]==pd.Timedelta(hours=forward))

def future_labels(frame,i,horizons=HORIZONS_HOURS):
    """Short % from next bar OPEN to future close; MFE/MAE are *outcomes*, never predictors."""
    if i+1>=len(frame) or frame.index[i+1]-frame.index[i]!=pd.Timedelta(hours=1):
        return None
    entry=float(frame["open"].iloc[i+1])
    if not _finite(entry) or entry<=0:return None
    out={"reference_next_open":entry}
    for h in horizons:
        j=i+h
        if j>=len(frame) or frame.index[j]-frame.index[i]!=pd.Timedelta(hours=h):
            return None
        block=frame.iloc[i+1:j+1]
        if len(block)!=h:return None
        future_close=float(frame["close"].iloc[j])
        low=float(block["low"].min()); high=float(block["high"].max())
        out[f"short_{h}h_pct"]=round((entry-future_close)/entry*100,6)
        out[f"mfe_{h}h_pct"]=round((entry-low)/entry*100,6)
        out[f"mae_{h}h_pct"]=round((high-entry)/entry*100,6)
    return out

def evaluate_frame(frame,symbol,signal_start,signal_end):
    """Returns (events, control_pool, audit), never a short recommendation."""
    horizon=max(HORIZONS_HOURS);warm=max(PREVIOUS_HIGH_HOURS,24)
    if frame is None or len(frame)<warm+horizon+1:
        return [],[],{"eligible_points":0,"drop_missing_amount":0,"drop_gaps":0,"events":0,"control_pool":0}
    frame=frame.sort_index()
    start=pd.Timestamp(signal_start); end=pd.Timestamp(signal_end)
    if start.tzinfo is None:start=start.tz_localize("UTC")
    if end.tzinfo is None:end.tz_localize("UTC")
    close=frame["close"].to_numpy(dtype=float)
    high=frame["high"].to_numpy(dtype=float)
    low=frame["low"].to_numpy(dtype=float)
    op=frame["open"].to_numpy(dtype=float)
    amount=frame["amount"].to_numpy(dtype=float)
    audit={"eligible_points":0,"drop_missing_amount":0,"drop_gaps":0,"events":0,"control_pool":0}
    events=[];pool=[];last_event_idx=None
    for i in range(warm,len(frame)-horizon):
        signal_time=frame.index[i]+pd.Timedelta(hours=1)
        if signal_time<start or signal_time>=end:continue
        if not _contiguous(frame,i,warm,horizon):
            audit["drop_gaps"]+=1;continue
        prev_high=float(np.max(high[i-PREVIOUS_HIGH_HOURS:i]))
        if prev_high<=0:continue
        ret24=(close[i]/close[i-24]-1)*100
        if not math.isfinite(ret24) or ret24<RUNUP_24H_MIN_PCT:continue
        turnover=float(np.sum(amount[i-23:i+1]))
        if not math.isfinite(turnover) or turnover<MIN_ASOF_QUOTE_TURNOVER_24H:
            audit["drop_missing_amount"]+=1;continue

        candle_range=max(high[i]-low[i],1e-12)
        wick=(high[i]-max(op[i],close[i]))/candle_range
        sweep=(high[i]/prev_high-1)*100
        returns=np.diff(np.log(close[i-24:i+1]))
        vol24=float(np.std(returns,ddof=0)*math.sqrt(24)*100)
        if not math.isfinite(vol24):continue

        raw_event=(sweep>=SWEEP_MIN_PCT and close[i]<prev_high and wick>=WICK_MIN_RATIO
                   and (not REQUIRE_BEARISH_CLOSE or close[i]<op[i]))
        future=future_labels(frame,i)
        if future is None:continue
        audit["eligible_points"]+=1
        basic={
            "symbol":symbol,
            "signal_time_utc":signal_time.isoformat(),
            "return_24h_asof_pct":round(float(ret24),6),
            "volatility_24h_asof_pct":round(vol24,6),
            "quote_turnover_24h_asof":round(turnover,2),
            "raw_h1_event":bool(raw_event),
        }
        pool.append({**basic,**future})
        if raw_event and (last_event_idx is None or i-last_event_idx>=SAME_SYMBOL_COOLDOWN_HOURS):
            events.append({
                **basic,"event_bar_open_utc":frame.index[i].isoformat(),
                "previous_48h_high":round(prev_high,10),
                "sweep_depth_pct":round(sweep,6),
                "upper_wick_ratio":round(wick,6),
                **future,
            })
            last_event_idx=i
    audit["events"]=len(events);audit["control_pool"]=len(pool)
    return events,pool,audit
