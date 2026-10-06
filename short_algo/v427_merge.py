import json,math,os,sys
from collections import Counter,defaultdict
from datetime import timedelta
from glob import glob

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from .config import OUTPUT_DIR
from .v427_config import (
    V427_EMBARGO_HOURS,V427_INITIAL_TRAIN_FRACTION,V427_L2,
    V427_LEARNING_RATE,V427_MAX_ITER,V427_MAX_LEAF_NODES,
    V427_MAX_REVERSAL_PROB,V427_MIN_2R_EDGE,V427_MIN_SAMPLES_LEAF,
    V427_MIN_TRAIN_ROWS,V427_MIN_ZONE_FILL_EDGE,V427_OOS_FOLDS,
    V427_PERSISTENT_TOP_PCT,V427_PRIORITY_TOP_PCT,
    V427_REVERSAL_PENALTY_POWER,V427_ZONE_WAIT_MAX_ATR,
)
from .v427_main import CSV_FIELDS,_write_csv,_write_json
from .v427_model import (
    ENTRY_FEATURE_NAMES,REVERSAL_FEATURE_NAMES,TREND_FEATURE_NAMES,
    fit_model,predict_model,
)

XS_FIELDS=[
 "xs_weak_rank_4h","xs_weak_rank_12h","xs_weak_rank_24h",
 "xs_relative_weak_rank_4h","xs_relative_weak_rank_24h",
 "xs_weak_consistency","xs_weak_average",
]

SCORED_FIELDS=CSV_FIELDS+XS_FIELDS+[
 "oos_fold","train_rows",
 "p_4h_lower","p_12h_lower","p_24h_lower",
 "p_rel_12h_underperform","p_rel_24h_underperform",
 "p_trend_stable","p_reversal_after_short",
 "p_zone_fill","p_zone_2r_conditional",
 "trend_consensus","persistent_trend_score",
 "cross_section_rank","cross_section_rank_pct",
 "top_10pct","top_20pct","scanner_status",
]


def _load(root):
    out=[]
    for p in sorted(glob(os.path.join(root,"**","v427_backtest.json"),recursive=True)):
        with open(p,"r",encoding="utf-8") as h:
            out.append(json.load(h))
    return out


def _rate(rows,key):
    vals=[bool(r.get(key)) for r in rows if r.get(key) is not None]
    return round(sum(vals)/len(vals)*100.0,2) if vals else None


def _avg(rows,key):
    vals=[]
    for r in rows:
        try:
            v=float(r.get(key))
        except (TypeError,ValueError):
            continue
        if np.isfinite(v): vals.append(v)
    return round(float(np.mean(vals)),4) if vals else None


def _diag(rows):
    outcomes=Counter(str(r.get("zone_trade_outcome") or "NA") for r in rows)
    return {
        "count":len(rows),
        "short_rate":{
            "4h":_rate(rows,"y_4h_lower"),
            "12h":_rate(rows,"y_12h_lower"),
            "24h":_rate(rows,"y_24h_lower"),
        },
        "all3_short_pct":_rate(rows,"y_persistent_short"),
        "trend_stable_pct":_rate(rows,"y_trend_stable"),
        "relative_underperform":{
            "12h":_rate(rows,"y_rel_12h_underperform"),
            "24h":_rate(rows,"y_rel_24h_underperform"),
        },
        "reversal_after_short_pct":_rate(rows,"y_reversal_after_short"),
        "zone_fill_pct":_rate(rows,"y_zone_fill"),
        "zone_2r_unconditional_pct":_rate(rows,"y_zone_2r_success"),
        "zone_2r_conditional_pct":_rate(rows,"y_zone_2r_conditional"),
        "avg_support_room_r":_avg(rows,"v427_support_room_r"),
        "avg_trend_consensus":_avg(rows,"trend_consensus"),
        "avg_persistent_score":_avg(rows,"persistent_trend_score"),
        "avg_p2r":_avg(rows,"p_zone_2r_conditional"),
        "zone_outcomes":dict(sorted(outcomes.items())),
    }


def _auc(rows,prob,target):
    vals=[
        (float(r[prob]),1 if bool(r[target]) else 0)
        for r in rows if r.get(prob) is not None and r.get(target) is not None
    ]
    if not vals: return None
    y=np.asarray([v[1] for v in vals],dtype=int)
    if np.unique(y).size<2: return None
    p=np.asarray([v[0] for v in vals],dtype=float)
    return round(float(roc_auc_score(y,p)),5)


