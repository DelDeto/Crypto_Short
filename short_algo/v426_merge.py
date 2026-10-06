import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import timedelta
from glob import glob

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from .config import OUTPUT_DIR
from .v426_config import (
    V426_EMBARGO_HOURS,
    V426_INITIAL_TRAIN_FRACTION,
    V426_L2,
    V426_LEARNING_RATE,
    V426_MAX_ITER,
    V426_MAX_LEAF_NODES,
    V426_MAX_REVERSAL_PROB,
    V426_MIN_SAMPLES_LEAF,
    V426_MIN_TRAIN_ROWS,
    V426_OOS_FOLDS,
    V426_PRIORITY_TOP_PCT,
    V426_W_24H,
    V426_W_FIRST,
    V426_W_NO_REVERSAL,
    V426_W_PERSISTENT,
    V426_W_ZONE_2R,
    V426_WATCH_TOP_PCT,
    V426_ZONE_WAIT_MAX_ATR,
)
from .v426_main import CSV_FIELDS, _write_csv, _write_json
from .v426_model import fit_model, predict_model


SCORED_FIELDS = CSV_FIELDS + [
    "oos_fold","train_rows",
    "p_persistent_short","p_24h_lower","p_zone_2r",
    "p_first_short","p_reversal_after_short",
    "persistent_train_base","zone2r_train_base",
    "quality_probability",
    "cross_section_rank","cross_section_rank_pct",
    "top_10pct","top_20pct",
    "scanner_status",
]


def _load(root):
    reports=[]
    for path in sorted(glob(
        os.path.join(root,"**","v426_backtest.json"),
        recursive=True,
    )):
        with open(path,"r",encoding="utf-8") as handle:
            reports.append(json.load(handle))
    return reports


def _avg(rows,key):
    vals=[]
    for r in rows:
        if r.get(key) is None:
            continue
        try:
            v=float(r[key])
        except (TypeError,ValueError):
            continue
        if np.isfinite(v):
            vals.append(v)
    return round(float(np.mean(vals)),4) if vals else None


def _median(rows,key):
    vals=[]
    for r in rows:
        if r.get(key) is None:
            continue
        try:
            v=float(r[key])
        except (TypeError,ValueError):
            continue
        if np.isfinite(v):
            vals.append(v)
    return round(float(np.median(vals)),4) if vals else None


def _rate(rows,key):
    vals=[bool(r.get(key)) for r in rows if r.get(key) is not None]
    return round(sum(vals)/len(vals)*100.0,2) if vals else None


def _enum_rate(rows,key,value):
    vals=[str(r.get(key)) for r in rows if r.get(key) is not None]
    if not vals:
        return None
    return round(sum(1 for x in vals if x==value)/len(vals)*100.0,2)


def _diagnostics(rows):
    outcomes=Counter(str(r.get("zone_trade_outcome") or "NA") for r in rows)
    return {
        "count":len(rows),
        "short_rate":{
            "4h_pct":_rate(rows,"y_4h_lower"),
            "12h_pct":_rate(rows,"y_12h_lower"),
            "24h_pct":_rate(rows,"y_24h_lower"),
        },
        "persistent_short_pct":_rate(rows,"y_persistent_short"),
        "first_short_pct":_rate(rows,"y_first_short"),
        "reversal_after_short_pct":_rate(rows,"y_reversal_after_short"),
        "zone_fill_pct":_rate(rows,"zone_filled"),
        "zone_2r_success_pct":_rate(rows,"y_zone_2r_success"),
        "avg_support_room_r":_avg(rows,"v426_support_room_r"),
        "avg_quality_probability":_avg(rows,"quality_probability"),
        "avg_persistent_probability":_avg(rows,"p_persistent_short"),
        "avg_zone2r_probability":_avg(rows,"p_zone_2r"),
        "avg_max_downside_24h_atr":_avg(rows,"max_downside_24h_atr"),
        "avg_max_adverse_24h_atr":_avg(rows,"max_adverse_24h_atr"),
        "median_hours_to_max_downside":_median(rows,"hours_to_max_downside"),
        "zone_outcomes":dict(sorted(outcomes.items())),
        "short_then_reverse_pct":_enum_rate(
            rows,"path_class_24h","SHORT_THEN_REVERSE"
        ),
    }


