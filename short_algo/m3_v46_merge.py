"""M3 V4.6 merge: validate predeclared regime hypotheses on sequential OOS data."""
import json,os,sys,math,random
from glob import glob
import numpy as np
from .config import OUTPUT_DIR
from .m3_v441_config import M3_V441_MIN_ELIGIBLE_SYMBOLS
from .m3_v46_config import (
    M3_V46_HYPOTHESES,M3_V46_MIN_ENTRIES,M3_V46_REQUIRED_ACTIVE_BLOCKS,
    M3_V46_MIN_POSITIVE_BLOCKS,
)

def _pct(n,d):return round(100.0*n/d,2) if d else None
def _mean(xs):
    xs=[float(x) for x in xs if x is not None]
    return round(float(np.mean(xs)),5) if xs else None
def _med(xs):
    xs=[float(x) for x in xs if x is not None]
    return round(float(np.median(xs)),5) if xs else None
def _wilson(w,n,z=1.96):
    if not n:return [None,None]
    p=w/n;den=1+z*z/n;ctr=(p+z*z/(2*n))/den
    half=z*math.sqrt((p*(1-p)+z*z/(4*n))/n)/den
    return [round(100*(ctr-half),2),round(100*(ctr+half),2)]
def _bootstrap_mean_ci(vals,reps=5000):
    vals=[float(x) for x in vals if x is not None]
    if not vals:return [None,None]
    rng=random.Random(460);n=len(vals);means=[]
    for _ in range(reps):
        means.append(sum(vals[rng.randrange(n)] for _ in range(n))/n)
    means.sort()
    return [round(means[int(0.025*(reps-1))],5),round(means[int(0.975*(reps-1))],5)]
def _max_drawdown(vals):
    curve=0.0;peak=0.0;mdd=0.0
    for x in vals:
        curve+=float(x);peak=max(peak,curve);mdd=max(mdd,peak-curve)
    return round(mdd,5)
def _exit(row):return row.get("m3v45_frozen_exit") or {}
def _result(row):
    v=_exit(row).get("result_r")
    return float(v) if v is not None else None

def _metrics(rows,total_days,blocks):
    ordered=sorted(rows,key=lambda r:r.get("signal_time") or "")
    vals=[r for r in ordered if int(_exit(r).get("valid") or 0)==1]
    rs=[_result(r) for r in vals]
    wins=sum(1 for r in vals if _exit(r).get("state")=="TP")
    sls=sum(int(_exit(r).get("sl_hit") or 0) for r in vals)
    block_rows=[]
    for b in blocks:
        bid=int(b["block"])
        br=[r for r in vals if int(r.get("m3v45_block") or 0)==bid]
        brs=[_result(r) for r in br]
        block_rows.append({"block":bid,"entries":len(br),"expectancy_r":_mean(brs),"total_r":round(sum(x for x in brs if x is not None),5)})
    active=sum(1 for b in block_rows if b["entries"]>0)
    positive=sum(1 for b in block_rows if b["entries"]>0 and b["expectancy_r"] is not None and b["expectancy_r"]>0)
    return {
        "entries":len(vals),
        "entries_per_day":round(len(vals)/max(float(total_days),1.0),3),
        "target_hit_pct":_pct(wins,len(vals)),
        "target_hit_wilson95_pct":_wilson(wins,len(vals)),
        "sl_hit_pct":_pct(sls,len(vals)),
        "expectancy_r":_mean(rs),
        "expectancy_bootstrap95_r":_bootstrap_mean_ci(rs),
        "total_r":round(sum(x for x in rs if x is not None),5),
        "median_result_r":_med(rs),
        "max_drawdown_r_signal_order":_max_drawdown([x for x in rs if x is not None]),
        "median_minutes":_med([_exit(r).get("minutes") for r in vals]),
        "active_blocks":active,
        "positive_expectancy_blocks":positive,
        "block_expectancy":block_rows,
    }

def _match(row,hid):
    if hid=="H0_BASELINE":return True
    if hid=="H1_RISK_OFF":
        return str(row.get("m3v45_market_state") or "")=="RISK_OFF"
    if hid=="H2_BEARISH_4H":
        v=row.get("m3v45_market_return_4h_pct")
        return v is not None and float(v)>-1.5 and float(v)<=-0.5
    if hid=="H3_DEEP_RISK_OFF":
        v=row.get("m3v45_market_return_24h_pct")
        return v is not None and float(v)<=-4.0
    raise KeyError(hid)

def _shadow_gate(metrics,baseline):
    checks={
        "min_entries":int(metrics.get("entries") or 0)>=int(M3_V46_MIN_ENTRIES),
        "all_blocks_active":int(metrics.get("active_blocks") or 0)>=int(M3_V46_REQUIRED_ACTIVE_BLOCKS),
        "positive_blocks":int(metrics.get("positive_expectancy_blocks") or 0)>=int(M3_V46_MIN_POSITIVE_BLOCKS),
        "expectancy_beats_baseline":metrics.get("expectancy_r") is not None and baseline.get("expectancy_r") is not None and float(metrics["expectancy_r"])>float(baseline["expectancy_r"]),
        "drawdown_not_worse":metrics.get("max_drawdown_r_signal_order") is not None and baseline.get("max_drawdown_r_signal_order") is not None and float(metrics["max_drawdown_r_signal_order"])<=float(baseline["max_drawdown_r_signal_order"]),
    }
    return {"pass":all(checks.values()),"checks":checks}

