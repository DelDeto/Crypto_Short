"""M3 V4.8 validation of pre-registered structural-quality hypotheses."""
import json,os,sys
from glob import glob
from .config import OUTPUT_DIR
from .m3_v441_config import M3_V441_MIN_ELIGIBLE_SYMBOLS
from .m3_v46_merge import _metrics,_pct
from .m3_v48_config import (
    M3_V48_HYPOTHESES,M3_V48_SHALLOW_RETEST_MAX_ATR15,
    M3_V48_CONTAINED_RISK_MAX_PCT,M3_V48_COMPACT_PULLBACK_BARS,
    M3_V48_MIN_ENTRIES,M3_V48_REQUIRED_ACTIVE_BLOCKS,M3_V48_MIN_POSITIVE_BLOCKS,
)

def _risk_pct(row):
    p=row.get("m3v45_frozen_policy") or {}
    v=p.get("risk_pct")
    return float(v) if v is not None else None

def _shallow(row):
    v=row.get("m3v21_retest_penetration_atr15")
    return v is not None and float(v)<=float(M3_V48_SHALLOW_RETEST_MAX_ATR15)

def _contained_risk(row):
    v=_risk_pct(row)
    return v is not None and v<=float(M3_V48_CONTAINED_RISK_MAX_PCT)

def _compact(row):
    v=row.get("m3v2_pullback_bars")
    return v is not None and int(v)==int(M3_V48_COMPACT_PULLBACK_BARS)

def _match(row,hid):
    if hid=="H0_BASELINE":return True
    if hid=="H1_SHALLOW_RETEST":return _shallow(row)
    if hid=="H2_CONTAINED_RISK":return _contained_risk(row)
    if hid=="H3_COMPACT_PULLBACK":return _compact(row)
    if hid=="H4_ALL_THREE":return _shallow(row) and _contained_risk(row) and _compact(row)
    raise KeyError(hid)

def _validation_gate(metrics,baseline):
    checks={
        "min_entries":int(metrics.get("entries") or 0)>=int(M3_V48_MIN_ENTRIES),
        "all_blocks_active":int(metrics.get("active_blocks") or 0)>=int(M3_V48_REQUIRED_ACTIVE_BLOCKS),
        "positive_blocks":int(metrics.get("positive_expectancy_blocks") or 0)>=int(M3_V48_MIN_POSITIVE_BLOCKS),
        "expectancy_positive":metrics.get("expectancy_r") is not None and float(metrics["expectancy_r"])>0,
        "expectancy_beats_baseline":metrics.get("expectancy_r") is not None and baseline.get("expectancy_r") is not None and float(metrics["expectancy_r"])>float(baseline["expectancy_r"]),
        "drawdown_not_worse":metrics.get("max_drawdown_r_signal_order") is not None and baseline.get("max_drawdown_r_signal_order") is not None and float(metrics["max_drawdown_r_signal_order"])<=float(baseline["max_drawdown_r_signal_order"]),
    }
    return {"pass":all(checks.values()),"checks":checks}