def _auc(rows,prob_key,target_key):
    vals=[
        (float(r[prob_key]),1 if bool(r[target_key]) else 0)
        for r in rows
        if r.get(prob_key) is not None and r.get(target_key) is not None
    ]
    if not vals:
        return None
    y=np.asarray([v[1] for v in vals],dtype=int)
    if np.unique(y).size<2:
        return None
    p=np.asarray([v[0] for v in vals],dtype=float)
    return round(float(roc_auc_score(y,p)),5)


def _cross_stats(rows):
    grouped=defaultdict(int)
    for r in rows:
        grouped[str(r.get("signal_time"))]+=1
    vals=list(grouped.values())
    if not vals:
        return {"timestamps":0,"mean":None,"median":None}
    return {
        "timestamps":len(vals),
        "mean":round(float(np.mean(vals)),2),
        "median":round(float(np.median(vals)),2),
        "min":int(min(vals)),
        "max":int(max(vals)),
    }


def _model_cfg():
    return {
        "learning_rate":float(V426_LEARNING_RATE),
        "max_iter":int(V426_MAX_ITER),
        "max_leaf_nodes":int(V426_MAX_LEAF_NODES),
        "min_samples_leaf":int(V426_MIN_SAMPLES_LEAF),
        "l2":float(V426_L2),
    }


def _assign_ranks(rows):
    grouped=defaultdict(list)
    for r in rows:
        grouped[str(r["signal_time"])].append(r)

    for group in grouped.values():
        group.sort(
            key=lambda r:(
                -float(r.get("quality_probability") or 0.0),
                -float(r.get("p_persistent_short") or 0.0),
                str(r.get("symbol")),
            )
        )
        n=len(group)
        for i,row in enumerate(group):
            pct=i/float(max(n,1))
            row["cross_section_rank"]=i+1
            row["cross_section_rank_pct"]=round(pct,4)
            row["top_10pct"]=pct<float(V426_PRIORITY_TOP_PCT)
            row["top_20pct"]=pct<float(V426_WATCH_TOP_PCT)

            trend_edge=(
                float(row.get("p_persistent_short") or 0.0)
                > float(row.get("persistent_train_base") or 0.0)
            )
            zone_edge=(
                float(row.get("p_zone_2r") or 0.0)
                > float(row.get("zone2r_train_base") or 0.0)
            )
            structural=bool(
                int(row.get("v426_rr2_room_ok") or 0)==1
                and int(row.get("v426_strong_zone") or 0)==1
                and not bool(row.get("severe_bottom_rule"))
                and float(row.get("p_reversal_after_short") or 1.0)
                    <= float(V426_MAX_REVERSAL_PROB)
            )
            dist=row.get("v426_entry_zone_distance_atr")
            dist=float(dist) if dist is not None else 999.0

            if (
                row["top_10pct"] and trend_edge and zone_edge and structural
                and int(row.get("v426_in_zone") or 0)==1
            ):
                status="PRIORITY_SHORT"
            elif (
                row["top_10pct"] and trend_edge and zone_edge and structural
                and int(row.get("v426_below_zone") or 0)==1
                and dist<=float(V426_ZONE_WAIT_MAX_ATR)
            ):
                status="WAIT_ENTRY_ZONE"
            elif row["top_20pct"] and trend_edge:
                status="TREND_SHORT_WATCH"
            else:
                status="WATCH"
            row["scanner_status"]=status


