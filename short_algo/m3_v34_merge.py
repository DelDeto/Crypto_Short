"""Merge M3 V3.4 shards and decompose setup quality for fixed POI-limit entry."""
import json,os,sys
from glob import glob
import numpy as np
from .config import OUTPUT_DIR
from .m3_v34_config import (
    M3_V34_PENETRATION_SPLITS,
    M3_V34_VOLUME_SPLITS,
    M3_V34_WICK_SPLITS,
    M3_V34_DISPLACEMENT_SPLITS,
    M3_V34_DISTANCE_SPLITS,
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


def _metrics(candidates,days):
    filled=[r for r in candidates if r.get("m3v34_entry_state")=="FILLED"]
    hits=[r for r in filled if int(r.get("m3v34_hit_3pct_24h") or 0)]
    return {
        "candidates":len(candidates),
        "filled_entries":len(filled),
        "fill_rate_pct":_pct(len(filled),len(candidates)),
        "entries_per_day":round(len(filled)/max(float(days),1.0),3),
        "hit_3pct_24h_pct":_pct(len(hits),len(filled)),
        "clean3_before_0_5_pct":_pct(sum(int(r.get("m3v34_clean3_adverse_0_5") or 0) for r in filled),len(filled)),
        "clean3_before_0_75_pct":_pct(sum(int(r.get("m3v34_clean3_adverse_0_75") or 0) for r in filled),len(filled)),
        "clean3_before_1_0_pct":_pct(sum(int(r.get("m3v34_clean3_adverse_1_0") or 0) for r in filled),len(filled)),
        "median_pre3pct_mae_pct":_q([r.get("m3v34_pre3pct_mae_pct") for r in filled]),
        "p75_pre3pct_mae_pct":_q([r.get("m3v34_pre3pct_mae_pct") for r in filled],0.75),
        "median_minutes_to_3pct_hits":_q([r.get("m3v34_minutes_to_3pct") for r in hits]),
    }


def _le(rows,key,v):
    return [r for r in rows if _num(r.get(key)) is not None and _num(r.get(key))<=float(v)]


def _ge(rows,key,v):
    return [r for r in rows if _num(r.get(key)) is not None and _num(r.get(key))>=float(v)]


def _named_thresholds(rows,days,key,values,direction):
    out={}
    for v in values:
        subset=_le(rows,key,v) if direction=="le" else _ge(rows,key,v)
        out[f"{direction}_{v}"]=_metrics(subset,days)
    return out


def main(root="m3v34_shards"):
    reports=[]
    for path in sorted(glob(os.path.join(root,"**","m3_v34_backtest.json"),recursive=True)):
        with open(path,encoding="utf-8") as f: reports.append(json.load(f))
    if not reports: raise RuntimeError("No M3 V3.4 reports")

    expected=max(int(r["shard_count"]) for r in reports)
    found={int(r["shard_index"]) for r in reports}
    if found!=set(range(expected)): raise RuntimeError(f"Incomplete shards {sorted(found)}")
    manifest_ids={r["manifest_id"] for r in reports}
    if len(manifest_ids)!=1: raise RuntimeError("Manifest mismatch")

    rows=[]; errors=[]; symbols=[]
    for report in reports:
        rows+=report.get("rows",[])
        errors+=report.get("errors",[])
        symbols+=report.get("selected_symbols",[])
    dedup={}
    for row in rows: dedup.setdefault((row.get("symbol"),row.get("signal_time")),row)
    rows=list(dedup.values())
    days=int(reports[0]["days"])

    penetration=_named_thresholds(rows,days,"m3v21_retest_penetration_atr15",M3_V34_PENETRATION_SPLITS,"le")
    volume=_named_thresholds(rows,days,"m3v21_retest_volume_vs_displacement",M3_V34_VOLUME_SPLITS,"le")
    wick=_named_thresholds(rows,days,"m3v21_retest_upper_wick_ratio",M3_V34_WICK_SPLITS,"ge")
    displacement=_named_thresholds(rows,days,"m3v34_displacement_body_atr15",M3_V34_DISPLACEMENT_SPLITS,"ge")
    distance=_named_thresholds(rows,days,"m3v34_base_chase_atr15",M3_V34_DISTANCE_SPLITS,"le")

    v21_full=[
        r for r in rows
        if (_num(r.get("m3v21_retest_penetration_atr15")) is not None and _num(r.get("m3v21_retest_penetration_atr15"))<=0.25)
        and (r.get("m3v21_retest_volume_vs_displacement") is None or (_num(r.get("m3v21_retest_volume_vs_displacement")) is not None and _num(r.get("m3v21_retest_volume_vs_displacement"))<=1.0))
    ]
    lower_high=[r for r in rows if int(r.get("m3v21_retest_lower_high") or 0)==1]
    wick25_lh=[r for r in lower_high if (_num(r.get("m3v21_retest_upper_wick_ratio")) or 0)>=0.25]
    tight_combo=[
        r for r in v21_full
        if int(r.get("m3v21_retest_lower_high") or 0)==1
        and (_num(r.get("m3v21_retest_upper_wick_ratio")) or 0)>=0.25
    ]

    market={}
    for state in ("NEUTRAL","RISK_OFF","RISK_ON_STRONG"):
        market[state]=_metrics([r for r in rows if r.get("m3v34_market_state")==state],days)

    quality={}
    for q in (3,4,5,6):
        quality[f"score_ge_{q}"]=_metrics([r for r in rows if int(r.get("m3v21_retest_quality_score") or 0)>=q],days)

    combos={
        "v21_full_quality_gate_pen_le_025_vol_le_1":_metrics(v21_full,days),
        "lower_high_only":_metrics(lower_high,days),
        "wick_ge_025_plus_lower_high":_metrics(wick25_lh,days),
        "v21_full_plus_wick025_lower_high":_metrics(tight_combo,days),
    }

    analysis={
        "baseline_all_core":_metrics(rows,days),
        "penetration_thresholds":penetration,
        "volume_thresholds":volume,
        "upper_wick_thresholds":wick,
        "displacement_thresholds":displacement,
        "base_chase_distance_thresholds":distance,
        "quality_score_thresholds":quality,
        "market_state":market,
        "combinations":combos,
    }

    out={
        "engine":"M3 V3.4 Setup Quality Decomposition",
        "manifest_id":next(iter(manifest_ids)),
        "days":days,
        "symbols":len(set(symbols)),
        "errors":errors,
        "analysis":analysis,
        "rows":rows,
        "research_status":"SAME_PERIOD_DEVELOPMENT_NOT_INDEPENDENT_OOS",
        "note":"Fixed Entry B POI-limit execution. Thresholds/combinations are diagnostics, not promoted rules.",
    }

    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v34_analysis.json"),"w",encoding="utf-8") as f:
        json.dump(out,f,ensure_ascii=False,indent=2,default=str)
    with open(os.path.join(OUTPUT_DIR,"m3_v34_summary.md"),"w",encoding="utf-8") as f:
        f.write("# M3 V3.4 — Setup Quality Decomposition\n\n")
        f.write("Execution fixed to Entry B: POI-limit for up to 2 bars.\n\n")
        for key,value in analysis.items():
            f.write(f"## {key}\n{json.dumps(value,ensure_ascii=False,indent=2)}\n\n")
        f.write("Same-period development only; diagnostic thresholds are not live rules.\n")

    print(json.dumps(analysis,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv)>1 else "m3v34_shards"))