def main(root="m3v46_shards",preflight_path="frozen/m3_v46_preflight.json"):
    reps=[]
    for p in sorted(glob(os.path.join(root,"**","m3_v46_backtest.json"),recursive=True)):
        with open(p,encoding="utf-8") as f:reps.append(json.load(f))
    if not reps:raise RuntimeError("No M3 V4.6 reports")
    expected=max(int(r["shard_count"]) for r in reps)
    found={int(r["shard_index"]) for r in reps}
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
    for row in rows:dedup.setdefault((row.get("symbol"),row.get("signal_time")),row)
    rows=list(dedup.values())
    cov={c.get("symbol"):c for c in coverage}
    eligible=sum(1 for c in cov.values() if int(c.get("eligible") or 0)==1)
    data_valid=bool((preflight is None or preflight.get("data_valid")) and eligible>=int(M3_V441_MIN_ELIGIBLE_SYMBOLS))

    m=reps[0]["manifest"]
    blocks=m["blocks"];total_days=int(m["block_days"])*int(m["block_count"])
    hypothesis_results={}
    for hid in M3_V46_HYPOTHESES:
        subset=[r for r in rows if _match(r,hid)]
        hypothesis_results[hid]={
            "definition":M3_V46_HYPOTHESES[hid],
            "metrics":_metrics(subset,total_days,blocks),
        }
    baseline=hypothesis_results["H0_BASELINE"]["metrics"]
    for hid,item in hypothesis_results.items():
        met=item["metrics"]
        item["vs_baseline"]={
            "retained_pct":_pct(met["entries"],baseline["entries"]),
            "delta_expectancy_r":round(float(met["expectancy_r"])-float(baseline["expectancy_r"]),5) if met["expectancy_r"] is not None and baseline["expectancy_r"] is not None else None,
            "delta_max_drawdown_r":round(float(met["max_drawdown_r_signal_order"])-float(baseline["max_drawdown_r_signal_order"]),5) if met["max_drawdown_r_signal_order"] is not None and baseline["max_drawdown_r_signal_order"] is not None else None,
        }
        item["shadow_gate"]={"pass":False,"checks":{"baseline_reference":True}} if hid=="H0_BASELINE" else _shadow_gate(met,baseline)

    eligible_h=[hid for hid in ("H1_RISK_OFF","H2_BEARISH_4H","H3_DEEP_RISK_OFF") if hypothesis_results[hid]["shadow_gate"]["pass"]]
    selected=max(eligible_h,key=lambda h:float(hypothesis_results[h]["metrics"]["expectancy_r"])) if eligible_h else None
    decision=f"SHADOW_ELIGIBLE:{selected}" if selected else "NO_REGIME_VALIDATED"

    out={
        "engine":"M3 V4.6 Frozen Regime OOS Validation",
        "manifest_id":next(iter(mids)),
        "period_start":m["period_start"],"period_end":m["period_end"],
        "selected_symbols":len(set(symbols)),"eligible_symbols":eligible,"data_valid":data_valid,
        "preflight":preflight,"errors":errors,
        "oos_scope":"regime hypotheses only; base setup lineage not fully OOS",
        "hypotheses_frozen_before_run":m.get("hypotheses"),
        "hypothesis_results":hypothesis_results,
        "shadow_gate_policy":{
            "min_entries":M3_V46_MIN_ENTRIES,
            "required_active_blocks":M3_V46_REQUIRED_ACTIVE_BLOCKS,
            "min_positive_blocks":M3_V46_MIN_POSITIVE_BLOCKS,
            "expectancy_must_beat_baseline":True,
            "drawdown_must_not_exceed_baseline":True,
        },
        "decision":decision,
        "selected_shadow_candidate":selected,
        "live_promotion":False,
        "research_status":"OOS_REGIME_VALIDATION_COMPLETE_NOT_LIVE_PROMOTION" if data_valid else "DATA_INVALID",
        "note":"Thresholds were frozen from V4.5.1 before this sequential OOS run. No threshold retuning is permitted from this window. Any passing hypothesis is eligible for shadow monitoring only, not live promotion.",
    }
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v46_analysis.json"),"w",encoding="utf-8") as f:json.dump(out,f,ensure_ascii=False,indent=2,default=str)
    with open(os.path.join(OUTPUT_DIR,"m3_v46_summary.md"),"w",encoding="utf-8") as f:
        f.write("# M3 V4.6 - Frozen Regime OOS Validation\n\n")
        f.write(f"Decision: **{decision}**\n\n")
        f.write(json.dumps(out,ensure_ascii=False,indent=2))
        f.write("\n")
    print(json.dumps({"decision":decision,"data_valid":data_valid,"results":{k:v["metrics"] for k,v in hypothesis_results.items()},"gates":{k:v["shadow_gate"] for k,v in hypothesis_results.items()}},ensure_ascii=False,indent=2))
    return 0 if data_valid else 2

if __name__=="__main__":
    root=sys.argv[1] if len(sys.argv)>1 else "m3v46_shards"
    pf=sys.argv[2] if len(sys.argv)>2 else "frozen/m3_v46_preflight.json"
    raise SystemExit(main(root,pf))