def main(root="m3v48_shards",preflight_path="frozen/m3_v48_preflight.json"):
    reps=[]
    for p in sorted(glob(os.path.join(root,"**","m3_v48_backtest.json"),recursive=True)):
        with open(p,encoding="utf-8") as f:reps.append(json.load(f))
    if not reps:raise RuntimeError("No M3 V4.8 reports")
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

    m=reps[0]["manifest"];blocks=m["blocks"];total_days=int(m["block_days"])*int(m["block_count"])
    results={}
    for hid in M3_V48_HYPOTHESES:
        subset=[r for r in rows if _match(r,hid)]
        results[hid]={
            "definition":M3_V48_HYPOTHESES[hid],
            "metrics":_metrics(subset,total_days,blocks),
        }

    baseline=results["H0_BASELINE"]["metrics"]
    for hid,item in results.items():
        met=item["metrics"]
        item["vs_baseline"]={
            "retained_pct":_pct(met["entries"],baseline["entries"]),
            "delta_expectancy_r":round(float(met["expectancy_r"])-float(baseline["expectancy_r"]),5) if met.get("expectancy_r") is not None and baseline.get("expectancy_r") is not None else None,
            "delta_max_drawdown_r":round(float(met["max_drawdown_r_signal_order"])-float(baseline["max_drawdown_r_signal_order"]),5) if met.get("max_drawdown_r_signal_order") is not None and baseline.get("max_drawdown_r_signal_order") is not None else None,
        }
        item["validation_gate"]={"pass":False,"checks":{"baseline_reference":True}} if hid=="H0_BASELINE" else _validation_gate(met,baseline)

    passing=[h for h in ("H1_SHALLOW_RETEST","H2_CONTAINED_RISK","H3_COMPACT_PULLBACK","H4_ALL_THREE") if results[h]["validation_gate"]["pass"]]
    selected=max(passing,key=lambda h:float(results[h]["metrics"]["expectancy_r"])) if passing else None
    decision=f"HOLDOUT_VALIDATED:{selected}" if selected else "NO_STRUCTURAL_HYPOTHESIS_VALIDATED"

    out={
        "engine":"M3 V4.8 Pre-registered Structural Quality Validation",
        "manifest_id":next(iter(mids)),
        "period_start":m["period_start"],"period_end":m["period_end"],
        "selected_symbols":len(set(symbols)),"eligible_symbols":eligible,"data_valid":data_valid,
        "preflight":preflight,"errors":errors,
        "validation_scope":"V4.7 structural-quality hypotheses only; not untouched full-strategy OOS",
        "thresholds_frozen_before_run":m.get("thresholds"),
        "hypotheses_frozen_before_run":m.get("hypotheses"),
        "hypothesis_results":results,
        "validation_gate_policy":{
            "min_entries":M3_V48_MIN_ENTRIES,
            "required_active_blocks":M3_V48_REQUIRED_ACTIVE_BLOCKS,
            "min_positive_blocks":M3_V48_MIN_POSITIVE_BLOCKS,
            "expectancy_must_be_positive":True,
            "expectancy_must_beat_baseline":True,
            "drawdown_must_not_exceed_baseline":True,
        },
        "decision":decision,
        "selected_shadow_candidate":selected,
        "live_promotion":False,
        "research_status":"STRUCTURAL_HYPOTHESIS_HOLDOUT_COMPLETE_NOT_LIVE_PROMOTION" if data_valid else "DATA_INVALID",
        "note":"Thresholds were frozen from V4.7 before this run. The 2025-12 to 2026-04 holdout was previously used for structural-policy/base-strategy validation, so V4.8 validates the newly generated structural-quality hypotheses only. Passing yields a shadow candidate, never automatic live promotion.",
    }
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v48_analysis.json"),"w",encoding="utf-8") as f:json.dump(out,f,ensure_ascii=False,indent=2,default=str)
    with open(os.path.join(OUTPUT_DIR,"m3_v48_summary.md"),"w",encoding="utf-8") as f:
        f.write("# M3 V4.8 - Pre-registered Structural Quality Validation\n\n")
        f.write(f"Decision: **{decision}**\n\n")
        f.write(json.dumps(out,ensure_ascii=False,indent=2))
        f.write("\n")
    print(json.dumps({"decision":decision,"data_valid":data_valid,"eligible_symbols":eligible,"results":{k:v["metrics"] for k,v in results.items()},"gates":{k:v["validation_gate"] for k,v in results.items()}},ensure_ascii=False,indent=2))
    return 0 if data_valid else 2

if __name__=="__main__":
    root=sys.argv[1] if len(sys.argv)>1 else "m3v48_shards"
    pf=sys.argv[2] if len(sys.argv)>2 else "frozen/m3_v48_preflight.json"
    raise SystemExit(main(root,pf))
