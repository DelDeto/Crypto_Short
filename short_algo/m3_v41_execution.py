"""M3 V4.1 structural invalidation research."""
import pandas as pd
from .m3_v2_execution import _find_displacement_retest
from .m3_v37_execution import evaluate_m3_v37
from .m3_v39_execution import _fill_limit
from .m3_v41_config import M3_V41_ENTRY_OFFSET_ATR15,M3_V41_LOCAL_15M_LOOKBACK,M3_V41_REJECTION_1H_LOOKBACK,M3_V41_POLICIES,M3_V41_TARGET_R

STEP=pd.Timedelta(minutes=15)

def _path(fifteen,entry_idx,entry,sl,target_r):
    rows=fifteen.sort_index().iloc[int(entry_idx):]
    if rows.empty:return {}
    start=rows.index[0]
    rows=rows.loc[rows.index<start+pd.Timedelta(hours=24)]
    if rows.empty:return {}
    entry=float(entry);sl=float(sl);unit=sl-entry
    if unit<=0:return {"valid":0}
    target=entry-float(target_r)*unit
    state="OPEN";result=None;resolved=None;mae=0.0;mfe=0.0
    for n,(t,row) in enumerate(rows.iterrows()):
        h=float(row["high"]);l=float(row["low"])
        mae=max(mae,max(0.0,(h-entry)/unit))
        mfe=max(mfe,max(0.0,(entry-l)/unit))
        hit_sl=h>=sl
        hit_tp=(n>0 and l<=target)
        if hit_sl and hit_tp:
            state="SL_FIRST_SAME_BAR";result=-1.0;resolved=pd.Timestamp(t)+STEP;break
        if hit_sl:
            state="SL";result=-1.0;resolved=pd.Timestamp(t)+STEP;break
        if hit_tp:
            state="TP";result=float(target_r);resolved=pd.Timestamp(t)+STEP;break
    if result is None:
        last=float(rows.iloc[-1]["close"])
        result=max(-1.0,min(float(target_r),(entry-last)/unit))
    return {"valid":1,"sl":round(sl,10),"risk_pct":round(unit/entry*100.0,5),"target":round(target,10),"target_r":float(target_r),"state":state,"target_hit":int(state=="TP"),"sl_hit":int(state in ("SL","SL_FIRST_SAME_BAR")),"result_r":round(float(result),5),"mae_r":round(mae,5),"mfe_r":round(mfe,5),"minutes":int((resolved-start).total_seconds()//60) if resolved is not None else None}

def _anchor(one_closed,fifteen,seq):
    frame=fifteen.sort_index();idx=int(seq["entry_idx"])
    lo=max(0,idx-int(M3_V41_LOCAL_15M_LOOKBACK))
    local15=float(frame.iloc[lo:idx]["high"].astype(float).max()) if idx>lo else float(seq["retest_high"])
    tail=one_closed.iloc[-int(M3_V41_REJECTION_1H_LOOKBACK):]
    high1=float(tail["high"].astype(float).max())
    parts={"retest_high":float(seq["retest_high"]),"local_high_15m":local15,"rejection_high_1h":high1}
    src=max(parts,key=parts.get)
    return parts[src],src,parts

def evaluate_m3_v41(one_closed,four_closed,fifteen,signal_time,btc_closed=None,eth_closed=None):
    base=evaluate_m3_v37(one_closed,four_closed,fifteen,signal_time,btc_closed,eth_closed)
    out={}
    for k,v in base.items():
        out[k.replace("m3v37_","m3v41_",1) if k.startswith("m3v37_") else k]=v
    if out.get("m3v41_state")!="BASELINE_CANDIDATE":return out
    if int(out.get("m3v41_candidate_a_rw24_le_m5") or 0)!=1:
        out["m3v41_state"]="FAIL_RW24";return out
    seq=_find_displacement_retest(fifteen,signal_time)
    if seq.get("state")!="RETEST_ENTRY":
        out["m3v41_state"]="NO_RETEST";return out
    poi=float(seq["break_level"]);atr15=float(seq["atr15"])
    entry_limit=poi+float(M3_V41_ENTRY_OFFSET_ATR15)*atr15
    fill=_fill_limit(fifteen,seq,entry_limit)
    out.update({"m3v41_state":"STRUCTURAL_STUDY","m3v41_poi":round(poi,10),"m3v41_atr15":round(atr15,10),"m3v41_entry_limit":round(entry_limit,10),"m3v41_entry_state":fill.get("state")})
    if fill.get("state")!="FILLED":return out
    entry=float(fill["entry"]);idx=int(fill["entry_idx"])
    anchor,src,parts=_anchor(one_closed,fifteen,seq)
    out.update({"m3v41_entry":round(entry,10),"m3v41_entry_time":pd.Timestamp(fill["entry_time"]).isoformat(),"m3v41_anchor":round(anchor,10),"m3v41_anchor_source":src,"m3v41_anchor_parts":{k:round(v,10) for k,v in parts.items()}})
    policies={}
    for name,cfg in M3_V41_POLICIES.items():
        raw=anchor+float(cfg["buffer_atr15"])*atr15
        floor_dist=max(float(cfg["min_atr15"])*atr15,float(cfg["min_pct"])/100.0*entry)
        floor_level=entry+floor_dist
        sl=max(raw,floor_level)
        item={**cfg,"raw_level":round(raw,10),"floor_level":round(floor_level,10),"floor_applied":int(floor_level>=raw),"sl":round(sl,10),"risk_pct":round((sl-entry)/entry*100.0,5)}
        for tr in M3_V41_TARGET_R:item[f"r{str(tr).replace('.','_')}"]=_path(fifteen,idx,entry,sl,tr)
        policies[name]=item
    out["m3v41_policies"]=policies
    return out
