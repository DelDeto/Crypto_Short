"""M3 V4.7 failure attribution on the exact V4.6 OOS sample. Diagnostic only."""
import json,os,sys
from collections import Counter
from glob import glob
import numpy as np

from .config import OUTPUT_DIR
from .m3_v441_config import M3_V441_MIN_ELIGIBLE_SYMBOLS
from .m3_v47_config import (
    M3_V47_NUMERIC_BINS,M3_V47_MIN_BUCKET_ENTRIES,
    M3_V47_FAST_SL_MINUTES,M3_V47_MEDIUM_SL_MINUTES,M3_V47_LOW_MFE_R,
    M3_V47_EXPECTED_ENTRIES,M3_V47_EXPECTED_BLOCK_ENTRIES,
    M3_V47_EXPECTED_EXPECTANCY_R,M3_V47_EXPECTED_TOTAL_R,M3_V47_REPLICATION_TOL,
)

FEATURES={
    "impulse_atr":"m3v2_impulse_atr",
    "pullback_retrace":"m3v2_pullback_retrace",
    "retest_penetration_atr15":"m3v21_retest_penetration_atr15",
    "retest_volume_vs_displacement":"m3v21_retest_volume_vs_displacement",
    "distance_to_ema20_atr1h":"m3v45_distance_to_ema20_atr1h",
    "distance_to_ema50_atr1h":"m3v45_distance_to_ema50_atr1h",
    "coin_return_24h_pct":"m3v45_coin_return_24h_pct",
    "relative_weakness_24h_pct":"m3v45_relative_weakness_24h_pct",
    "volume_expansion_1h":"m3v45_volume_expansion_1h",
}
CATEGORICAL={
    "pullback_bars":"m3v2_pullback_bars",
    "anchor_source":"m3v45_anchor_source",
    "failed_reclaim_1h":"m3v2_failed_reclaim_1h",
    "bearish_rejection_1h":"m3v2_bearish_rejection_1h",
    "lower_high_1h":"m3v2_lower_high_1h",
    "market_state":"m3v45_market_state",
}

def _exit(r):return r.get("m3v45_frozen_exit") or {}
def _result(r):
    v=_exit(r).get("result_r")
    return float(v) if v is not None else None
def _class(r):
    s=str(_exit(r).get("state") or "")
    if s=="TP":return "TP"
    if "SL" in s:return "SL"
    return "TIME"
def _mean(xs):
    xs=[float(x) for x in xs if x is not None]
    return round(float(np.mean(xs)),5) if xs else None
def _med(xs):
    xs=[float(x) for x in xs if x is not None]
    return round(float(np.median(xs)),5) if xs else None
def _pct(n,d):return round(100.0*n/d,2) if d else None
def _risk_pct(r):
    p=r.get("m3v45_frozen_policy") or {}
    v=p.get("risk_pct")
    return float(v) if v is not None else None
def _mfe_proxy(r):
    p=r.get("m3v45_frozen_policy") or {}
    v=(p.get("r2_0") or {}).get("mfe_r")
    return float(v) if v is not None else None
def _mae_proxy(r):
    p=r.get("m3v45_frozen_policy") or {}
    v=(p.get("r2_0") or {}).get("mae_r")
    return float(v) if v is not None else None
def _value(r,name):
    if name=="risk_pct":return _risk_pct(r)
    return r.get(FEATURES[name])
def _bucket(v,edges):
    if v is None:return "MISSING"
    x=float(v)
    for i in range(len(edges)-1):
        lo,hi=float(edges[i]),float(edges[i+1])
        if i==0 and x<=hi:return f"<= {hi:g}"
        if i==len(edges)-2 and x>lo:return f"> {lo:g}"
        if lo<x<=hi:return f"({lo:g}, {hi:g}]"
    return "OUTSIDE"
def _metrics(rows):
    vals=[r for r in rows if int(_exit(r).get("valid") or 0)==1]
    rs=[_result(r) for r in vals]
    return {
        "entries":len(vals),
        "tp":sum(1 for r in vals if _class(r)=="TP"),
        "sl":sum(1 for r in vals if _class(r)=="SL"),
        "time_exit":sum(1 for r in vals if _class(r)=="TIME"),
        "tp_pct":_pct(sum(1 for r in vals if _class(r)=="TP"),len(vals)),
        "sl_pct":_pct(sum(1 for r in vals if _class(r)=="SL"),len(vals)),
        "expectancy_r":_mean(rs),
        "total_r":round(sum(x for x in rs if x is not None),5),
        "median_minutes":_med([_exit(r).get("minutes") for r in vals]),
    }
