"""Merge M3 V3.9 shards and compare entry/stop survivability."""
import json,os,sys
from glob import glob
import numpy as np

from .config import OUTPUT_DIR
from .m3_v39_config import M3_V39_ENTRY_OFFSETS_ATR15, M3_V39_STOP_CAPS_PCT


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


def _variant_rows(setups,name):
    out=[]
    for row in setups:
        v=(row.get("m3v39_variants") or {}).get(name)
        if v is not None:
            out.append(v)
    return out


def _metrics(setups,name,days):
    vals=_variant_rows(setups,name)
    filled=[v for v in vals if v.get("fill_state")=="FILLED"]
    hits=[v for v in filled if int(v.get("hit_3pct_24h") or 0)]
    out={
        "setups":len(vals),
        "filled_entries":len(filled),
        "fill_rate_pct":_pct(len(filled),len(vals)),
        "entries_per_day":round(len(filled)/max(float(days),1.0),3),
        "hit_3pct_24h_pct":_pct(len(hits),len(filled)),
        "median_pre3pct_mae_pct":_q([v.get("pre3pct_mae_pct") for v in filled]),
        "p75_pre3pct_mae_pct":_q([v.get("pre3pct_mae_pct") for v in filled],0.75),
        "median_minutes_to_3pct_hits":_q([v.get("minutes_to_3pct") for v in hits]),
    }
    for cap in M3_V39_STOP_CAPS_PCT:
        label=str(float(cap)).replace(".","_")
        key=f"target_before_stop_{label}pct"
        out[f"{key}_pct"]=_pct(sum(int(v.get(key) or 0) for v in filled),len(filled))
    return out


def _stability(blocks):
    active=[m for m in blocks if (m.get("filled_entries") or 0)>0]
    hits=[m["hit_3pct_24h_pct"] for m in active if m.get("hit_3pct_24h_pct") is not None]
    tbs15=[m.get("target_before_stop_1_5pct_pct") for m in active if m.get("target_before_stop_1_5pct_pct") is not None]
    maes=[m["median_pre3pct_mae_pct"] for m in active if m.get("median_pre3pct_mae_pct") is not None]
    return {
        "active_blocks":len(active),
        "median_block_hit_pct":round(float(np.median(hits)),2) if hits else None,
        "min_block_hit_pct":round(float(np.min(hits)),2) if hits else None,
        "max_block_hit_pct":round(float(np.max(hits)),2) if hits else None,
        "median_block_target_before_stop_1_5pct_pct":round(float(np.median(tbs15)),2) if tbs15 else None,
        "median_block_mae_pct":round(float(np.median(maes)),5) if maes else None,
    }


def main(root="m3v39_shards"):
    reports=[]
    for path in sorted(glob(os.path.join(root,"**","m3_v39_backtest.json"),recursive=True)):
        with open(path,encoding="utf-8") as f:
            reports.append(json.load(f))
    if not reports:
        raise RuntimeError("No M3 V3.9 reports")

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
    total_days=block_days*int(manifest["block_count"])

    analysis={}
    for name in M3_V39_ENTRY_OFFSETS_ATR15:
        block_metrics=[]
        for block in manifest["blocks"]:
            subset=[r for r in rows if int(r.get("m3v39_block") or 0)==int(block["block"])]
            block_metrics.append({
                "block":int(block["block"]),
                "start":block["start"],
                "end":block["end"],
                **_metrics(subset,name,block_days),
            })
        analysis[name]={
            "offset_atr15":float(M3_V39_ENTRY_OFFSETS_ATR15[name]),
            "aggregate":_metrics(rows,name,total_days),
            "stability":_stability(block_metrics),
            "blocks":block_metrics,
        }

    out={
        "engine":"M3 V3.9 Entry Quality + Stop Survivability",
        "manifest_id":next(iter(manifest_ids)),
        "period_start":manifest["period_start"],
        "period_end":manifest["period_end"],
        "block_days":block_days,
        "block_count":manifest["block_count"],
        "symbols":len(set(symbols)),
        "errors":errors,
        "analysis":analysis,
        "research_status":"ENTRY_STOP_DIAGNOSTIC_CURRENT_UNIVERSE_SELECTION_CAVEAT",
        "note":"Frozen RW24<=-5 setup. Compares predeclared POI entry offsets and conservative target-before-stop outcomes. No live promotion.",
    }

    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v39_analysis.json"),"w",encoding="utf-8") as f:
        json.dump(out,f,ensure_ascii=False,indent=2,default=str)
    with open(os.path.join(OUTPUT_DIR,"m3_v39_summary.md"),"w",encoding="utf-8") as f:
        f.write("# M3 V3.9 — Entry Quality + Stop Survivability\n\n")
        f.write("Frozen directional gate: RW24 <= -5%. Entry variants are fixed before the run.\n\n")
        f.write("Target prints in the fill bar are not credited; stop-survivability is conservative.\n\n")
        for key,value in analysis.items():
            f.write(f"## {key}\n{json.dumps(value,ensure_ascii=False,indent=2)}\n\n")
        f.write("Current-turnover universe selection remains a survivorship/selection caveat.\n")

    print(json.dumps(analysis,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv)>1 else "m3v39_shards"))
