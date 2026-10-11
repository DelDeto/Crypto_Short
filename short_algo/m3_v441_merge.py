"""Merge M3 V4.4.1 and enforce data-validity guard."""
import json,os,sys,math,random
from glob import glob
import numpy as np

from .config import OUTPUT_DIR
from .m3_v441_config import M3_V441_MIN_ELIGIBLE_SYMBOLS

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
    rng=random.Random(441);n=len(vals);means=[]
    for _ in range(reps):
        means.append(sum(vals[rng.randrange(n)] for _ in range(n))/n)
    means.sort()
    return [round(means[int(0.025*(reps-1))],5),round(means[int(0.975*(reps-1))],5)]
def _max_drawdown(vals):
    curve=0.0;peak=0.0;mdd=0.0
    for x in vals:
        curve+=float(x);peak=max(peak,curve);mdd=max(mdd,peak-curve)
    return round(mdd,5)

def _metrics(rows,days):
    ordered=sorted(rows,key=lambda r:r.get("signal_time") or "")
    vals=[]
    for row in ordered:
        v=row.get("m3v441_frozen_exit") or {}
        if int(v.get("valid") or 0)==1:vals.append(v)
    rs=[v.get("result_r") for v in vals]
    wins=sum(1 for v in vals if v.get("state")=="TP")
    sls=sum(int(v.get("sl_hit") or 0) for v in vals)
    return {
        "entries":len(vals),
        "entries_per_day":round(len(vals)/max(float(days),1),3),
        "target_hit_pct":_pct(wins,len(vals)),
        "target_hit_wilson95_pct":_wilson(wins,len(vals)),
        "sl_hit_pct":_pct(sls,len(vals)),
        "expectancy_r":_mean(rs),
        "expectancy_bootstrap95_r":_bootstrap_mean_ci(rs),
        "total_r":round(sum(float(x) for x in rs if x is not None),5),
        "median_result_r":_med(rs),
        "max_drawdown_r_signal_order":_max_drawdown([x for x in rs if x is not None]),
        "median_minutes":_med([v.get("minutes") for v in vals]),
    }

def main(root="m3v441_shards",preflight_path="frozen/m3_v441_preflight.json"):
    reps=[]
    for p in sorted(glob(os.path.join(root,"**","m3_v441_backtest.json"),recursive=True)):
        with open(p,encoding="utf-8") as f:reps.append(json.load(f))
    if not reps:raise RuntimeError("No M3 V4.4.1 reports")

    expected=max(int(r["shard_count"]) for r in reps)
    found={int(r["shard_index"]) for r in reps}
    if found!=set(range(expected)):raise RuntimeError(f"Incomplete shards {sorted(found)}")
    mids={r["manifest_id"] for r in reps}
    if len(mids)!=1:raise RuntimeError("Manifest mismatch")

    preflight=None
    if os.path.exists(preflight_path):
        with open(preflight_path,encoding="utf-8") as f:preflight=json.load(f)

    rows=[];errors=[];symbols=[];coverage=[]
    for r in reps:
        rows+=r.get("rows",[]);errors+=r.get("errors",[])
        symbols+=r.get("selected_symbols",[]);coverage+=r.get("coverage",[])
    dedup={}
    for row in rows:dedup.setdefault((row.get("symbol"),row.get("signal_time")),row)
    rows=list(dedup.values())

    cov_by_symbol={}
    for c in coverage:cov_by_symbol[c.get("symbol")]=c
    eligible=[c for c in cov_by_symbol.values() if int(c.get("eligible") or 0)==1]
    eligible_count=len(eligible)
    selected_count=len(set(symbols))
    data_valid=bool(
        (preflight is None or bool(preflight.get("data_valid")))
        and eligible_count>=int(M3_V441_MIN_ELIGIBLE_SYMBOLS)
    )

    m=reps[0]["manifest"];bd=int(m["block_days"]);total=bd*int(m["block_count"])
    blocks=[]
    for b in m["blocks"]:
        br=[x for x in rows if int(x.get("m3v441_block") or 0)==int(b["block"])]
        blocks.append({"block":int(b["block"]),"start":b["start"],"end":b["end"],**_metrics(br,bd)})
    aggregate=_metrics(rows,total)

    tf_summary={}
    for tf in ("15M","1H","4H"):
        ratios=[]
        for c in cov_by_symbol.values():
            v=((c.get("timeframes") or {}).get(tf) or {}).get("coverage")
            if v is not None:ratios.append(float(v))
        tf_summary[tf]={
            "median_coverage":_med(ratios),
            "min_coverage":round(min(ratios),4) if ratios else None,
            "symbols_ge_threshold":sum(1 for x in ratios if x>=float(reps[0].get("minimum_symbol_coverage") or 0.0)),
        }

    out={
        "engine":"M3 V4.4.1 Fixed OOS Data Guard",
        "manifest_id":next(iter(mids)),
        "period_start":m["period_start"],"period_end":m["period_end"],
        "selected_symbols":selected_count,
        "eligible_symbols":eligible_count,
        "minimum_eligible_symbols":int(M3_V441_MIN_ELIGIBLE_SYMBOLS),
        "data_valid":data_valid,
        "preflight":preflight,
        "timeframe_coverage_summary":tf_summary,
        "errors":errors,
        "frozen_exit":"fixed_1_5R",
        "aggregate":aggregate,
        "blocks":blocks,
        "active_blocks":sum(1 for b in blocks if (b.get("entries") or 0)>0),
        "positive_expectancy_blocks":sum(1 for b in blocks if b.get("expectancy_r") is not None and b["expectancy_r"]>0),
        "median_block_expectancy_r":_med([b.get("expectancy_r") for b in blocks]),
        "min_block_expectancy_r":min([b["expectancy_r"] for b in blocks if b.get("expectancy_r") is not None],default=None),
        "research_status":"FROZEN_EXIT_POLICY_OOS_BASE_SETUP_PREEXPOSED_CURRENT_UNIVERSE_CAVEAT",
        "note":"Fixed 2026-04-08 to 2026-08-06 UTC. Frozen V4.2 setup/entry/structural SL + V4.3 fixed 1.5R exit. This window is OOS for the exit selection, but the base setup/context lineage has prior exposure to parts of this era. Current-universe ranking remains a survivorship caveat.",
    }

    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v441_analysis.json"),"w",encoding="utf-8") as f:
        json.dump(out,f,ensure_ascii=False,indent=2,default=str)
    with open(os.path.join(OUTPUT_DIR,"m3_v441_summary.md"),"w",encoding="utf-8") as f:
        f.write("# M3 V4.4.1 — Frozen 1.5R Exit OOS + Data Guard\n\n")
        f.write("Fixed dates: 2026-04-08 00:00 UTC to 2026-08-06 00:00 UTC. Strategy parameters frozen; coverage guard is operational QA only.\n\n")
        f.write(json.dumps(out,ensure_ascii=False,indent=2))
    print(json.dumps(out,ensure_ascii=False,indent=2))

    if not data_valid:
        print(f"M3 V4.4.1 DATA GUARD FAILED: eligible_symbols={eligible_count}, required={int(M3_V441_MIN_ELIGIBLE_SYMBOLS)}")
        return 2
    return 0

if __name__=="__main__":
    root=sys.argv[1] if len(sys.argv)>1 else "m3v441_shards"
    preflight=sys.argv[2] if len(sys.argv)>2 else "frozen/m3_v441_preflight.json"
    raise SystemExit(main(root,preflight))