def _outcome_medians(rows):
    out={}
    names=list(FEATURES)+["risk_pct","mfe_r_proxy","mae_r_proxy"]
    for cls in ("TP","SL","TIME"):
        rr=[r for r in rows if _class(r)==cls]
        med={}
        for name in names:
            if name=="mfe_r_proxy":xs=[_mfe_proxy(r) for r in rr]
            elif name=="mae_r_proxy":xs=[_mae_proxy(r) for r in rr]
            else:xs=[_value(r,name) for r in rr]
            med[name]=_med(xs)
        out[cls]={"entries":len(rr),"medians":med}
    deltas={}
    for name in names:
        a=out["TP"]["medians"].get(name);b=out["SL"]["medians"].get(name)
        deltas[name]=round(float(a)-float(b),5) if a is not None and b is not None else None
    return out,deltas
def _numeric_bins(rows,name,edges):
    groups={}
    for r in rows:groups.setdefault(_bucket(_value(r,name),edges),[]).append(r)
    return {k:_metrics(v) for k,v in groups.items()}
def _categorical(rows,name,key):
    groups={}
    for r in rows:
        if name=="pullback_bars":
            v=r.get(key)
            label="1" if v==1 else ("2" if v==2 else (">=3" if v is not None and float(v)>=3 else "MISSING"))
        else:label=str(r.get(key) if r.get(key) is not None else "MISSING")
        groups.setdefault(label,[]).append(r)
    return {k:_metrics(v) for k,v in groups.items()}
def _spread_candidates(diagnostics):
    out=[]
    for dim,buckets in diagnostics.items():
        eligible=[(label,m) for label,m in buckets.items() if int(m.get("entries") or 0)>=int(M3_V47_MIN_BUCKET_ENTRIES) and m.get("expectancy_r") is not None]
        if len(eligible)<2:continue
        hi=max(eligible,key=lambda x:float(x[1]["expectancy_r"]))
        lo=min(eligible,key=lambda x:float(x[1]["expectancy_r"]))
        out.append({
            "dimension":dim,
            "high_bucket":hi[0],"high_entries":hi[1]["entries"],"high_expectancy_r":hi[1]["expectancy_r"],
            "low_bucket":lo[0],"low_entries":lo[1]["entries"],"low_expectancy_r":lo[1]["expectancy_r"],
            "spread_r":round(float(hi[1]["expectancy_r"])-float(lo[1]["expectancy_r"]),5),
            "diagnostic_only":True,
        })
    return sorted(out,key=lambda x:-abs(float(x["spread_r"])))
def _failure_signatures(rows):
    sl=[r for r in rows if _class(r)=="SL"]
    def sig(r):
        mins=_exit(r).get("minutes")
        return {
            "fast_sl_le_120m":mins is not None and float(mins)<=float(M3_V47_FAST_SL_MINUTES),
            "medium_sl_121_360m":mins is not None and float(M3_V47_FAST_SL_MINUTES)<float(mins)<=float(M3_V47_MEDIUM_SL_MINUTES),
            "slow_sl_gt_360m":mins is not None and float(mins)>float(M3_V47_MEDIUM_SL_MINUTES),
            "low_mfe_lt_0_5r":_mfe_proxy(r) is not None and _mfe_proxy(r)<float(M3_V47_LOW_MFE_R),
            "pullback_bars_ge_3":r.get("m3v2_pullback_bars") is not None and float(r.get("m3v2_pullback_bars"))>=3,
            "retest_penetration_gt_0_25atr15":r.get("m3v21_retest_penetration_atr15") is not None and float(r.get("m3v21_retest_penetration_atr15"))>0.25,
            "risk_pct_gt_3":_risk_pct(r) is not None and _risk_pct(r)>3.0,
        }
    flags={name:0 for name in sig(sl[0]).keys()} if sl else {}
    combos=Counter()
    for r in sl:
        s=sig(r)
        for k,v in s.items():flags[k]+=int(bool(v))
        active=sorted(k for k,v in s.items() if v and not k.startswith(("fast_sl","medium_sl","slow_sl")))
        for i in range(len(active)):
            for j in range(i+1,len(active)):
                combos[(active[i],active[j])]+=1
    return {
        "sl_entries":len(sl),
        "signature_counts":{k:{"count":v,"pct_of_sl":_pct(v,len(sl))} for k,v in flags.items()},
        "top_overlaps":[{"signals":list(k),"count":v,"pct_of_sl":_pct(v,len(sl))} for k,v in combos.most_common(10)],
        "note":"MFE proxy comes from the frozen structural policy r2 path and is used only as descriptive execution excursion, not as an immediate-follow-through trading rule.",
    }