def _base(model):
    return float(model.get("base_rate",model.get("probability",0.5)) or 0.5)


def _cfg():
    return {
        "learning_rate":float(V427_LEARNING_RATE),
        "max_iter":int(V427_MAX_ITER),
        "max_leaf_nodes":int(V427_MAX_LEAF_NODES),
        "min_samples_leaf":int(V427_MIN_SAMPLES_LEAF),
        "l2":float(V427_L2),
    }


def _add_cross_section_features(rows):
    groups=defaultdict(list)
    for r in rows:
        groups[str(r["signal_time"])].append(r)

    pairs=[
        ("return_4h_pct","xs_weak_rank_4h"),
        ("return_12h_pct","xs_weak_rank_12h"),
        ("return_24h_pct","xs_weak_rank_24h"),
        ("relative_4h_pct","xs_relative_weak_rank_4h"),
        ("relative_24h_pct","xs_relative_weak_rank_24h"),
    ]
    for group in groups.values():
        for source,target in pairs:
            valid=[]
            for row in group:
                try:
                    v=float(row.get(source))
                    if np.isfinite(v): valid.append((v,row))
                except (TypeError,ValueError):
                    pass
            valid.sort(key=lambda x:x[0])
            n=len(valid)
            for i,(_,row) in enumerate(valid):
                # 1 = weakest / most negative, 0 = strongest.
                row[target]=round(1.0-i/float(max(n-1,1)),4)
        for row in group:
            core=[
                row.get("xs_weak_rank_4h"),
                row.get("xs_weak_rank_12h"),
                row.get("xs_weak_rank_24h"),
            ]
            vals=[float(v) for v in core if v is not None]
            row["xs_weak_consistency"]=round(min(vals),4) if vals else None
            allv=[
                row.get("xs_weak_rank_4h"),row.get("xs_weak_rank_12h"),
                row.get("xs_weak_rank_24h"),row.get("xs_relative_weak_rank_4h"),
                row.get("xs_relative_weak_rank_24h"),
            ]
            vals=[float(v) for v in allv if v is not None]
            row["xs_weak_average"]=round(float(np.mean(vals)),4) if vals else None


def _geom(values):
    vals=[max(1e-4,min(0.9999,float(v))) for v in values]
    return math.exp(sum(math.log(v) for v in vals)/len(vals))


def _rank_and_status(rows,bases):
    groups=defaultdict(list)
    for r in rows:
        groups[str(r["signal_time"])].append(r)

    for group in groups.values():
        group.sort(key=lambda r:(
            -float(r.get("persistent_trend_score") or 0.0),
            str(r.get("symbol")),
        ))
        n=len(group)
        for i,row in enumerate(group):
            pct=i/float(max(n,1))
            row["cross_section_rank"]=i+1
            row["cross_section_rank_pct"]=round(pct,4)
            row["top_10pct"]=pct<float(V427_PRIORITY_TOP_PCT)
            row["top_20pct"]=pct<float(V427_PERSISTENT_TOP_PCT)

            head_ok=all([
                float(row["p_4h_lower"])>bases["4h"],
                float(row["p_12h_lower"])>bases["12h"],
                float(row["p_24h_lower"])>bases["24h"],
                float(row["p_rel_12h_underperform"])>bases["rel12"],
                float(row["p_rel_24h_underperform"])>bases["rel24"],
                float(row["p_trend_stable"])>bases["stable"],
            ])
            reversal_ok=(
                float(row["p_reversal_after_short"])
                < min(float(V427_MAX_REVERSAL_PROB),max(0.25,bases["reversal"]))
            )
            trend_core=bool(row["top_20pct"] and head_ok and reversal_ok)

            entry_structural=bool(
                int(row.get("v427_strong_zone") or 0)==1
                and int(row.get("v427_rr2_room_ok") or 0)==1
                and not bool(row.get("severe_bottom_rule"))
            )
            fill_edge=(
                float(row.get("p_zone_fill") or 0.0)
                >= bases["fill"]+float(V427_MIN_ZONE_FILL_EDGE)
            )
            rr_edge=(
                float(row.get("p_zone_2r_conditional") or 0.0)
                >= bases["2r"]+float(V427_MIN_2R_EDGE)
            )
            dist=row.get("v427_entry_zone_distance_atr")
            dist=float(dist) if dist is not None else 999.0

            if not trend_core:
                status="WATCH"
            elif (
                bool(row.get("severe_bottom_rule"))
                or not reversal_ok
                or (
                    int(row.get("v427_near_zone") or 0)==1
                    and int(row.get("v427_rr2_room_ok") or 0)==0
                )
            ):
                status="AVOID_SHORT"
            elif (
                row["top_10pct"] and entry_structural and fill_edge and rr_edge
                and int(row.get("v427_in_zone") or 0)==1
            ):
                status="PRIORITY_SHORT"
            elif (
                row["top_10pct"] and entry_structural and fill_edge and rr_edge
                and int(row.get("v427_below_zone") or 0)==1
                and dist<=float(V427_ZONE_WAIT_MAX_ATR)
            ):
                status="WAIT_ENTRY_ZONE"
            else:
                status="PERSISTENT_SHORT"
            row["scanner_status"]=status


