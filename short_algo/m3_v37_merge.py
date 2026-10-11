"""Merge M3 V3.7 shards and score frozen context candidates."""
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
    filled=[r for r in rows if r.get("m3v37_entry_state")=="FILLED"]
    hits=[r for r in filled if int(r.get("m3v37_hit_3pct_24h") or 0)]
    return {
        "candidates":len(rows),
        "filled_entries":len(filled),
        "fill_rate_pct":_pct(len(filled),len(rows)),
        "entries_per_day":round(len(filled)/max(float(days),1.0),3),
        "hit_3pct_24h_pct":_pct(len(hits),len(filled)),
        "clean3_before_0_5_pct":_pct(sum(int(r.get("m3v37_clean3_adverse_0_5") or 0) for r in filled),len(filled)),
        "clean3_before_0_75_pct":_pct(sum(int(r.get("m3v37_clean3_adverse_0_75") or 0) for r in filled),len(filled)),
        "clean3_before_1_0_pct":_pct(sum(int(r.get("m3v37_clean3_adverse_1_0") or 0) for r in filled),len(filled)),
        "median_pre3pct_mae_pct":_q([r.get("m3v37_pre3pct_mae_pct") for r in filled]),
        "p75_pre3pct_mae_pct":_q([r.get("m3v37_pre3pct_mae_pct") for r in filled],0.75),
        "median_minutes_to_3pct_hits":_q([r.get("m3v37_minutes_to_3pct") for r in hits]),
    }


def main(root="m3v37_shards"):
    reports=[]
    for path in sorted(glob(os.path.join(root,"**","m3_v37_backtest.json"),recursive=True)):
        with open(path,encoding="utf-8") as f:
            reports.append(json.load(f))
    if not reports:
        raise RuntimeError("No M3 V3.7 reports")

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
    a=[r for r in rows if int(r.get("m3v37_candidate_a_rw24_le_m5") or 0)]
    b=[r for r in rows if int(r.get("m3v37_candidate_b_volume_ge_2") or 0)]
    c=[r for r in rows if int(r.get("m3v37_candidate_c_both") or 0)]

    analysis={
        "baseline_candidate_b":_metrics(rows,days),
        "candidate_a_rw24_le_minus5":_metrics(a,days),
        "candidate_b_volume_ge_2x":_metrics(b,days),
        "candidate_c_rw24_le_minus5_and_volume_ge_2x":_metrics(c,days),
    }

    out={
        "engine":"M3 V3.7 Frozen Context Second OOS",
        "manifest_id":next(iter(manifest_ids)),
        "period_start":manifest["period_start"],
        "period_end":manifest["period_end"],
        "prior_oos_window_start":manifest["prior_oos_window_start"],
        "prior_oos_window_end":manifest["prior_oos_window_end"],
        "days":days,
        "symbols":len(set(symbols)),
        "errors":errors,
        "analysis":analysis,
        "rows":rows,
        "research_status":"SECOND_TEMPORAL_OOS_CURRENT_UNIVERSE_SELECTION_CAVEAT",
        "note":"Frozen thresholds from V3.6; fixed Candidate-B base and POI-limit execution; no tuning in this run.",
    }

    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v37_analysis.json"),"w",encoding="utf-8") as f:
        json.dump(out,f,ensure_ascii=False,indent=2,default=str)
    with open(os.path.join(OUTPUT_DIR,"m3_v37_summary.md"),"w",encoding="utf-8") as f:
        f.write("# M3 V3.7 — Frozen Context Second OOS\n\n")
        f.write(f"OOS: {manifest['period_start']} → {manifest['period_end']}\n\n")
        f.write("Frozen rules: RW24 <= -5%, volume >= 2x, and their intersection.\n\n")
        for key,value in analysis.items():
            f.write(f"## {key}\n{json.dumps(value,ensure_ascii=False,indent=2)}\n\n")
        f.write("Current-turnover universe selection remains a survivorship/selection caveat.\n")

    print(json.dumps(analysis,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv)>1 else "m3v37_shards"))