def main(root="m3v47_shards",preflight_path="frozen/m3_v47_preflight.json"):
    reps=[]
    for p in sorted(glob(os.path.join(root,"**","m3_v47_backtest.json"),recursive=True)):
        with open(p,encoding="utf-8") as f:reps.append(json.load(f))
    if not reps:raise RuntimeError("No M3 V4.7 reports")
    expected=max(int(r["shard_count"]) for r in reps);found={int(r["shard_index"]) for r in reps}
    if found!=set(range(expected)):raise RuntimeError(f"Incomplete shards {sorted(found)}")
    mids={r["manifest_id"] for r in reps}
    if len(mids)!=1:raise RuntimeError("Manifest mismatch")

    preflight=None
    if os.path.exists(preflight_path):
        with open(preflight_path,encoding="utf-8") as f:preflight=json.load(f)
    rows=[];coverage=[];errors=[];symbols=[]
    for r in reps:
        rows+=r.get("rows",[]);coverage+=r.get("coverage",[]);errors+=r.get("errors",[]);symbols+=r.get("selected_symbols",[])
    dedup={}
    for r in rows:dedup.setdefault((r.get("symbol"),r.get("signal_time")),r)
    rows=list(dedup.values())
    cov={c.get("symbol"):c for c in coverage}
    eligible=sum(1 for c in cov.values() if int(c.get("eligible") or 0)==1)
    data_valid=bool((preflight is None or preflight.get("data_valid")) and eligible>=int(M3_V441_MIN_ELIGIBLE_SYMBOLS))

    base=_metrics(rows)
    m=reps[0]["manifest"]
    block_entries=[]
    for b in m["blocks"]:
        br=[r for r in rows if int(r.get("m3v45_block") or 0)==int(b["block"])]
        block_entries.append(len([r for r in br if int(_exit(r).get("valid") or 0)==1]))
    replication={
        "entries_match":base["entries"]==int(M3_V47_EXPECTED_ENTRIES),
        "block_entries_match":block_entries==list(M3_V47_EXPECTED_BLOCK_ENTRIES),
        "expectancy_match":base["expectancy_r"] is not None and abs(float(base["expectancy_r"])-float(M3_V47_EXPECTED_EXPECTANCY_R))<=float(M3_V47_REPLICATION_TOL),
        "total_r_match":abs(float(base["total_r"])-float(M3_V47_EXPECTED_TOTAL_R))<=float(M3_V47_REPLICATION_TOL),
    }
    replication["pass"]=all(replication.values())

    outcome_medians,tp_minus_sl=_outcome_medians(rows)
    diagnostics={}
    diagnostics["pullback_bars"]=_categorical(rows,"pullback_bars",CATEGORICAL["pullback_bars"])
    for name,key in CATEGORICAL.items():
        if name=="pullback_bars":continue
        diagnostics[name]=_categorical(rows,name,key)
    for name,edges in M3_V47_NUMERIC_BINS.items():
        diagnostics[name]=_numeric_bins(rows,name,edges)

    out={
        "engine":"M3 V4.7 OOS Failure Attribution",
        "manifest_id":next(iter(mids)),
        "period_start":m["period_start"],"period_end":m["period_end"],
        "selected_symbols":len(set(symbols)),"eligible_symbols":eligible,"data_valid":data_valid,
        "replication_gate":replication,
        "baseline":base,
        "outcome_medians":outcome_medians,
        "tp_minus_sl_median_delta":tp_minus_sl,
        "diagnostic_buckets":diagnostics,
        "largest_expectancy_spreads":_spread_candidates(diagnostics),
        "failure_signatures":_failure_signatures(rows),
        "research_status":"DIAGNOSTIC_ONLY_NO_RULE_CHANGE_NO_FILTER_PROMOTION",
        "next_step":"Use V4.7 only to define a small pre-registered V4.8 hypothesis set. Do not tune a filter directly on this same 60-trade window.",
        "note":"V4.7 replays the exact V4.6 strategy/window/cohort. It changes no setup, entry, stop, exit, cooldown, or regime rule. Any apparent failure signature is hypothesis generation only.",
    }
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v47_analysis.json"),"w",encoding="utf-8") as f:json.dump(out,f,ensure_ascii=False,indent=2,default=str)
    with open(os.path.join(OUTPUT_DIR,"m3_v47_summary.md"),"w",encoding="utf-8") as f:
        f.write("# M3 V4.7 - OOS Failure Attribution\n\n")
        f.write(f"Replication gate: **{'PASS' if replication['pass'] else 'FAIL'}**\n\n")
        f.write(json.dumps(out,ensure_ascii=False,indent=2))
        f.write("\n")
    print(json.dumps({"replication_gate":replication,"baseline":base,"largest_expectancy_spreads":out["largest_expectancy_spreads"],"failure_signatures":out["failure_signatures"]},ensure_ascii=False,indent=2))
    if not data_valid or not replication["pass"]:return 2
    return 0

if __name__=="__main__":
    root=sys.argv[1] if len(sys.argv)>1 else "m3v47_shards"
    pf=sys.argv[2] if len(sys.argv)>2 else "frozen/m3_v47_preflight.json"
    raise SystemExit(main(root,pf))
