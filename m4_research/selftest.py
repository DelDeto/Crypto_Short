"""Deterministic, no-network M4 tests; required before any market-data scan."""
from datetime import datetime,timezone
import numpy as np
import pandas as pd
from .market import _candle_frame
from .prepare import build_manifest
from .events import evaluate_frame,future_labels
from .merge import match_controls,_day_cluster_ci

def _sample(reversal=True):
    n=150
    ts=pd.date_range("2026-08-01",periods=n,freq="h",tz="UTC")
    close=np.full(n,100.0)
    for i in range(61,85):
        close[i]=100+10*(i-60)/24
    if reversal:
        close[84]=109.5
    for i in range(85,n):close[i]=max(95.0,108-(i-85)*0.13)
    opening=np.concatenate(([100.0],close[:-1]))
    opening[84]=111.0
    high=np.maximum(opening,close)+0.2
    low=np.minimum(opening,close)-0.2
    high[84]=113.0;low[84]=109.0
    amount=np.full(n,100000.0)
    frame=pd.DataFrame({"open":opening,"high":high,"low":low,"close":close,"volume":np.ones(n),"amount":amount},index=ts)
    return frame

def main():
    data={
        "time":[int(pd.Timestamp("2026-09-01T00:00:00Z").timestamp()),int(pd.Timestamp("2026-09-01T01:00:00Z").timestamp())],
        "open":[100,101],"high":[102,103],"low":[99,100],"close":[101,102],
        "vol":[1000,1100],"amount":[101000,112000],
    }
    f=_candle_frame(data)
    assert len(f)==2 and f["amount"].iloc[-1]==112000

    names=[f"COIN{i}_USDT" for i in range(12)]
    manifest=build_manifest(datetime(2026,10,12,5,tzinfo=timezone.utc),lambda:(names,{"catalogue_rows":12,"excluded":{}}))
    assert manifest["symbol_count"]==12
    assert manifest["research_only"] and manifest["no_live_short_signals"]

    frame=_sample()
    t=frame.index[84]+pd.Timedelta(hours=1)
    es,pool,audit=evaluate_frame(frame,"SAMPLE_USDT",t,t+pd.Timedelta(hours=1))
    assert len(es)==1,(es,audit)
    assert es[0]["signal_time_utc"]==t.isoformat()
    assert es[0]["return_24h_asof_pct"]>=8.0
    assert es[0]["upper_wick_ratio"]>=0.35
    assert es[0]["short_24h_pct"]>0
    assert es[0]["reference_next_open"]==frame["open"].iloc[85]

    # Alter ONLY post-signal candles: event & as-of features must remain identical.
    alt=frame.copy()
    for i in range(85,150):
        alt.iloc[i,alt.columns.get_loc("open")]=115.0
        alt.iloc[i,alt.columns.get_loc("close")]=116.0
        alt.iloc[i,alt.columns.get_loc("high")]=117.0
        alt.iloc[i,alt.columns.get_loc("low")]=114.0
    es2,_,_=evaluate_frame(alt,"SAMPLE_USDT",t,t+pd.Timedelta(hours=1))
    assert len(es2)==1
    for key in ("signal_time_utc","return_24h_asof_pct","upper_wick_ratio","sweep_depth_pct"):
        assert es[0][key]==es2[0][key],key
    assert es[0]["short_24h_pct"]!=es2[0]["short_24h_pct"]

    control={**pool[0]}
    control["symbol"]="CONTROL_USDT"
    control["raw_h1_event"]=False
    control["return_24h_asof_pct"]=es[0]["return_24h_asof_pct"]+1
    control["volatility_24h_asof_pct"]=es[0]["volatility_24h_asof_pct"]+1
    pairs,unmatched,_=match_controls(es,[control])
    assert len(pairs)==1 and not unmatched
    assert pairs[0]["control_symbols"]=="CONTROL_USDT"
    assert _day_cluster_ci(pairs)==[None,None]
    control["raw_h1_event"]=True
    pairs,unmatched,_=match_controls(es,[control])
    assert not pairs and len(unmatched)==1

    print("M4 offline selftest PASS: manifest, historical parsing, real-time-safe event selection, outcome isolation, matched controls")
    return 0

if __name__=="__main__":raise SystemExit(main())