def _walk_forward(rows):
    ordered=sorted(rows,key=lambda r:(pd.Timestamp(r["signal_time"]),str(r.get("symbol"))))
    times=sorted({pd.Timestamp(r["signal_time"]) for r in ordered})
    initial=min(max(2,int(len(times)*float(V427_INITIAL_TRAIN_FRACTION))),len(times)-1)
    remaining=times[initial:]
    blocks=[
        list(x) for x in np.array_split(
            np.asarray(remaining,dtype=object),max(1,int(V427_OOS_FOLDS))
        ) if len(x)
    ]

    scored=[]; folds=[]; meta=[]; cfg=_cfg()
    for fold_idx,block in enumerate(blocks,start=1):
        start=pd.Timestamp(block[0]); end=pd.Timestamp(block[-1])
        cutoff=start-timedelta(hours=int(V427_EMBARGO_HOURS))
        train=[r for r in ordered if pd.Timestamp(r["signal_time"])<cutoff]
        test=[dict(r) for r in ordered if start<=pd.Timestamp(r["signal_time"])<=end]
        if len(train)<int(V427_MIN_TRAIN_ROWS) or not test:
            folds.append({"fold":fold_idx,"train_rows":len(train),"test_rows":len(test),"skipped":True})
            continue

        heads={
            "4h":fit_model(train,"y_4h_lower",TREND_FEATURE_NAMES,cfg),
            "12h":fit_model(train,"y_12h_lower",TREND_FEATURE_NAMES,cfg),
            "24h":fit_model(train,"y_24h_lower",TREND_FEATURE_NAMES,cfg),
            "rel12":fit_model(train,"y_rel_12h_underperform",TREND_FEATURE_NAMES,cfg),
            "rel24":fit_model(train,"y_rel_24h_underperform",TREND_FEATURE_NAMES,cfg),
            "stable":fit_model(train,"y_trend_stable",TREND_FEATURE_NAMES,cfg),
            "reversal":fit_model(train,"y_reversal_after_short",REVERSAL_FEATURE_NAMES,cfg),
            "fill":fit_model(train,"y_zone_fill",ENTRY_FEATURE_NAMES,cfg),
            "2r":fit_model(train,"y_zone_2r_conditional",ENTRY_FEATURE_NAMES,cfg),
        }
        pred={k:predict_model(m,test) for k,m in heads.items()}
        bases={k:_base(m) for k,m in heads.items()}

        for idx,row in enumerate(test):
            row.update({
                "oos_fold":fold_idx,"train_rows":len(train),
                "p_4h_lower":round(pred["4h"][idx],6),
                "p_12h_lower":round(pred["12h"][idx],6),
                "p_24h_lower":round(pred["24h"][idx],6),
                "p_rel_12h_underperform":round(pred["rel12"][idx],6),
                "p_rel_24h_underperform":round(pred["rel24"][idx],6),
                "p_trend_stable":round(pred["stable"][idx],6),
                "p_reversal_after_short":round(pred["reversal"][idx],6),
                "p_zone_fill":round(pred["fill"][idx],6),
                "p_zone_2r_conditional":round(pred["2r"][idx],6),
            })
            consensus=_geom([
                pred["4h"][idx],pred["12h"][idx],pred["24h"][idx],
                pred["rel12"][idx],pred["rel24"][idx],pred["stable"][idx],
            ])
            score=consensus*(
                max(1e-4,1.0-pred["reversal"][idx])
                **float(V427_REVERSAL_PENALTY_POWER)
            )
            row["trend_consensus"]=round(consensus,6)
            row["persistent_trend_score"]=round(score,6)

        _rank_and_status(test,bases)
        scored.extend(test)

        by=defaultdict(list)
        for r in test: by[str(r.get("scanner_status"))].append(r)
        folds.append({
            "fold":fold_idx,"test_start":str(start),"test_end":str(end),
            "train_rows":len(train),"test_rows":len(test),"skipped":False,
            "priority":_diag(by.get("PRIORITY_SHORT",[])),
            "wait_entry":_diag(by.get("WAIT_ENTRY_ZONE",[])),
            "persistent":_diag(by.get("PERSISTENT_SHORT",[])),
            "auc":{
                "4h":_auc(test,"p_4h_lower","y_4h_lower"),
                "12h":_auc(test,"p_12h_lower","y_12h_lower"),
                "24h":_auc(test,"p_24h_lower","y_24h_lower"),
                "rel12":_auc(test,"p_rel_12h_underperform","y_rel_12h_underperform"),
                "rel24":_auc(test,"p_rel_24h_underperform","y_rel_24h_underperform"),
                "stable":_auc(test,"p_trend_stable","y_trend_stable"),
                "reversal":_auc(test,"p_reversal_after_short","y_reversal_after_short"),
                "fill":_auc(test,"p_zone_fill","y_zone_fill"),
                "2r":_auc(test,"p_zone_2r_conditional","y_zone_2r_conditional"),
            },
        })
        meta.append({"fold":fold_idx,"train_rows":len(train),"base_rates":bases})

    scored.sort(key=lambda r:(str(r.get("signal_time")),str(r.get("symbol"))))
    return scored,folds,meta


