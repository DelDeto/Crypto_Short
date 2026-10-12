"""H3 features at the fully closed 1h bar, with zero future access."""
import math
import numpy as np
import pandas as pd
from .protocol import (
 PRIOR_18H_MIN_PCT,LAST_6H_MAX_PCT,RELATIVE_LAST_6H_MAX_PP,
 ASOF_24H_MIN_TURNOVER_USDT,ASOF_CANDLES,
)
H=pd.Timedelta(hours=1)
def read_features(symbol,frame,btc,closed_open):
    closed_open=pd.Timestamp(closed_open)
    if closed_open.tzinfo is None:closed_open=closed_open.tz_localize("UTC")
    frame=frame.loc[frame.index<=closed_open].sort_index()
    btc=btc.loc[btc.index<=closed_open].sort_index()
    if closed_open not in frame.index or closed_open not in btc.index:
        return None,"MISSING_SIGNAL_BAR"
    t=[closed_open-H*i for i in range(24,-1,-1)]
    if any(z not in frame.index or z not in btc.index for z in t):
        return None,"GAP_OR_TOO_YOUNG"
    f=frame.loc[t];b=btc.loc[t]
    try:
        closes=f["close"].to_numpy(dtype=float)
        btc_closes=b["close"].to_numpy(dtype=float)
        amounts=f["amount"].to_numpy(dtype=float)
        if np.any(~np.isfinite(closes)) or np.any(closes<=0) or np.any(~np.isfinite(btc_closes)) or np.any(btc_closes<=0):
            return None,"BAD_PRICES"
        if np.any(~np.isfinite(amounts[-24:])) or np.any(amounts[-24:]<0):
            return None,"MISSING_ASOF_TURNOVER"
        prior18=100*(closes[-7]/closes[0]-1)
        last6=100*(closes[-1]/closes[-7]-1)
        last6btc=100*(btc_closes[-1]/btc_closes[-7]-1)
        ret24=100*(closes[-1]/closes[0]-1)
        rel=last6-last6btc
        vol=float(np.std(np.diff(np.log(closes)),ddof=0)*math.sqrt(24)*100)
        turnover=float(amounts[-24:].sum())
        if not all(math.isfinite(x) for x in (prior18,last6,last6btc,ret24,rel,vol,turnover)):
            return None,"BAD_ASOF_FEATURES"
    except (ValueError,IndexError,KeyError):
        return None,"MISSING_ASOF_FIELDS"
    structural=prior18>=PRIOR_18H_MIN_PCT
    liquid=turnover>=ASOF_24H_MIN_TURNOVER_USDT
    h3=(structural and liquid and last6<=LAST_6H_MAX_PCT and rel<=RELATIVE_LAST_6H_MAX_PP)
    return {
        "symbol":symbol,"signal_time_utc":(closed_open+H).isoformat(),
        "prior18_pct":round(prior18,6),"last6_pct":round(last6,6),
        "btc_last6_pct":round(last6btc,6),"relative6_pp":round(rel,6),
        "return24_pct":round(ret24,6),"volatility24_pct":round(vol,6),
        "asof_quote_turnover24_usdt":round(turnover,2),
        "comparison_eligible":bool(structural and liquid),
        "h3_event":bool(h3),
    },None

def match_asof(events,features):
    """Controls fixed now, not selected from any future price or outcome."""
    pool=[f for f in features if f["comparison_eligible"] and not f["h3_event"]]
    result=[]
    for e in events:
        matches=[]
        for c in pool:
            if c["symbol"]==e["symbol"]:continue
            # Calipers use ONLY information already captured at decision time.
            if abs(float(c["prior18_pct"])-float(e["prior18_pct"]))>12:continue
            if abs(float(c["volatility24_pct"])-float(e["volatility24_pct"]))>12:continue
            t1=float(c["asof_quote_turnover24_usdt"]);t2=float(e["asof_quote_turnover24_usdt"])
            if t1<=0 or t2<=0:continue
            dist=(abs(c["prior18_pct"]-e["prior18_pct"])/6
                  +abs(c["volatility24_pct"]-e["volatility24_pct"])/6
                  +.35*abs(math.log(t1/t2)))
            matches.append((dist,c["symbol"]))
        matches.sort()
        result.append({**e,"control_symbols":[x[1] for x in matches[:3]],
                       "control_count":min(3,len(matches))})
    return result