def _walk_forward(rows):
    ordered=sorted(
        rows,key=lambda r:(pd.Timestamp(r["signal_time"]),str(r.get("symbol")))
    )
    times=sorted({pd.Timestamp(r["signal_time"]) for r in ordered})
    if len(times)<12:
        return [],[],[]

    initial=max(2,int(len(times)*float(V426_INITIAL_TRAIN_FRACTION)))
    initial=min(initial,len(times)-1)
    remaining=times[initial:]
    blocks=[
        list(x) for x in np.array_split(
            np.asarray(remaining,dtype=object),
            max(1,int(V426_OOS_FOLDS)),
        ) if len(x)
    ]

    scored=[]
    fold_reports=[]
    model_meta=[]
    cfg=_model_cfg()

    for fold_idx,block in enumerate(blocks,start=1):
        test_start=pd.Timestamp(block[0])
        test_end=pd.Timestamp(block[-1])
        cutoff=test_start-timedelta(hours=int(V426_EMBARGO_HOURS))

        train=[r for r in ordered if pd.Timestamp(r["signal_time"])<cutoff]
        test=[
            dict(r) for r in ordered
            if test_start<=pd.Timestamp(r["signal_time"])<=test_end
        ]

        if len(train)<int(V426_MIN_TRAIN_ROWS) or not test:
            fold_reports.append({
                "fold":fold_idx,"train_rows":len(train),
                "test_rows":len(test),"skipped":True,
            })
            continue

        mp=fit_model(train,"y_persistent_short",cfg)
        m24=fit_model(train,"y_24h_lower",cfg)
        m2r=fit_model(train,"y_zone_2r_success",cfg)
        mf=fit_model(train,"y_first_short",cfg)
        mr=fit_model(train,"y_reversal_after_short",cfg)

        pp=predict_model(mp,test)
        p24=predict_model(m24,test)
        p2r=predict_model(m2r,test)
        pf=predict_model(mf,test)
        pr=predict_model(mr,test)

        total=(
            float(V426_W_PERSISTENT)+float(V426_W_ZONE_2R)
            +float(V426_W_FIRST)+float(V426_W_24H)
            +float(V426_W_NO_REVERSAL)
        )
        base_p=float(mp.get("base_rate",mp.get("probability",0.0)) or 0.0)
        base_2r=float(m2r.get("base_rate",m2r.get("probability",0.0)) or 0.0)

        for row,a,b,c,d,e in zip(test,pp,p24,p2r,pf,pr):
            q=(
                float(V426_W_PERSISTENT)*a
                +float(V426_W_ZONE_2R)*c
                +float(V426_W_FIRST)*d
                +float(V426_W_24H)*b
                +float(V426_W_NO_REVERSAL)*(1.0-e)
            )/max(total,1e-12)
            row.update({
                "oos_fold":fold_idx,
                "train_rows":len(train),
                "p_persistent_short":round(float(a),6),
                "p_24h_lower":round(float(b),6),
                "p_zone_2r":round(float(c),6),
                "p_first_short":round(float(d),6),
                "p_reversal_after_short":round(float(e),6),
                "persistent_train_base":round(base_p,6),
                "zone2r_train_base":round(base_2r,6),
                "quality_probability":round(float(q),6),
            })

        _assign_ranks(test)
        scored.extend(test)

        priority=[r for r in test if r.get("scanner_status")=="PRIORITY_SHORT"]
        wait=[r for r in test if r.get("scanner_status")=="WAIT_ENTRY_ZONE"]
        top10=[r for r in test if r.get("top_10pct")]

        fold_reports.append({
            "fold":fold_idx,
            "test_start":str(test_start),
            "test_end":str(test_end),
            "train_rows":len(train),
            "test_rows":len(test),
            "cross_section":_cross_stats(test),
            "all":_diagnostics(test),
            "top10":_diagnostics(top10),
            "priority":_diagnostics(priority),
            "wait_entry":_diagnostics(wait),
            "auc":{
                "persistent":_auc(test,"p_persistent_short","y_persistent_short"),
                "24h":_auc(test,"p_24h_lower","y_24h_lower"),
                "zone2r":_auc(test,"p_zone_2r","y_zone_2r_success"),
                "first":_auc(test,"p_first_short","y_first_short"),
                "reversal":_auc(test,"p_reversal_after_short","y_reversal_after_short"),
            },
        })

        model_meta.append({
            "fold":fold_idx,
            "test_start":str(test_start),
            "test_end":str(test_end),
            "train_rows":len(train),
            "base_rates":{
                "persistent":base_p,
                "zone2r":base_2r,
                "24h":float(m24.get("base_rate",m24.get("probability",0.0)) or 0.0),
                "first":float(mf.get("base_rate",mf.get("probability",0.0)) or 0.0),
                "reversal":float(mr.get("base_rate",mr.get("probability",0.0)) or 0.0),
            },
        })

    scored.sort(key=lambda r:(str(r.get("signal_time")),str(r.get("symbol"))))
    return scored,fold_reports,model_meta


