"""M3 V4.3 — exit architecture study on frozen V4.2 setup/entry/SL."""
import pandas as pd
from .m3_v42_execution import evaluate_m3_v42
from .m3_v43_config import M3_V43_FIXED_TARGETS,M3_V43_PARTIAL_FIRST_R,M3_V43_PARTIAL_FINAL_R,M3_V43_PARTIAL_FIRST_FRACTION

STEP=pd.Timedelta(minutes=15)

def _entry_idx(frame,entry_time):
    ts=pd.Timestamp(entry_time)
    if ts.tzinfo is None and frame.index.tz is not None:
        ts=ts.tz_localize(frame.index.tz)
    idx=frame.index.get_indexer([ts])
    return int(idx[0]) if len(idx) and idx[0]>=0 else None

def _fixed(frame,idx,entry,sl,target_r):
    rows=frame.iloc[int(idx):]
    if rows.empty:return {}
    start=rows.index[0]
    rows=rows.loc[rows.index<start+pd.Timedelta(hours=24)]
    risk=float(sl)-float(entry)
    if risk<=0 or rows.empty:return {"valid":0}
    target=float(entry)-float(target_r)*risk
    state="OPEN";result=None;resolved=None
    for n,(t,row) in enumerate(rows.iterrows()):
        h=float(row["high"]);l=float(row["low"])
        hit_sl=h>=float(sl)
        hit_tp=(n>0 and l<=target)
        if hit_sl and hit_tp:
            state="SL_FIRST_SAME_BAR";result=-1.0;resolved=pd.Timestamp(t)+STEP;break
        if hit_sl:
            state="SL";result=-1.0;resolved=pd.Timestamp(t)+STEP;break
        if hit_tp:
            state="TP";result=float(target_r);resolved=pd.Timestamp(t)+STEP;break
    if result is None:
        last=float(rows.iloc[-1]["close"])
        result=max(-1.0,min(float(target_r),(float(entry)-last)/risk))
        state="TIME_EXIT_24H"
    return {"valid":1,"state":state,"result_r":round(float(result),5),"target_hit":int(state=="TP"),"sl_hit":int(state in ("SL","SL_FIRST_SAME_BAR")),"minutes":int((resolved-start).total_seconds()//60) if resolved is not None else None}

def _partial(frame,idx,entry,sl):
    rows=frame.iloc[int(idx):]
    if rows.empty:return {}
    start=rows.index[0]
    rows=rows.loc[rows.index<start+pd.Timedelta(hours=24)]
    risk=float(sl)-float(entry)
    if risk<=0 or rows.empty:return {"valid":0}

    first_r=float(M3_V43_PARTIAL_FIRST_R)
    final_r=float(M3_V43_PARTIAL_FINAL_R)
    frac=float(M3_V43_PARTIAL_FIRST_FRACTION)
    t1=float(entry)-first_r*risk
    t2=float(entry)-final_r*risk

    took_first=False;state="OPEN";result=None;resolved=None
    for n,(t,row) in enumerate(rows.iterrows()):
        h=float(row["high"]);l=float(row["low"])
        hit_sl=h>=float(sl)
        hit_t1=(n>0 and l<=t1)
        hit_t2=(n>0 and l<=t2)

        if not took_first:
            if hit_sl and hit_t1:
                state="SL_FIRST_SAME_BAR";result=-1.0;resolved=pd.Timestamp(t)+STEP;break
            if hit_sl:
                state="SL";result=-1.0;resolved=pd.Timestamp(t)+STEP;break
            if hit_t1:
                took_first=True
                if hit_t2:
                    result=frac*first_r+(1.0-frac)*final_r
                    state="TP_FINAL";resolved=pd.Timestamp(t)+STEP;break
                continue
        else:
            if hit_sl and hit_t2:
                # Conservative ordering on the remaining half.
                result=frac*first_r-(1.0-frac)
                state="PARTIAL_THEN_SL_SAME_BAR";resolved=pd.Timestamp(t)+STEP;break
            if hit_sl:
                result=frac*first_r-(1.0-frac)
                state="PARTIAL_THEN_SL";resolved=pd.Timestamp(t)+STEP;break
            if hit_t2:
                result=frac*first_r+(1.0-frac)*final_r
                state="TP_FINAL";resolved=pd.Timestamp(t)+STEP;break

    if result is None:
        last=float(rows.iloc[-1]["close"])
        mtm=max(-1.0,min(final_r,(float(entry)-last)/risk))
        result=(frac*first_r+(1.0-frac)*mtm) if took_first else mtm
        state="PARTIAL_TIME_EXIT_24H" if took_first else "TIME_EXIT_24H"

    return {"valid":1,"state":state,"result_r":round(float(result),5),"first_target_hit":int(took_first),"final_target_hit":int(state=="TP_FINAL"),"sl_hit":int("SL" in state),"minutes":int((resolved-start).total_seconds()//60) if resolved is not None else None}

def evaluate_m3_v43(one_closed,four_closed,fifteen,signal_time,btc_closed=None,eth_closed=None):
    base=evaluate_m3_v42(one_closed,four_closed,fifteen,signal_time,btc_closed,eth_closed)
    out={}
    for k,v in base.items():
        out[k.replace("m3v42_","m3v43_",1) if k.startswith("m3v42_") else k]=v
    if out.get("m3v43_state")!="STRUCTURAL_STUDY":return out
    if out.get("m3v43_entry_state")!="FILLED":return out

    frozen=out.get("m3v43_frozen_policy") or {}
    entry=out.get("m3v43_entry");entry_time=out.get("m3v43_entry_time");sl=frozen.get("sl")
    if entry is None or entry_time is None or sl is None:
        out["m3v43_exit_state"]="MISSING_FROZEN_RISK";return out

    frame=fifteen.sort_index()
    idx=_entry_idx(frame,entry_time)
    if idx is None:
        out["m3v43_exit_state"]="ENTRY_INDEX_NOT_FOUND";return out

    variants={}
    for tr in M3_V43_FIXED_TARGETS:
        variants[f"fixed_{str(tr).replace('.','_')}R"]=_fixed(frame,idx,float(entry),float(sl),float(tr))
    variants["partial_50_at_1_5R_rest_3R"]=_partial(frame,idx,float(entry),float(sl))
    out["m3v43_exit_state"]="EXIT_STUDY"
    out["m3v43_exit_variants"]=variants
    return out