def _summary(report):
    a=report["analysis"]
    lines=[
        "# Crypto Short V4.2.7 — Persistent Trend Consensus + 2R Entry",
        "",
        f"- Period: {report['period_start']} → {report['period_end']}",
        f"- Symbols: {report['selected_symbol_count']}",
        f"- Integrity: {'PASS' if report['manifest_integrity']['ok'] else 'FAIL'}",
        f"- Errors: {len(report.get('errors') or [])}",
        f"- Median coins/timestamp: {a['cross_section_median']}",
        "",
        "## OOS cohorts",
        "",
        "| Cohort | N | 4h ↓ | 12h ↓ | 24h ↓ | ALL 3 ↓ | Stable trend | Rel12 weak | Rel24 weak | Reversal | 2R conditional |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name,key in [
        ("All OOS","overall"),("Top10 persistent score","top10"),
        ("PERSISTENT_SHORT","PERSISTENT_SHORT"),
        ("WAIT_ENTRY_ZONE","WAIT_ENTRY_ZONE"),
        ("PRIORITY_SHORT","PRIORITY_SHORT"),
    ]:
        s=a["by_status"].get(key,_diag([])) if key not in ("overall","top10") else a[key]
        lines.append(
            f"| {name} | {s['count']} | {s['short_rate']['4h']} | {s['short_rate']['12h']} | "
            f"{s['short_rate']['24h']} | {s['all3_short_pct']} | {s['trend_stable_pct']} | "
            f"{s['relative_underperform']['12h']} | {s['relative_underperform']['24h']} | "
            f"{s['reversal_after_short_pct']} | {s['zone_2r_conditional_pct']} |"
        )
    lines += [
        "",
        "## OOS AUC",
    ]
    for k,v in a["auc"].items():
        lines.append(f"- {k}: {v}")
    lines += [
        "",
        "## Architecture check",
        "- Trend heads use no entry-zone, SL, TP or support-room geometry.",
        "- Cross-sectional weakness ranks are computed only from same-timestamp signal data.",
        "- Entry model is separate and evaluates zone fill + conditional 2R-after-fill.",
        "- PRIORITY_SHORT requires trend consensus + strong zone + >=2.2R support room + current price inside zone.",
        "- WAIT_ENTRY_ZONE uses the same trend/entry quality but forbids chasing below the preferred zone.",
        "",
    ]
    return "\n".join(lines)


