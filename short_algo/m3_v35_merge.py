"""Merge M3 V3.5 temporal OOS shards and score frozen candidates."""
import json,os,sys
from glob import glob
import numpy as np
from .config import OUTPUT_DIR


def _num(x):
    try:
        y=float(x)
        return y if np.isfinite(y) else None
    except (TypeError,ValueError):
        return None


def _pct(n,d):
    return round(100.0*n/d,2) if d else None


def _q(vals,q=0.5):
    arr=[_num(x) for x in vals]
    arr=[x for x in arr if x is not None]
    return round(float(np.quantile(arr,q)),5) if arr else None


def _metrics(rows,days):
    filled=[r for r in rows if r.get("m3v35_entry_state")=="FILLED"]
    hits=[r for r in filled if int(r.get("m3v35_hit_3pct_24h") or 0)]
    return {
        "candidates":len(rows),
        "filled_entries":len(filled),
        "fill_rate_pct":_pct(len(filled),len(rows)),
        "entries_per_day":round(len(filled)/max(float(days),1.0),3),
        "hit_3pct_24h_pct":_pct(len(hits),len(filled)),
        "clean3_before_0_5_pct":_pct(sum(int(r.get("m3v35_clean3_adverse_0_5") or 0) for r in filled),len(filled)),
        "clean3_before_0_75_pct":_pct(sum(int(r.get("m3v35_clean3_adverse_0_75") or 0) for r in filled),len(filled)),
        "clean3_before_1_0_pct":_pct(sum(int(r.get("m3v35_clean3_adverse_1_0") or 0) for r in filled),len(filled)),
        "median_pre3pct_mae_pct":_q([r.get("m3v35_pre3pct_mae_pct") for r in filled]),
        "p75_pre3pct_mae_pct":_q([r.get("m3v35_pre3pct_mae_pct") for r in filled],0.75),
        "median_minutes_to_3pct_hits":_q([r.get("m3v35_minutes_to_3pct") for r in hits]),
    }


def main(root="m3v35_shards"):
    reports=[]
    for path in sorted(glob(os.path.join(root,"**","m3_v35_backtest.json"),recursive=True)):
        with open(path,encoding="utf-8") as f:
            reports.append(json.load(f))
    if not reports:
        raise RuntimeError("No M3 V3.5 reports")

    expected=max(int(r["shard_count"]) for r in reports)
    found={int(r["shard_index"]) for r in reports}
    if found!=set(range(expected)):
        raise RuntimeError(f"Incomplete shards {sorted(found)}")
    manifest_ids={r["manifest_id"] for r in reports}
    if len(manifest_ids)!=1:
        raise RuntimeError("Manifest mismatch")

    rows=[]; errors=[]; symbols=[]
    for report in reports:
        rows+=report.get("rows",[])
        errors+=report.get("errors",[])
        symbols+=report.get("selected_symbols",[])
    dedup={}
    for row in rows:
        dedup.setdefault((row.get("symbol"),row.get("signal_time")),row)
    rows=list(dedup.values())
    days=int(reports[0]["days"])
    manifest=reports[0]["manifest"]

    candidate_a=[r for r in rows if int(r.get("m3v35_candidate_a") or 0)]
    candidate_b=[r for r in rows if int(r.get("m3v35_candidate_b") or 0)]
    candidate_c=[r for r in rows if int(r.get("m3v35_candidate_c") or 0)]

    analysis={
        "candidate_a_penetration_le_0_10":_metrics(candidate_a,days),
        "candidate_b_quality_score_ge_5":_metrics(candidate_b,days),
        "candidate_c_v21_gate_wick025_lower_high":_metrics(candidate_c,days),
    }

    out={
        "engine":"M3 V3.5 Frozen Rule Temporal OOS",
        "manifest_id":next(iter(manifest_ids)),
        "period_start":manifest["period_start"],
        "period_end":manifest["period_end"],
        "development_window_start":manifest["development_window_start"],
        "embargo_days":manifest["embargo_days"],
        "days":days,
        "symbols":len(set(symbols)),
        "errors":errors,
        "analysis":analysis,
        "rows":rows,
        "research_status":"TEMPORAL_OOS_WITH_CURRENT_UNIVERSE_SELECTION_CAVEAT",
        "note":"Frozen thresholds from V3.4; fixed Entry B POI-limit; no threshold tuning in this run.",
    }

    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v35_analysis.json"),"w",encoding="utf-8") as f:
        json.dump(out,f,ensure_ascii=False,indent=2,default=str)
    with open(os.path.join(OUTPUT_DIR,"m3_v35_summary.md"),"w",encoding="utf-8") as f:
        f.write("# M3 V3.5 — Frozen Rule Temporal OOS\n\n")
        f.write(f"OOS: {manifest['period_start']} → {manifest['period_end']}\n\n")
        f.write(f"Development window begins: {manifest['development_window_start']} | embargo: {manifest['embargo_days']}d\n\n")
        for key,value in analysis.items():
            f.write(f"## {key}\n{json.dumps(value,ensure_ascii=False,indent=2)}\n\n")
        f.write("Universe is selected by current turnover, so this is temporal OOS but not a perfect survivorship-free test.\n")
    print(json.dumps(analysis,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv)>1 else "m3v35_shards"))
