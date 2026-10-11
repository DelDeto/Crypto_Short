"""M3 V3.9 — frozen RW24 setup, entry-price ladder, stop survivability.

Research only. The directional setup is frozen at RW24 <= -5%. Three
predeclared sell-limit entry prices are compared without changing setup logic.
"""
import pandas as pd

from .m3_v2_execution import _find_displacement_retest
from .m3_v37_execution import evaluate_m3_v37
from .m3_v39_config import (
    M3_V39_ENTRY_OFFSETS_ATR15,
    M3_V39_FILL_BARS,
    M3_V39_STOP_CAPS_PCT,
)


STEP=pd.Timedelta(minutes=15)


def _fill_limit(fifteen,seq,price):
    frame=fifteen.sort_index()
    first_i=int(seq["entry_idx"])
    last_i=min(len(frame)-1,first_i+int(M3_V39_FILL_BARS)-1)
    for i in range(first_i,last_i+1):
        row=frame.iloc[i]
        o=float(row["open"])
        h=float(row["high"])
        if o>=float(price):
            return {"state":"FILLED","entry":float(price),"entry_idx":i,"entry_time":frame.index[i],"wait_bars":i-first_i,"fill_at_open_or_better":1}
        if h>=float(price):
            return {"state":"FILLED","entry":float(price),"entry_idx":i,"entry_time":frame.index[i],"wait_bars":i-first_i,"fill_at_open_or_better":0}
    return {"state":"NO_FILL"}


def _path_outcome(fifteen,entry_idx,entry):
    frame=fifteen.sort_index()
    rows=frame.iloc[int(entry_idx):]
    if rows.empty:
        return {}

    start=rows.index[0]
    rows=rows.loc[rows.index < start+pd.Timedelta(hours=24)]
    if rows.empty:
        return {}

    entry=float(entry)
    target=entry*0.97
    caps=tuple(float(x) for x in M3_V39_STOP_CAPS_PCT)
    first_stop={cap:None for cap in caps}
    target_time=None
    max_adverse=0.0
    max_adverse_before_target=0.0
    max_favorable=0.0

    for n,(t,row) in enumerate(rows.iterrows()):
        h=float(row["high"])
        l=float(row["low"])
        adv=max(0.0,(h-entry)/entry*100.0)
        fav=max(0.0,(entry-l)/entry*100.0)
        max_adverse=max(max_adverse,adv)
        max_favorable=max(max_favorable,fav)

        for cap in caps:
            if first_stop[cap] is None and adv>=cap:
                first_stop[cap]=pd.Timestamp(t)+STEP

        if target_time is None:
            max_adverse_before_target=max(max_adverse_before_target,adv)
            # Conservative: do not credit a target printed in the fill bar;
            # its low may have occurred before the sell-limit fill.
            if n>0 and l<=target:
                target_time=pd.Timestamp(t)+STEP
                break

    reached=target_time is not None
    minutes=int((target_time-start).total_seconds()//60) if reached else None

    out={
        "target_3pct":round(target,10),
        "hit_3pct_24h":int(reached),
        "minutes_to_3pct":minutes,
        "pre3pct_mae_pct":round(max_adverse_before_target,5),
        "max_favorable_pct_24h":round(max_favorable,5),
        "max_adverse_pct_24h":round(max_adverse,5),
    }
    for cap in caps:
        label=str(cap).replace(".","_")
        stop_time=first_stop[cap]
        out[f"target_before_stop_{label}pct"]=int(
            reached and (stop_time is None or target_time<stop_time)
        )
    return out


def evaluate_m3_v39(one_closed,four_closed,fifteen,signal_time,btc_closed=None,eth_closed=None):
    base=evaluate_m3_v37(one_closed,four_closed,fifteen,signal_time,btc_closed,eth_closed)
    out={"m3v39_state":"NO_SETUP"}

    # Copy context/setup diagnostics for auditability.
    for key,value in base.items():
        if key.startswith("m3v37_"):
            out[key.replace("m3v37_","m3v39_",1)]=value
        else:
            out[key]=value

    if out.get("m3v39_state")!="BASELINE_CANDIDATE":
        return out
    if int(out.get("m3v39_candidate_a_rw24_le_m5") or 0)!=1:
        out["m3v39_state"]="FAIL_RW24_FROZEN_GATE"
        return out

    seq=_find_displacement_retest(fifteen,signal_time)
    if seq.get("state")!="RETEST_ENTRY":
        out["m3v39_state"]="NO_RETEST"
        return out

    poi=float(seq["break_level"])
    atr15=float(seq["atr15"])
    out["m3v39_state"]="RW24_ENTRY_STUDY"
    out["m3v39_poi"]=round(poi,10)
    out["m3v39_atr15"]=round(atr15,10)

    variants={}
    for name,offset in M3_V39_ENTRY_OFFSETS_ATR15.items():
        price=poi+float(offset)*atr15
        fill=_fill_limit(fifteen,seq,price)
        item={
            "name":name,
            "offset_atr15":float(offset),
            "limit_price":round(price,10),
            "fill_state":fill.get("state"),
        }
        if fill.get("state")=="FILLED":
            item.update({
                "entry":round(float(fill["entry"]),10),
                "entry_time":pd.Timestamp(fill["entry_time"]).isoformat(),
                "entry_idx":int(fill["entry_idx"]),
                "wait_bars":int(fill["wait_bars"]),
                "fill_at_open_or_better":int(fill.get("fill_at_open_or_better") or 0),
            })
            item.update(_path_outcome(fifteen,int(fill["entry_idx"]),float(fill["entry"])))
        variants[name]=item

    out["m3v39_variants"]=variants
    return out
