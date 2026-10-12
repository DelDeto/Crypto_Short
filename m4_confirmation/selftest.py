"""Offline, no-network tests of M4 H2 event timing, no reclaim and reanchored outcomes."""
import pandas as pd
from .engine import case_study,control_study,H

def fixture():
    index=pd.date_range("2026-08-01T00:00:00Z",periods=90,freq="h")
    close=[108.0]*90
    close[10]=108.0;close[11]=106.0;close[12]=104.0
    for i in range(13,90):close[i]=max(95,104.0-(i-12)*.08)
    op=[108.0]+close[:-1]
    op[10]=111.0
    high=[max(op[i],close[i])+.5 for i in range(90)]
    low=[min(op[i],close[i])-.5 for i in range(90)]
    high[10]=112.0;low[10]=105.0
    df=pd.DataFrame({"open":op,"high":high,"low":low,"close":close},index=index)
    t=index[11]
    event={"symbol":"TEST_USDT","signal_time_utc":t.isoformat(),
           "previous_48h_high":110.0,"reference_next_open":op[11],
           "short_24h_pct":-10.0}
    return df,event,index[-1]

def main():
    df,e,last=fixture()
    c=case_study(e,df,last)
    assert c["confirmation_status"]=="CONFIRMED",c
    assert c["confirmation_lag_hours"]==2,c
    assert c["confirmation_time_utc"]==df.index[13].isoformat()
    assert c["entry_reference_open"]==df.loc[df.index[13],"open"]
    assert c["short_24h_pct"]>0
    control=control_study("CTRL_USDT",e["signal_time_utc"],2,df,last)
    assert control["outcome_status"]=="OK"
    assert control["entry_reference_open"]==c["entry_reference_open"]
    assert control["short_24h_pct"]==c["short_24h_pct"]

    # After-confirmation future cannot influence past H2 decision.
    future=df.copy()
    future.loc[future.index[15]:,["close","high"]]=200.0
    after=case_study(e,future,last)
    assert after["confirmation_status"]=="CONFIRMED"
    assert after["confirmation_lag_hours"]==2
    assert after["short_24h_pct"]!=c["short_24h_pct"]

    # Reclaim before a subsequent breakdown invalidates confirmation.
    reclaim=df.copy();reclaim.loc[reclaim.index[11],"close"]=110.5
    assert case_study(e,reclaim,last)["confirmation_status"]=="RECLAIMED_BEFORE_CONFIRM"

    # No close < H1 sweep low within six bars => never confirmed.
    flat=df.copy()
    for i in range(11,17):flat.loc[flat.index[i],"close"]=106.0
    assert case_study(e,flat,last)["confirmation_status"]=="NO_CONFIRMATION_6H"

    tampered={**e,"reference_next_open":1.0}
    assert case_study(tampered,df,last)["confirmation_status"]=="SOURCE_PRICE_MISMATCH"

    early=df.index[45]
    assert case_study(e,df,early)["confirmation_status"]=="NOT_MATURED"
    print("M4 V0.2.2 selftest PASS: causal trigger, lower-low, reclaim rejection, no confirmation, future isolation, price tamper, maturity")
    return 0

if __name__=="__main__":raise SystemExit(main())
