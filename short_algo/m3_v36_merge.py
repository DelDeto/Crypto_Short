"""Merge M3 V3.6 shards and stratify frozen Candidate B by context."""
import json,os,sys
from glob import glob
import numpy as np

from .config import OUTPUT_DIR
from .m3_v36_config import (
    M3_V36_RW4_SPLITS,
    M3_V36_RW24_SPLITS,
    M3_V36_EMA20_ATR_SPLITS,
    M3_V36_EMA50_ATR_SPLITS,
    M3_V36_BREAKDOWN_ATR_SPLITS,
    M3_V36_VOLUME_EXPANSION_SPLITS,
)


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
    filled=[r for r in rows if r.get("m3v36_entry_state")=="FILLED"]
    hits=[r for r in filled if int(r.get("m3v36_hit_3pct_24h") or 0)]
    return {
        "candidates":len(rows),
        "filled_entries":len(filled),
        "fill_rate_pct":_pct(len(filled),len(rows)),
        "entries_per_day":round(len(filled)/max(float(days),1.0),3),
        "hit_3pct_24h_pct":_pct(len(hits),len(filled)),
        "clean3_before_0_5_pct":_pct(sum(int(r.get("m3v36_clean3_adverse_0_5") or 0) for r in filled),len(filled)),
        "clean3_before_0_75_pct":_pct(sum(int(r.get("m3v36_clean3_adverse_0_75") or 0) for r in filled),len(filled)),
        "clean3_before_1_0_pct":_pct(sum(int(r.get("m3v36_clean3_adverse_1_0") or 0) for r in filled),len(filled)),
        "median_pre3pct_mae_pct":_q([r.get("m3v36_pre3pct_mae_pct") for r in filled]),
        "p75_pre3pct_mae_pct":_q([r.get("m3v36_pre3pct_mae_pct") for r in filled],0.75),
        "median_minutes_to_3pct_hits":_q([r.get("m3v36_minutes_to_3pct") for r in hits]),
    }


def _le(rows,key,value):
    return [r for r in rows if _num(r.get(key)) is not None and _num(r.get(key))<=float(value)]


def _ge(rows,key,value):
    return [r for r in rows if _num(r.get(key)) is not None and _num(r.get(key))>=float(value)]


def _thresholds(rows,days,key,values,direction):
    out={}
    for value in values:
        subset=_le(rows,key,value) if direction=="le" else _ge(rows,key,value)
        out[f"{direction}_{value}"]=_metrics(subset,days)
    return out


def main(root="m3v36_shards"):
    reports=[]
    for path in sorted(glob(os.path.join(root,"**","m3_v36_backtest.json"),recursive=True)):
        with open(path,encoding="utf-8") as f:
            reports.append(json.load(f))
    if not reports:
        raise RuntimeError("No M3 V3.6 reports")

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

    analysis={
        "baseline_candidate_b":_metrics(rows,days),
        "relative_weakness_4h":_thresholds(rows,days,"m3v36_relative_weakness_4h_pct",M3_V36_RW4_SPLITS,"le"),
        "relative_weakness_24h":_thresholds(rows,days,"m3v36_relative_weakness_24h_pct",M3_V36_RW24_SPLITS,"le"),
        "distance_below_ema20_atr1h":_thresholds(rows,days,"m3v36_distance_to_ema20_atr1h",M3_V36_EMA20_ATR_SPLITS,"le"),
        "distance_below_ema50_atr1h":_thresholds(rows,days,"m3v36_distance_to_ema50_atr1h",M3_V36_EMA50_ATR_SPLITS,"le"),
        "breakdown_strength_atr1h":_thresholds(rows,days,"m3v36_breakdown_strength_atr1h",M3_V36_BREAKDOWN_ATR_SPLITS,"ge"),
        "volume_expansion_1h":_thresholds(rows,days,"m3v36_volume_expansion_1h",M3_V36_VOLUME_EXPANSION_SPLITS,"ge"),
        "market_state":{
            state:_metrics([r for r in rows if r.get("m3v36_market_state")==state],days)
            for state in ("NEUTRAL","RISK_OFF","RISK_ON_STRONG")
        },
    }

    out={
        "engine":"M3 V3.6 Regime + Relative Weakness Diagnostics",
        "manifest_id":next(iter(manifest_ids)),
        "period_start":manifest["period_start"],
        "period_end":manifest["period_end"],
        "days":days,
        "symbols":len(set(symbols)),
        "errors":errors,
        "analysis":analysis,
        "rows":rows,
        "research_status":"TEMPORAL_OOS_DIAGNOSTIC_CURRENT_UNIVERSE_CAVEAT",
        "note":"Frozen Candidate B and POI-limit entry. Buckets are diagnostics only; no threshold is promoted by this run.",
    }

    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v36_analysis.json"),"w",encoding="utf-8") as f:
        json.dump(out,f,ensure_ascii=False,indent=2,default=str)
    with open(os.path.join(OUTPUT_DIR,"m3_v36_summary.md"),"w",encoding="utf-8") as f:
        f.write("# M3 V3.6 — Regime + Relative Weakness Diagnostics\n\n")
        f.write("Frozen baseline: Candidate B (quality score >=5), Entry B POI-limit.\n\n")
        f.write("No threshold tuning or live promotion in this run.\n\n")
        for key,value in analysis.items():
            f.write(f"## {key}\n{json.dumps(value,ensure_ascii=False,indent=2)}\n\n")
    print(json.dumps(analysis,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv)>1 else "m3v36_shards"))