def merge_reports(reports):
    if not reports: raise RuntimeError("No V4.2.7 shards")
    expected=max(int(r.get("shard_count") or 1) for r in reports)
    found={int(r.get("shard_index")) for r in reports}
    if found!=set(range(expected)): raise RuntimeError(f"Incomplete shards {sorted(found)}")
    ids={str(r.get("manifest_id")) for r in reports}
    if len(ids)!=1: raise RuntimeError("Manifest mismatch")

    first=reports[0]
    frozen=set((first.get("manifest") or {}).get("symbols") or [])
    symbols=[]; raw=[]; errors=[]
    for r in reports:
        symbols.extend(r.get("selected_symbols") or [])
        raw.extend(r.get("trades") or [])
        errors.extend(r.get("errors") or [])
    unique=set(symbols)
    integrity={
        "ok":len(reports)==expected and len(symbols)==len(unique) and unique==frozen,
        "expected_shards":expected,"found_shards":len(reports),
        "frozen_symbol_count":len(frozen),"merged_symbol_count":len(unique),
    }
    if not integrity["ok"]: raise RuntimeError(f"Integrity failed {integrity}")

    dedup={}
    for row in raw:
        dedup.setdefault((row.get("symbol"),row.get("signal_time")),row)
    raw_rows=sorted(dedup.values(),key=lambda r:(str(r.get("signal_time")),str(r.get("symbol"))))
    _add_cross_section_features(raw_rows)

    scored,folds,meta=_walk_forward(raw_rows)
    by=defaultdict(list)
    for r in scored: by[str(r.get("scanner_status") or "UNKNOWN")].append(r)
    top10=[r for r in scored if r.get("top_10pct")]

    counts=defaultdict(int)
    for r in scored: counts[str(r["signal_time"])]+=1
    median=float(np.median(list(counts.values()))) if counts else None

    auc={
        "4h":_auc(scored,"p_4h_lower","y_4h_lower"),
        "12h":_auc(scored,"p_12h_lower","y_12h_lower"),
        "24h":_auc(scored,"p_24h_lower","y_24h_lower"),
        "relative12":_auc(scored,"p_rel_12h_underperform","y_rel_12h_underperform"),
        "relative24":_auc(scored,"p_rel_24h_underperform","y_rel_24h_underperform"),
        "stability":_auc(scored,"p_trend_stable","y_trend_stable"),
        "reversal":_auc(scored,"p_reversal_after_short","y_reversal_after_short"),
        "zone_fill":_auc(scored,"p_zone_fill","y_zone_fill"),
        "zone_2r_conditional":_auc(scored,"p_zone_2r_conditional","y_zone_2r_conditional"),
    }
    analysis={
        "raw_count":len(raw_rows),"oos_count":len(scored),
        "cross_section_median":round(median,2) if median is not None else None,
        "overall":_diag(scored),"top10":_diag(top10),
        "by_status":{k:_diag(v) for k,v in sorted(by.items())},
        "auc":auc,"folds":folds,
    }
    return {
        "engine":"Crypto Short V4.2.7 Persistent Consensus",
        "manifest_id":next(iter(ids)),"manifest":first.get("manifest"),
        "manifest_integrity":integrity,
        "period_start":first.get("period_start"),"period_end":first.get("period_end"),
        "days":first.get("days"),"selected_symbols":sorted(unique),
        "selected_symbol_count":len(unique),"analysis":analysis,
        "model_meta":meta,"trades":scored,"errors":errors,
    }


def main():
    root=sys.argv[1] if len(sys.argv)>1 else "shard_outputs"
    report=merge_reports(_load(root))
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR,"v427_backtest.json"),report)
    _write_json(os.path.join(OUTPUT_DIR,"v427_analysis.json"),report["analysis"])
    _write_json(os.path.join(OUTPUT_DIR,"v427_model_meta.json"),report["model_meta"])
    _write_json(os.path.join(OUTPUT_DIR,"v427_manifest.json"),report["manifest"])
    _write_csv(
        os.path.join(OUTPUT_DIR,"v427_scored_candidates.csv"),
        report.get("trades") or [],fields=SCORED_FIELDS,
    )
    with open(os.path.join(OUTPUT_DIR,"v427_summary.md"),"w",encoding="utf-8") as h:
        h.write(_summary(report))
    print(json.dumps({
        "integrity":report["manifest_integrity"],
        "median_coins_per_timestamp":report["analysis"]["cross_section_median"],
        "priority":report["analysis"]["by_status"].get("PRIORITY_SHORT"),
        "wait_entry":report["analysis"]["by_status"].get("WAIT_ENTRY_ZONE"),
        "persistent":report["analysis"]["by_status"].get("PERSISTENT_SHORT"),
        "auc":report["analysis"]["auc"],
        "errors":len(report.get("errors") or []),
    },ensure_ascii=False,indent=2,default=str))
    return 0


if __name__=="__main__":
    sys.exit(main())
