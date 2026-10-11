"""M3 V4.0 — structural stop and 2R/3R path study.

Frozen setup: RW24 <= -5%.
Frozen entry: sell limit at POI + 0.25 ATR15.
This run studies only stop placement and R outcomes.
"""
import pandas as pd

from .m3_v2_execution import _find_displacement_retest
from .m3_v37_execution import evaluate_m3_v37
from .m3_v39_execution import _fill_limit
from .m3_v40_config import (
    M3_V40_ENTRY_OFFSET_ATR15, M3_V40_FILL_BARS,
    M3_V40_STOP_BUFFERS_ATR15, M3_V40_TARGET_R,
)


STEP=pd.Timedelta(minutes=15)


def _r_path(fifteen, entry_idx, entry, stop, target_r):
    frame=fifteen.sort_index()
    rows=frame.iloc[int(entry_idx):]
    if rows.empty:
        return {}
    start=rows.index[0]
    rows=rows.loc[rows.index < start+pd.Timedelta(hours=24)]
    if rows.empty:
        return {}

    entry=float(entry); stop=float(stop); risk=stop-entry
    if risk<=0:
        return {"valid":0}

    target=entry-float(target_r)*risk
    outcome="UNRESOLVED"
    resolved_r=None
    hit_time=None
    max_adverse_r=0.0
    max_favorable_r=0.0

    for n,(t,row) in enumerate(rows.iterrows()):
        h=float(row["high"]); l=float(row["low"])
        max_adverse_r=max(max_adverse_r,max(0.0,(h-entry)/risk))
        max_favorable_r=max(max_favorable_r,max(0.0,(entry-l)/risk))

        stop_hit=h>=stop
        target_hit=(n>0 and l<=target)  # no target credit inside fill bar
        if stop_hit and target_hit:
            outcome="STOP_FIRST_CONSERVATIVE"; resolved_r=-1.0; hit_time=pd.Timestamp(t)+STEP; break
        if stop_hit:
            outcome="STOP"; resolved_r=-1.0; hit_time=pd.Timestamp(t)+STEP; break
        if target_hit:
            outcome="TARGET"; resolved_r=float(target_r); hit_time=pd.Timestamp(t)+STEP; break

    if resolved_r is None:
        last_close=float(rows.iloc[-1]["close"])
        mtm=(entry-last_close)/risk
        mtm=max(-1.0,min(float(target_r),mtm))
        resolved_r=mtm

    return {
        "valid":1,
        "stop":round(stop,10),
        "risk_pct":round(risk/entry*100.0,5),
        "target":round(target,10),
        "target_r":float(target_r),
        "outcome":outcome,
        "target_hit":int(outcome=="TARGET"),
        "stop_hit":int(outcome in ("STOP","STOP_FIRST_CONSERVATIVE")),
        "result_r":round(float(resolved_r),5),
        "max_adverse_r":round(max_adverse_r,5),
        "max_favorable_r":round(max_favorable_r,5),
        "minutes_to_resolution":int((hit_time-start).total_seconds()//60) if hit_time is not None else None,
    }


def evaluate_m3_v40(one_closed,four_closed,fifteen,signal_time,btc_closed=None,eth_closed=None):
    base=evaluate_m3_v37(one_closed,four_closed,fifteen,signal_time,btc_closed,eth_closed)
    out={}
    for key,value in base.items():
        if key.startswith("m3v37_"):
            out[key.replace("m3v37_","m3v40_",1)]=value
        else:
            out[key]=value

    if out.get("m3v40_state")!="BASELINE_CANDIDATE":
        return out
    if int(out.get("m3v40_candidate_a_rw24_le_m5") or 0)!=1:
        out["m3v40_state"]="FAIL_RW24_FROZEN_GATE"
        return out

    seq=_find_displacement_retest(fifteen,signal_time)
    if seq.get("state")!="RETEST_ENTRY":
        out["m3v40_state"]="NO_RETEST"
        return out

    poi=float(seq["break_level"]); atr15=float(seq["atr15"])
    entry_price=poi+float(M3_V40_ENTRY_OFFSET_ATR15)*atr15
    fill=_fill_limit(fifteen,seq,entry_price)
    out["m3v40_state"]="STRUCTURAL_STOP_STUDY"
    out["m3v40_poi"]=round(poi,10)
    out["m3v40_retest_high"]=round(float(seq["retest_high"]),10)
    out["m3v40_atr15"]=round(atr15,10)
    out["m3v40_entry_limit"]=round(entry_price,10)
    out["m3v40_entry_state"]=fill.get("state")
    if fill.get("state")!="FILLED":
        return out

    entry=float(fill["entry"]); entry_idx=int(fill["entry_idx"])
    out["m3v40_entry"]=round(entry,10)
    out["m3v40_entry_time"]=pd.Timestamp(fill["entry_time"]).isoformat()
    out["m3v40_wait_bars"]=int(fill["wait_bars"])

    stops={}
    for name,buffer_atr in M3_V40_STOP_BUFFERS_ATR15.items():
        stop=float(seq["retest_high"])+float(buffer_atr)*atr15
        item={"buffer_atr15":float(buffer_atr),"stop":round(stop,10)}
        if stop<=entry:
            item["valid"]=0
        else:
            item["valid"]=1
            for r in M3_V40_TARGET_R:
                item[f"r{str(r).replace('.','_')}"]=_r_path(fifteen,entry_idx,entry,stop,r)
        stops[name]=item
    out["m3v40_stops"]=stops
    return out