def _summary_md(report):
    a=report["analysis"]
    cohorts=[
        ("All OOS",a["overall_oos"]),
        ("Top 10%",a["top10"]),
        ("TREND_SHORT_WATCH",a["by_status"].get("TREND_SHORT_WATCH",_diagnostics([]))),
        ("WAIT_ENTRY_ZONE",a["by_status"].get("WAIT_ENTRY_ZONE",_diagnostics([]))),
        ("PRIORITY_SHORT",a["by_status"].get("PRIORITY_SHORT",_diagnostics([]))),
    ]
    lines=[
        "# Crypto Short V4.2.6 — Persistent Trend + 2R Zone",
        "",
        f"- Manifest: {report.get('manifest_id')}",
        f"- Period: {report.get('period_start')} → {report.get('period_end')}",
        f"- Frozen symbols: {report.get('selected_symbol_count')}",
        f"- Integrity: {'PASS' if report['manifest_integrity']['ok'] else 'FAIL'}",
        f"- Errors: {len(report.get('errors') or [])}",
        f"- Coins/timestamp median: {a['cross_section']['median']}",
        "",
        "## OOS directional + RR quality",
        "",
        "| Cohort | N | 4h ↓ | 12h ↓ | 24h ↓ | ALL 3 ↓ | First short | Zone fill | 2R success | Reversal after short |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name,s in cohorts:
        lines.append(
            f"| {name} | {s['count']} | {s['short_rate']['4h_pct']} | "
            f"{s['short_rate']['12h_pct']} | {s['short_rate']['24h_pct']} | "
            f"{s['persistent_short_pct']} | {s['first_short_pct']} | "
            f"{s['zone_fill_pct']} | {s['zone_2r_success_pct']} | "
            f"{s['reversal_after_short_pct']} |"
        )

    lines += [
        "",
        "## Fold stability — PRIORITY_SHORT",
        "",
        "| Fold | N | 4h ↓ | 12h ↓ | 24h ↓ | ALL 3 ↓ | 2R success |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for f in a["folds"]:
        if f.get("skipped"):
            continue
        s=f["priority"]
        lines.append(
            f"| {f['fold']} | {s['count']} | {s['short_rate']['4h_pct']} | "
            f"{s['short_rate']['12h_pct']} | {s['short_rate']['24h_pct']} | "
            f"{s['persistent_short_pct']} | {s['zone_2r_success_pct']} |"
        )

    lines += [
        "",
        "## OOS AUC",
        f"- Persistent 4h+12h+24h: {a['auc']['persistent']}",
        f"- 24h lower: {a['auc']['24h']}",
        f"- Zone 2R before SL: {a['auc']['zone2r']}",
        f"- First Short move: {a['auc']['first']}",
        f"- Reversal risk: {a['auc']['reversal']}",
        "",
        "## Rule",
        "- PRIORITY_SHORT = top-ranked persistent trend + strong entry zone + currently inside zone + known support room >= 2R + acceptable reversal risk.",
        "- WAIT_ENTRY_ZONE = same structural quality but price is still below the preferred retracement zone; do not chase.",
        "- TP reference remains 2R; the user controls actual execution.",
        "",
    ]
    return "\n".join(lines)


def merge_reports(reports):
    if not reports:
        raise RuntimeError("No V4.2.6 shard reports found")

    expected=max(int(r.get("shard_count") or 1) for r in reports)
    found={int(r.get("shard_index")) for r in reports}
    if found!=set(range(expected)):
        raise RuntimeError(f"Incomplete V4.2.6 shards: {sorted(found)}")

    ids={str(r.get("manifest_id")) for r in reports}
    if len(ids)!=1:
        raise RuntimeError("V4.2.6 manifest mismatch")

    first=reports[0]
    frozen=set((first.get("manifest") or {}).get("symbols") or [])
    symbols=[]
    raw=[]
    errors=[]
    for r in reports:
        symbols.extend(r.get("selected_symbols") or [])
        raw.extend(r.get("trades") or [])
        errors.extend(r.get("errors") or [])
    unique=set(symbols)

    integrity={
        "ok":len(symbols)==len(unique) and unique==frozen and len(reports)==expected,
        "expected_shards":expected,
        "found_shards":len(reports),
        "frozen_symbol_count":len(frozen),
        "merged_symbol_count":len(unique),
    }
    if not integrity["ok"]:
        raise RuntimeError(f"V4.2.6 integrity failed: {integrity}")

    dedup={}
    for row in raw:
        dedup.setdefault((row.get("symbol"),row.get("signal_time")),row)
    raw_rows=sorted(
        dedup.values(),
        key=lambda r:(str(r.get("signal_time")),str(r.get("symbol"))),
    )

    scored,folds,meta=_walk_forward(raw_rows)
    by_status=defaultdict(list)
    for row in scored:
        by_status[str(row.get("scanner_status") or "UNKNOWN")].append(row)

    top10=[r for r in scored if r.get("top_10pct")]
    analysis={
        "raw_count":len(raw_rows),
        "oos_count":len(scored),
        "cross_section":_cross_stats(scored),
        "overall_oos":_diagnostics(scored),
        "top10":_diagnostics(top10),
        "by_status":{k:_diagnostics(v) for k,v in sorted(by_status.items())},
        "auc":{
            "persistent":_auc(scored,"p_persistent_short","y_persistent_short"),
            "24h":_auc(scored,"p_24h_lower","y_24h_lower"),
            "zone2r":_auc(scored,"p_zone_2r","y_zone_2r_success"),
            "first":_auc(scored,"p_first_short","y_first_short"),
            "reversal":_auc(scored,"p_reversal_after_short","y_reversal_after_short"),
        },
        "folds":folds,
    }

    return {
        "engine":"Crypto Short V4.2.6 Persistent Trend + 2R Zone",
        "manifest_id":next(iter(ids)),
        "manifest":first.get("manifest"),
        "manifest_integrity":integrity,
        "period_start":first.get("period_start"),
        "period_end":first.get("period_end"),
        "days":first.get("days"),
        "selected_symbols":sorted(unique),
        "selected_symbol_count":len(unique),
        "analysis":analysis,
        "model_meta":meta,
        "trades":scored,
        "errors":errors,
    }


def main():
    root=sys.argv[1] if len(sys.argv)>1 else "shard_outputs"
    report=merge_reports(_load(root))
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR,"v426_backtest.json"),report)
    _write_json(os.path.join(OUTPUT_DIR,"v426_analysis.json"),report["analysis"])
    _write_json(os.path.join(OUTPUT_DIR,"v426_model_meta.json"),report["model_meta"])
    _write_json(os.path.join(OUTPUT_DIR,"v426_manifest.json"),report["manifest"])
    _write_csv(
        os.path.join(OUTPUT_DIR,"v426_scored_candidates.csv"),
        report.get("trades") or [],
        fields=SCORED_FIELDS,
    )
    with open(os.path.join(OUTPUT_DIR,"v426_summary.md"),"w",encoding="utf-8") as h:
        h.write(_summary_md(report))
    print(json.dumps({
        "manifest_id":report.get("manifest_id"),
        "integrity":report.get("manifest_integrity"),
        "cross_section":report["analysis"]["cross_section"],
        "priority":report["analysis"]["by_status"].get("PRIORITY_SHORT"),
        "errors":len(report.get("errors") or []),
    },ensure_ascii=False,indent=2,default=str))
    return 0


if __name__=="__main__":
    sys.exit(main())
