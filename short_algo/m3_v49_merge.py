"""M3 V4.9 merge: sequential forward-shadow validation of the single H1 shallow-retest rule."""
import json,os,sys,math
from glob import glob
from .config import OUTPUT_DIR
from .m3_v441_config import M3_V441_MIN_ELIGIBLE_SYMBOLS
from .m3_v46_merge import _metrics,_pct
from .m3_v49_config import (
    M3_V49_SHALLOW_RETEST_MAX_ATR15,
    M3_V49_MIN_FORWARD_DAYS,M3_V49_MIN_H1_ENTRIES,
    M3_V49_MIN_ACTIVE_BLOCKS,M3_V49_MIN_POSITIVE_BLOCK_FRACTION,
)

def _match_h1(row):
    v=row.get("m3v21_retest_penetration_atr15")
    return v is not None and float(v)<=float(M3_V49_SHALLOW_RETEST_MAX_ATR15)

def _readiness(h1,forward_days):
    active=int(h1.get("active_blocks") or 0)
    positive=int(h1.get("positive_expectancy_blocks") or 0)
    pos_frac=(positive/active) if active else 0.0
    checks={
        "min_forward_days":float(forward_days)>=float(M3_V49_MIN_FORWARD_DAYS),
        "min_h1_entries":int(h1.get("entries") or 0)>=int(M3_V49_MIN_H1_ENTRIES),
        "min_active_blocks":active>=int(M3_V49_MIN_ACTIVE_BLOCKS),
        "positive_block_fraction":pos_frac>=float(M3_V49_MIN_POSITIVE_BLOCK_FRACTION),
    }
    return {"ready":all(checks.values()),"checks":checks,"positive_block_fraction":round(pos_frac,4)}

def _edge_checks(h1,baseline):
    ci=h1.get("expectancy_bootstrap95_r") or [None,None]
    lo=ci[0] if len(ci)>0 else None
    checks={
        "expectancy_positive":h1.get("expectancy_r") is not None and float(h1["expectancy_r"])>0,
        "expectancy_beats_baseline":h1.get("expectancy_r") is not None and baseline.get("expectancy_r") is not None and float(h1["expectancy_r"])>float(baseline["expectancy_r"]),
        "drawdown_not_worse":h1.get("max_drawdown_r_signal_order") is not None and baseline.get("max_drawdown_r_signal_order") is not None and float(h1["max_drawdown_r_signal_order"])<=float(baseline["max_drawdown_r_signal_order"]),
    }
    return {
        "pass":all(checks.values()),
        "checks":checks,
        "bootstrap_ci_excludes_zero":lo is not None and float(lo)>0,
    }

def main(root="m3v49_shards",preflight_path="frozen/m3_v49_preflight.json"):
    reps=[]
    for p in sorted(glob(os.path.join(root,"**","m3_v49_backtest.json"),recursive=True)):
        with open(p,encoding="utf-8") as f:reps.append(json.load(f))
    if not reps:raise RuntimeError("No M3 V4.9 reports")
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
    blocks=m["blocks"];forward_days=float(m.get("forward_days") or 0.0)
    baseline=_metrics(rows,forward_days,blocks)
    h1_rows=[r for r in rows if _match_h1(r)]
    h1=_metrics(h1_rows,forward_days,blocks)

    readiness=_readiness(h1,forward_days)
    edge=_edge_checks(h1,baseline)
    if not readiness["ready"]:
        decision="ACCUMULATING_FORWARD_SAMPLE"
    elif edge["pass"] and edge["bootstrap_ci_excludes_zero"]:
        decision="FORWARD_SHADOW_STRONG_CONFIRMED:H1_SHALLOW_RETEST"
    elif edge["pass"]:
        decision="FORWARD_SHADOW_DIRECTIONAL_CONFIRMATION_CI_WIDE:H1_SHALLOW_RETEST"
    else:
        decision="FORWARD_SHADOW_NOT_CONFIRMED:H1_SHALLOW_RETEST"

    comparison={
        "retained_pct":_pct(h1["entries"],baseline["entries"]),
        "delta_expectancy_r":round(float(h1["expectancy_r"])-float(baseline["expectancy_r"]),5) if h1.get("expectancy_r") is not None and baseline.get("expectancy_r") is not None else None,
        "delta_max_drawdown_r":round(float(h1["max_drawdown_r_signal_order"])-float(baseline["max_drawdown_r_signal_order"]),5) if h1.get("max_drawdown_r_signal_order") is not None and baseline.get("max_drawdown_r_signal_order") is not None else None,
    }

    out={
        "engine":"M3 V4.9 Shallow Retest Sequential Forward Shadow",
        "manifest_id":next(iter(mids)),
        "period_start":m["period_start"],"period_end":m["period_end"],"forward_days":forward_days,
        "selected_symbols":len(set(symbols)),"eligible_symbols":eligible,"data_valid":data_valid,
        "preflight":preflight,"errors":errors,
        "hypothesis_frozen_before_forward_run":m.get("hypothesis"),
        "baseline":baseline,
        "h1_shallow_retest":h1,
        "h1_vs_baseline":comparison,
        "readiness_gate":readiness,
        "edge_gate":edge,
        "decision":decision,
        "live_promotion":False,
        "research_status":"FORWARD_SHADOW_RUNNING" if data_valid else "DATA_INVALID",
        "note":"V4.9 never retunes the 0.10 ATR15 threshold. The forward window expands from 2026-10-05 and is re-evaluated sequentially. Even a strong confirmation remains shadow-only until explicitly promoted in a later version.",
    }
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v49_analysis.json"),"w",encoding="utf-8") as f:json.dump(out,f,ensure_ascii=False,indent=2,default=str)
    with open(os.path.join(OUTPUT_DIR,"m3_v49_summary.md"),"w",encoding="utf-8") as f:
        f.write("# M3 V4.9 - Shallow Retest Sequential Forward Shadow\n\n")
        f.write(f"Decision: **{decision}**\n\n")
        f.write(json.dumps(out,ensure_ascii=False,indent=2))
        f.write("\n")
    print(json.dumps({
        "decision":decision,"data_valid":data_valid,"forward_days":forward_days,"eligible_symbols":eligible,
        "baseline":baseline,"h1":h1,"h1_vs_baseline":comparison,"readiness":readiness,"edge":edge,
    },ensure_ascii=False,indent=2))
    return 0 if data_valid else 2

if __name__=="__main__":
    root=sys.argv[1] if len(sys.argv)>1 else "m3v49_shards"
    pf=sys.argv[2] if len(sys.argv)>2 else "frozen/m3_v49_preflight.json"
    raise SystemExit(main(root,pf))
