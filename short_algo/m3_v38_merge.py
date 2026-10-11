"""Merge M3 V3.8 shards and summarize stability across frozen windows."""
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
    filled=[r for r in rows if r.get("m3v38_entry_state")=="FILLED"]
    hits=[r for r in filled if int(r.get("m3v38_hit_3pct_24h") or 0)]
    return {
        "candidates":len(rows),
        "filled_entries":len(filled),
        "fill_rate_pct":_pct(len(filled),len(rows)),
        "entries_per_day":round(len(filled)/max(float(days),1.0),3),
        "hit_3pct_24h_pct":_pct(len(hits),len(filled)),
        "clean3_before_0_5_pct":_pct(sum(int(r.get("m3v38_clean3_adverse_0_5") or 0) for r in filled),len(filled)),
        "clean3_before_0_75_pct":_pct(sum(int(r.get("m3v38_clean3_adverse_0_75") or 0) for r in filled),len(filled)),
        "clean3_before_1_0_pct":_pct(sum(int(r.get("m3v38_clean3_adverse_1_0") or 0) for r in filled),len(filled)),
        "median_pre3pct_mae_pct":_q([r.get("m3v38_pre3pct_mae_pct") for r in filled]),
        "p75_pre3pct_mae_pct":_q([r.get("m3v38_pre3pct_mae_pct") for r in filled],0.75),
        "median_minutes_to_3pct_hits":_q([r.get("m3v38_minutes_to_3pct") for r in hits]),
    }


def _stability(block_metrics):
    active=[m for m in block_metrics if (m.get("filled_entries") or 0)>0]
    hit=[m["hit_3pct_24h_pct"] for m in active if m.get("hit_3pct_24h_pct") is not None]
    clean=[m["clean3_before_1_0_pct"] for m in active if m.get("clean3_before_1_0_pct") is not None]
    mae=[m["median_pre3pct_mae_pct"] for m in active if m.get("median_pre3pct_mae_pct") is not None]
    return {
        "active_blocks":len(active),
        "blocks_hit_ge_60pct":sum(1 for x in hit if x>=60.0),
        "median_block_hit_pct":round(float(np.median(hit)),2) if hit else None,
        "min_block_hit_pct":round(float(np.min(hit)),2) if hit else None,
        "max_block_hit_pct":round(float(np.max(hit)),2) if hit else None,
        "median_block_clean_before_1_pct":round(float(np.median(clean)),2) if clean else None,
        "median_block_mae_pct":round(float(np.median(mae)),5) if mae else None,
    }


def main(root="m3v38_shards"):
    reports=[]
    for path in sorted(glob(os.path.join(root,"**","m3_v38_backtest.json"),recursive=True)):
        with open(path,encoding="utf-8") as f:
            reports.append(json.load(f))
    if not reports:
        raise RuntimeError("No M3 V3.8 reports")

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

    manifest=reports[0]["manifest"]
    block_days=int(manifest["block_days"])

    rules={
        "baseline_candidate_b":lambda r:True,
        "candidate_a_rw24_le_minus5":lambda r:int(r.get("m3v38_candidate_a_rw24_le_m5") or 0)==1,
        "candidate_b_volume_ge_2x":lambda r:int(r.get("m3v38_candidate_b_volume_ge_2") or 0)==1,
        "candidate_c_rw24_le_minus5_and_volume_ge_2x":lambda r:int(r.get("m3v38_candidate_c_both") or 0)==1,
    }

    analysis={}
    for name,pred in rules.items():
        subset=[r for r in rows if pred(r)]
        block_metrics=[]
        for block in manifest["blocks"]:
            br=[r for r in subset if int(r.get("m3v38_block") or 0)==int(block["block"])]
            block_metrics.append({
                "block":int(block["block"]),
                "start":block["start"],
                "end":block["end"],
                **_metrics(br,block_days),
            })
        analysis[name]={
            "aggregate":_metrics(subset,block_days*len(manifest["blocks"])),
            "stability":_stability(block_metrics),
            "blocks":block_metrics,
        }

    out={
        "engine":"M3 V3.8 Multi-Window Stability",
        "manifest_id":next(iter(manifest_ids)),
        "period_start":manifest["period_start"],
        "period_end":manifest["period_end"],
        "block_days":block_days,
        "block_count":manifest["block_count"],
        "symbols":len(set(symbols)),
        "errors":errors,
        "analysis":analysis,
        "rows":rows,
        "research_status":"MULTIWINDOW_STABILITY_CURRENT_UNIVERSE_SELECTION_CAVEAT",
        "note":"Frozen rules from V3.6/V3.7. Earlier unseen windows, no threshold tuning. Current-turnover universe remains a selection/survivorship caveat.",
    }

    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v38_analysis.json"),"w",encoding="utf-8") as f:
        json.dump(out,f,ensure_ascii=False,indent=2,default=str)
    with open(os.path.join(OUTPUT_DIR,"m3_v38_summary.md"),"w",encoding="utf-8") as f:
        f.write("# M3 V3.8 — Multi-Window Stability\n\n")
        f.write(f"{manifest['block_count']} frozen blocks × {block_days} days; no threshold tuning.\n\n")
        for key,value in analysis.items():
            f.write(f"## {key}\n{json.dumps(value,ensure_ascii=False,indent=2)}\n\n")
        f.write("Current-turnover universe selection remains a survivorship/selection caveat.\n")

    print(json.dumps(analysis,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv)>1 else "m3v38_shards"))
