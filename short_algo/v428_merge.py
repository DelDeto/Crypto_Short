import json,math,os,sys
from collections import Counter,defaultdict
from datetime import timedelta
from glob import glob

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from .config import OUTPUT_DIR
from .v428_config import (
    V428_EMBARGO_HOURS,V428_EXHAUST_EMA_DISTANCE_ATR,
    V428_EXHAUST_FAST_DROP_ATR,V428_EXHAUST_LOW_DISTANCE_ATR,
    V428_EXTREME_WEAK_RANK,V428_INITIAL_TRAIN_FRACTION,
    V428_L2,V428_LEARNING_RATE,V428_MAX_ITER,V428_MAX_LEAF_NODES,
    V428_MAX_REVERSAL_PROB,V428_MIN_SAMPLES_LEAF,V428_MIN_TRAIN_ROWS,
    V428_OOS_FOLDS,V428_PERSISTENT_TOP_PCT,V428_PRIORITY_TOP_PCT,
    V428_RECOVERY_REL_1H_PCT,V428_RECOVERY_REL_3H_PCT,
    V428_REVERSAL_PENALTY_POWER,V428_ZONE_WAIT_MAX_ATR,
)
from .v428_main import CSV_FIELDS,_write_csv,_write_json
from .v428_model import (
    ENTRY_FEATURE_NAMES,REVERSAL_FEATURE_NAMES,TREND_FEATURE_NAMES,
    fit_model,predict_model,
)

XS_PHASE_FIELDS=[
    "xs_weak_rank_4h","xs_weak_rank_12h","xs_weak_rank_24h",
    "xs_relative_weak_rank_4h","xs_relative_weak_rank_24h",
    "xs_weak_consistency","xs_weak_average",
    "v428_structure_score","v428_exhaustion_score","v428_recovery_score",
    "v428_fast_drop_atr_proxy","v428_extreme_weakness",
    "v428_trend_phase","v428_phase_early","v428_phase_mature",
    "v428_phase_exhausted","v428_phase_recovery",
]

SCORED_FIELDS=CSV_FIELDS+XS_PHASE_FIELDS+[
    "oos_fold","train_rows",
    "p_4h_lower","p_12h_lower","p_24h_lower",
    "p_rel_12h_underperform","p_rel_24h_underperform",
    "p_trend_stable","p_reversal_after_short",
    "p_confirmed_2r",
    "direction_consensus","context_consensus","persistent_trend_score",
    "cross_section_rank","cross_section_rank_pct",
    "top_10pct","top_20pct","scanner_status",
]


def _load(root):
    out=[]
    for path in sorted(glob(
        os.path.join(root,"**","v428_backtest.json"),recursive=True
    )):
        with open(path,"r",encoding="utf-8") as h:
            out.append(json.load(h))
    return out


def _rate(rows,key):
    vals=[bool(r.get(key)) for r in rows if r.get(key) is not None]
    return round(sum(vals)/len(vals)*100.0,2) if vals else None


def _avg(rows,key):
    vals=[]
    for r in rows:
        try:
            value=float(r.get(key))
        except (TypeError,ValueError):
            continue
        if np.isfinite(value):
            vals.append(value)
    return round(float(np.mean(vals)),4) if vals else None


def _diag(rows):
    outcomes=Counter(
        str(r.get("confirmed_trade_outcome") or "NA")
        for r in rows
    )
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
        "entry_confirmed_pct":_rate(rows,"v428_entry_confirmed"),
        "confirmed_2r_success_pct":_rate(rows,"y_confirmed_2r_success"),
        "avg_confirm_support_room_r":_avg(rows,"v428_confirm_support_room_r"),
        "avg_direction_consensus":_avg(rows,"direction_consensus"),
        "avg_context_consensus":_avg(rows,"context_consensus"),
        "avg_persistent_score":_avg(rows,"persistent_trend_score"),
        "avg_p_confirmed_2r":_avg(rows,"p_confirmed_2r"),
        "confirmed_outcomes":dict(sorted(outcomes.items())),
    }


def _auc(rows,prob,target):
    vals=[
        (float(r[prob]),1 if bool(r[target]) else 0)
        for r in rows
        if r.get(prob) is not None and r.get(target) is not None
    ]
    if not vals:
        return None
    y=np.asarray([v[1] for v in vals],dtype=int)
    if np.unique(y).size<2:
        return None
    p=np.asarray([v[0] for v in vals],dtype=float)
    return round(float(roc_auc_score(y,p)),5)


def _base(model):
    return float(
        model.get("base_rate",model.get("probability",0.5)) or 0.5
    )


def _cfg():
    return {
        "learning_rate":float(V428_LEARNING_RATE),
        "max_iter":int(V428_MAX_ITER),
        "max_leaf_nodes":int(V428_MAX_LEAF_NODES),
        "min_samples_leaf":int(V428_MIN_SAMPLES_LEAF),
        "l2":float(V428_L2),
    }


def _geom(values):
    vals=[
        max(1e-4,min(0.9999,float(v)))
        for v in values
    ]
    return math.exp(sum(math.log(v) for v in vals)/len(vals))


def _add_cross_section_and_phase(rows):
    groups=defaultdict(list)
    for row in rows:
        groups[str(row["signal_time"])].append(row)

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
                    value=float(row.get(source))
                    if np.isfinite(value):
                        valid.append((value,row))
                except (TypeError,ValueError):
                    pass
            valid.sort(key=lambda x:x[0])
            n=len(valid)
            for i,(_,row) in enumerate(valid):
                row[target]=round(
                    1.0-i/float(max(n-1,1)),4
                )

        for row in group:
            weakness=[
                row.get("xs_weak_rank_4h"),
                row.get("xs_weak_rank_12h"),
                row.get("xs_weak_rank_24h"),
            ]
            vals=[float(v) for v in weakness if v is not None]
            row["xs_weak_consistency"]=(
                round(min(vals),4) if vals else None
            )
            all_weak=[
                row.get("xs_weak_rank_4h"),
                row.get("xs_weak_rank_12h"),
                row.get("xs_weak_rank_24h"),
                row.get("xs_relative_weak_rank_4h"),
                row.get("xs_relative_weak_rank_24h"),
            ]
            vals=[float(v) for v in all_weak if v is not None]
            weak_avg=float(np.mean(vals)) if vals else 0.5
            row["xs_weak_average"]=round(weak_avg,4)

            structure=0.0
            structure+=2.0*int(bool(row.get("s4_ema_bear")))
            structure+=2.0*int(bool(row.get("s4_lower_high")))
            structure+=1.0*int(bool(row.get("s4_lower_low")))
            structure+=1.0*int(bool(row.get("s1_ema_bear")))
            structure+=1.0*int(bool(row.get("s1_lower_high")))
            structure+=0.5*int(bool(row.get("s1_lower_low")))
            structure+=1.0*int(bool(row.get("breakdown_detected")))
            structure+=0.5*int(bool(row.get("bearish_rejection")))

            atr_pct=max(
                abs(float(row.get("atr_pct_1h") or 0.0)),0.05
            )
            fast_drop=max(
                0.0,
                -float(row.get("return_3h_pct") or 0.0)/atr_pct,
            )

            exhaustion=0.0
            if bool(row.get("severe_bottom_rule")):
                exhaustion+=3.0
            if (
                float(row.get("distance_12h_low_atr") or 99.0)
                <float(V428_EXHAUST_LOW_DISTANCE_ATR)
            ):
                exhaustion+=2.0
            if (
                float(row.get("ema20_distance_atr") or 0.0)
                >float(V428_EXHAUST_EMA_DISTANCE_ATR)
            ):
                exhaustion+=2.0
            if fast_drop>float(V428_EXHAUST_FAST_DROP_ATR):
                exhaustion+=2.0
            if float(row.get("anti_bottom_total") or 0.0)>=4.0:
                exhaustion+=1.0
            if weak_avg>=float(V428_EXTREME_WEAK_RANK):
                exhaustion+=1.0
            if float(row.get("range_position_12h") or 1.0)<=0.10:
                exhaustion+=1.0

            recovery=0.0
            if bool(row.get("reclaim_seen")):
                recovery+=3.0
            if (
                float(row.get("relative_recovery_1h_pct") or 0.0)
                >=float(V428_RECOVERY_REL_1H_PCT)
            ):
                recovery+=2.0
            if (
                float(row.get("relative_recovery_3h_pct") or 0.0)
                >=float(V428_RECOVERY_REL_3H_PCT)
            ):
                recovery+=2.0
            if float(row.get("rebound_from_break_low_atr") or 0.0)>=1.0:
                recovery+=1.0
            if int(row.get("market_risk_on") or 0)==1:
                recovery+=0.5

            age=float(row.get("breakdown_age_1h") or 99.0)
            fresh_break=bool(
                int(row.get("breakdown_detected") or 0)==1
                and age<=8.0
            )

            if recovery>=4.0:
                phase="RECOVERY_RECLAIM"
            elif exhaustion>=5.0:
                phase="EXHAUSTED_DOWNTREND"
            elif (
                structure>=4.0
                and fresh_break
                and exhaustion<=2.0
                and recovery<=2.0
            ):
                phase="EARLY_DOWNTREND"
            elif (
                structure>=5.0
                and exhaustion<=4.0
                and recovery<=2.0
            ):
                phase="MATURE_DOWNTREND"
            else:
                phase="UNCONFIRMED"

            row["v428_structure_score"]=round(structure,3)
            row["v428_exhaustion_score"]=round(exhaustion,3)
            row["v428_recovery_score"]=round(recovery,3)
            row["v428_fast_drop_atr_proxy"]=round(fast_drop,4)
            row["v428_extreme_weakness"]=int(
                weak_avg>=float(V428_EXTREME_WEAK_RANK)
            )
            row["v428_trend_phase"]=phase
            row["v428_phase_early"]=int(phase=="EARLY_DOWNTREND")
            row["v428_phase_mature"]=int(phase=="MATURE_DOWNTREND")
            row["v428_phase_exhausted"]=int(
                phase=="EXHAUSTED_DOWNTREND"
            )
            row["v428_phase_recovery"]=int(
                phase=="RECOVERY_RECLAIM"
            )


def _rank_and_status(rows,bases):
    groups=defaultdict(list)
    for row in rows:
        groups[str(row["signal_time"])].append(row)

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
            row["top_10pct"]=pct<float(V428_PRIORITY_TOP_PCT)
            row["top_20pct"]=pct<float(V428_PERSISTENT_TOP_PCT)

            direction_ok=all([
                float(row["p_4h_lower"])>bases["4h"],
                float(row["p_12h_lower"])>bases["12h"],
                float(row["p_24h_lower"])>bases["24h"],
            ])
            support_votes=sum([
                float(row["p_rel_12h_underperform"])>bases["rel12"],
                float(row["p_rel_24h_underperform"])>bases["rel24"],
                float(row["p_trend_stable"])>bases["stable"],
            ])
            phase_ok=str(row.get("v428_trend_phase")) in (
                "EARLY_DOWNTREND","MATURE_DOWNTREND"
            )
            reversal_limit=min(
                float(V428_MAX_REVERSAL_PROB),
                max(0.25,bases["reversal"]),
            )
            reversal_ok=(
                float(row["p_reversal_after_short"])
                <reversal_limit
            )
            trend_core=bool(
                row["top_20pct"]
                and direction_ok
                and support_votes>=2
                and phase_ok
                and reversal_ok
            )

            strong_zone=int(row.get("v428_strong_zone") or 0)==1
            confirmed=int(row.get("v428_entry_confirmed") or 0)==1
            rr_room=int(row.get("v428_confirm_rr2_room_ok") or 0)==1
            p2r=float(row.get("p_confirmed_2r") or 0.0)
            p2r_ok=p2r>=bases["2r"]
            touched=int(row.get("v428_zone_touched_recent") or 0)==1
            reclaimed=int(row.get("v428_reclaim_after_touch") or 0)==1
            below=int(row.get("v428_below_zone") or 0)==1
            dist=row.get("v428_entry_zone_distance_atr")
            dist=float(dist) if dist is not None else 999.0

            phase=str(row.get("v428_trend_phase") or "UNCONFIRMED")
            if not trend_core:
                if (
                    row["top_20pct"]
                    and phase in ("EXHAUSTED_DOWNTREND","RECOVERY_RECLAIM")
                ):
                    status="AVOID_SHORT"
                else:
                    status="WATCH"
            elif bool(row.get("severe_bottom_rule")) or reclaimed:
                status="AVOID_SHORT"
            elif (
                row["top_10pct"]
                and strong_zone
                and confirmed
                and rr_room
                and p2r_ok
            ):
                status="PRIORITY_SHORT"
            elif confirmed and not rr_room:
                status="AVOID_SHORT"
            elif strong_zone and touched and not confirmed:
                status="ZONE_TOUCHED_WAIT_CONFIRMATION"
            elif (
                strong_zone
                and below
                and not touched
                and dist<=float(V428_ZONE_WAIT_MAX_ATR)
            ):
                status="WAIT_ENTRY_ZONE"
            else:
                status="PERSISTENT_SHORT"
            row["scanner_status"]=status


def _walk_forward(rows):
    ordered=sorted(
        rows,
        key=lambda r:(pd.Timestamp(r["signal_time"]),str(r.get("symbol")))
    )
    times=sorted({pd.Timestamp(r["signal_time"]) for r in ordered})
    if len(times)<12:
        return [],[],[]

    initial=min(
        max(2,int(len(times)*float(V428_INITIAL_TRAIN_FRACTION))),
        len(times)-1,
    )
    remaining=times[initial:]
    blocks=[
        list(x)
        for x in np.array_split(
            np.asarray(remaining,dtype=object),
            max(1,int(V428_OOS_FOLDS)),
        )
        if len(x)
    ]

    scored=[]; folds=[]; meta=[]; cfg=_cfg()
    for fold_idx,block in enumerate(blocks,start=1):
        test_start=pd.Timestamp(block[0])
        test_end=pd.Timestamp(block[-1])
        cutoff=test_start-timedelta(hours=int(V428_EMBARGO_HOURS))

        train=[
            r for r in ordered
            if pd.Timestamp(r["signal_time"])<cutoff
        ]
        test=[
            dict(r) for r in ordered
            if test_start<=pd.Timestamp(r["signal_time"])<=test_end
        ]
        if len(train)<int(V428_MIN_TRAIN_ROWS) or not test:
            folds.append({
                "fold":fold_idx,"train_rows":len(train),
                "test_rows":len(test),"skipped":True,
            })
            continue

        heads={
            "4h":fit_model(train,"y_4h_lower",TREND_FEATURE_NAMES,cfg),
            "12h":fit_model(train,"y_12h_lower",TREND_FEATURE_NAMES,cfg),
            "24h":fit_model(train,"y_24h_lower",TREND_FEATURE_NAMES,cfg),
            "rel12":fit_model(
                train,"y_rel_12h_underperform",TREND_FEATURE_NAMES,cfg
            ),
            "rel24":fit_model(
                train,"y_rel_24h_underperform",TREND_FEATURE_NAMES,cfg
            ),
            "stable":fit_model(
                train,"y_trend_stable",TREND_FEATURE_NAMES,cfg
            ),
            "reversal":fit_model(
                train,"y_reversal_after_short",REVERSAL_FEATURE_NAMES,cfg
            ),
            "2r":fit_model(
                train,"y_confirmed_2r_success",ENTRY_FEATURE_NAMES,cfg
            ),
        }
        pred={key:predict_model(model,test) for key,model in heads.items()}
        bases={key:_base(model) for key,model in heads.items()}

        for idx,row in enumerate(test):
            row.update({
                "oos_fold":fold_idx,
                "train_rows":len(train),
                "p_4h_lower":round(pred["4h"][idx],6),
                "p_12h_lower":round(pred["12h"][idx],6),
                "p_24h_lower":round(pred["24h"][idx],6),
                "p_rel_12h_underperform":round(pred["rel12"][idx],6),
                "p_rel_24h_underperform":round(pred["rel24"][idx],6),
                "p_trend_stable":round(pred["stable"][idx],6),
                "p_reversal_after_short":round(pred["reversal"][idx],6),
                "p_confirmed_2r":round(pred["2r"][idx],6),
            })

            direction=_geom([
                pred["4h"][idx],pred["12h"][idx],pred["24h"][idx]
            ])
            context=_geom([
                pred["rel12"][idx],pred["rel24"][idx],pred["stable"][idx]
            ])
            consensus=(
                direction**0.70
                *context**0.30
            )
            score=consensus*(
                max(1e-4,1.0-pred["reversal"][idx])
                **float(V428_REVERSAL_PENALTY_POWER)
            )
            row["direction_consensus"]=round(direction,6)
            row["context_consensus"]=round(context,6)
            row["persistent_trend_score"]=round(score,6)

        _rank_and_status(test,bases)
        scored.extend(test)

        by=defaultdict(list)
        for row in test:
            by[str(row.get("scanner_status"))].append(row)

        folds.append({
            "fold":fold_idx,
            "test_start":str(test_start),
            "test_end":str(test_end),
            "train_rows":len(train),
            "test_rows":len(test),
            "skipped":False,
            "priority":_diag(by.get("PRIORITY_SHORT",[])),
            "wait_entry":_diag(by.get("WAIT_ENTRY_ZONE",[])),
            "wait_confirm":_diag(
                by.get("ZONE_TOUCHED_WAIT_CONFIRMATION",[])
            ),
            "persistent":_diag(by.get("PERSISTENT_SHORT",[])),
            "auc":{
                "4h":_auc(test,"p_4h_lower","y_4h_lower"),
                "12h":_auc(test,"p_12h_lower","y_12h_lower"),
                "24h":_auc(test,"p_24h_lower","y_24h_lower"),
                "rel12":_auc(
                    test,"p_rel_12h_underperform",
                    "y_rel_12h_underperform"
                ),
                "rel24":_auc(
                    test,"p_rel_24h_underperform",
                    "y_rel_24h_underperform"
                ),
                "stable":_auc(
                    test,"p_trend_stable","y_trend_stable"
                ),
                "reversal":_auc(
                    test,"p_reversal_after_short",
                    "y_reversal_after_short"
                ),
                "confirmed2r":_auc(
                    test,"p_confirmed_2r",
                    "y_confirmed_2r_success"
                ),
            },
        })
        meta.append({
            "fold":fold_idx,
            "train_rows":len(train),
            "base_rates":bases,
            "confirmed_entry_train_n":heads["2r"].get("train_n"),
        })

    scored.sort(
        key=lambda r:(str(r.get("signal_time")),str(r.get("symbol")))
    )
    return scored,folds,meta


def _summary(report):
    a=report["analysis"]
    lines=[
        "# Crypto Short V4.2.8 — Trend Phase + Confirmed Zone Rejection",
        "",
        f"- Period: {report['period_start']} → {report['period_end']}",
        f"- Symbols: {report['selected_symbol_count']}",
        f"- Integrity: {'PASS' if report['manifest_integrity']['ok'] else 'FAIL'}",
        f"- Errors: {len(report.get('errors') or [])}",
        f"- Median coins/timestamp: {a['cross_section_median']}",
        "",
        "## OOS cohorts",
        "",
        "| Cohort | N | 4h ↓ | 12h ↓ | 24h ↓ | ALL 3 ↓ | Stable | Reversal | Confirmed entry | Confirmed 2R |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    cohorts=[
        ("All OOS",a["overall"]),
        ("Top10 trend",a["top10"]),
        ("PERSISTENT_SHORT",a["by_status"].get("PERSISTENT_SHORT",_diag([]))),
        ("WAIT_ENTRY_ZONE",a["by_status"].get("WAIT_ENTRY_ZONE",_diag([]))),
        ("ZONE_TOUCHED_WAIT_CONFIRMATION",a["by_status"].get("ZONE_TOUCHED_WAIT_CONFIRMATION",_diag([]))),
        ("PRIORITY_SHORT",a["by_status"].get("PRIORITY_SHORT",_diag([]))),
    ]
    for name,s in cohorts:
        lines.append(
            f"| {name} | {s['count']} | {s['short_rate']['4h']} | "
            f"{s['short_rate']['12h']} | {s['short_rate']['24h']} | "
            f"{s['all3_short_pct']} | {s['trend_stable_pct']} | "
            f"{s['reversal_after_short_pct']} | {s['entry_confirmed_pct']} | "
            f"{s['confirmed_2r_success_pct']} |"
        )

    lines += [
        "",
        "## Trend phase",
        "",
        "| Phase | N | 4h ↓ | 12h ↓ | 24h ↓ | ALL 3 ↓ | Reversal |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for phase,s in a["by_phase"].items():
        lines.append(
            f"| {phase} | {s['count']} | {s['short_rate']['4h']} | "
            f"{s['short_rate']['12h']} | {s['short_rate']['24h']} | "
            f"{s['all3_short_pct']} | {s['reversal_after_short_pct']} |"
        )

    lines += ["","## OOS AUC"]
    for key,value in a["auc"].items():
        lines.append(f"- {key}: {value}")

    lines += [
        "",
        "## Rules",
        "- EARLY_DOWNTREND and MATURE_DOWNTREND may progress to actionable Short states.",
        "- EXHAUSTED_DOWNTREND and RECOVERY_RECLAIM are blocked from PRIORITY_SHORT.",
        "- Zone touch alone is never an entry trigger.",
        "- PRIORITY_SHORT requires recent zone touch + no reclaim + bearish rejection + micro turn-down + >=2.2R support room.",
        "- WAIT_ENTRY_ZONE forbids chasing below the preferred retracement zone.",
        "- ZONE_TOUCHED_WAIT_CONFIRMATION means location is reached but trigger is not confirmed yet.",
        "",
    ]
    return "\n".join(lines)


def merge_reports(reports):
    if not reports:
        raise RuntimeError("No V4.2.8 shard reports found")
    expected=max(int(r.get("shard_count") or 1) for r in reports)
    found={int(r.get("shard_index")) for r in reports}
    if found!=set(range(expected)):
        raise RuntimeError(f"Incomplete V4.2.8 shards: {sorted(found)}")
    ids={str(r.get("manifest_id")) for r in reports}
    if len(ids)!=1:
        raise RuntimeError("V4.2.8 manifest mismatch")

    first=reports[0]
    frozen=set((first.get("manifest") or {}).get("symbols") or [])
    symbols=[]; raw=[]; errors=[]
    for report in reports:
        symbols.extend(report.get("selected_symbols") or [])
        raw.extend(report.get("trades") or [])
        errors.extend(report.get("errors") or [])
    unique=set(symbols)
    integrity={
        "ok":(
            len(reports)==expected
            and len(symbols)==len(unique)
            and unique==frozen
        ),
        "expected_shards":expected,
        "found_shards":len(reports),
        "frozen_symbol_count":len(frozen),
        "merged_symbol_count":len(unique),
    }
    if not integrity["ok"]:
        raise RuntimeError(f"V4.2.8 integrity failed: {integrity}")

    dedup={}
    for row in raw:
        dedup.setdefault(
            (row.get("symbol"),row.get("signal_time")),row
        )
    raw_rows=sorted(
        dedup.values(),
        key=lambda r:(str(r.get("signal_time")),str(r.get("symbol"))),
    )
    _add_cross_section_and_phase(raw_rows)

    scored,folds,meta=_walk_forward(raw_rows)

    by_status=defaultdict(list)
    by_phase=defaultdict(list)
    for row in scored:
        by_status[str(row.get("scanner_status") or "UNKNOWN")].append(row)
        by_phase[str(row.get("v428_trend_phase") or "UNKNOWN")].append(row)

    top10=[r for r in scored if r.get("top_10pct")]
    counts=defaultdict(int)
    for row in scored:
        counts[str(row["signal_time"])]+=1
    median=(
        float(np.median(list(counts.values())))
        if counts else None
    )

    auc={
        "4h":_auc(scored,"p_4h_lower","y_4h_lower"),
        "12h":_auc(scored,"p_12h_lower","y_12h_lower"),
        "24h":_auc(scored,"p_24h_lower","y_24h_lower"),
        "relative12":_auc(
            scored,"p_rel_12h_underperform","y_rel_12h_underperform"
        ),
        "relative24":_auc(
            scored,"p_rel_24h_underperform","y_rel_24h_underperform"
        ),
        "stability":_auc(
            scored,"p_trend_stable","y_trend_stable"
        ),
        "reversal":_auc(
            scored,"p_reversal_after_short","y_reversal_after_short"
        ),
        "confirmed_2r":_auc(
            scored,"p_confirmed_2r","y_confirmed_2r_success"
        ),
    }
    analysis={
        "raw_count":len(raw_rows),
        "oos_count":len(scored),
        "cross_section_median":(
            round(median,2) if median is not None else None
        ),
        "overall":_diag(scored),
        "top10":_diag(top10),
        "by_status":{
            key:_diag(value)
            for key,value in sorted(by_status.items())
        },
        "by_phase":{
            key:_diag(value)
            for key,value in sorted(by_phase.items())
        },
        "auc":auc,
        "folds":folds,
    }

    return {
        "engine":"Crypto Short V4.2.8 Trend Phase + Confirmed Entry",
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

    _write_json(
        os.path.join(OUTPUT_DIR,"v428_backtest.json"),report
    )
    _write_json(
        os.path.join(OUTPUT_DIR,"v428_analysis.json"),report["analysis"]
    )
    _write_json(
        os.path.join(OUTPUT_DIR,"v428_model_meta.json"),report["model_meta"]
    )
    _write_json(
        os.path.join(OUTPUT_DIR,"v428_manifest.json"),report["manifest"]
    )
    _write_csv(
        os.path.join(OUTPUT_DIR,"v428_scored_candidates.csv"),
        report.get("trades") or [],
        fields=SCORED_FIELDS,
    )
    with open(
        os.path.join(OUTPUT_DIR,"v428_summary.md"),
        "w",encoding="utf-8",
    ) as h:
        h.write(_summary(report))

    print(json.dumps({
        "integrity":report["manifest_integrity"],
        "median_coins_per_timestamp":report["analysis"]["cross_section_median"],
        "priority":report["analysis"]["by_status"].get("PRIORITY_SHORT"),
        "wait_entry":report["analysis"]["by_status"].get("WAIT_ENTRY_ZONE"),
        "wait_confirmation":report["analysis"]["by_status"].get("ZONE_TOUCHED_WAIT_CONFIRMATION"),
        "persistent":report["analysis"]["by_status"].get("PERSISTENT_SHORT"),
        "by_phase":report["analysis"]["by_phase"],
        "auc":report["analysis"]["auc"],
        "errors":len(report.get("errors") or []),
    },ensure_ascii=False,indent=2,default=str))
    return 0


if __name__=="__main__":
    sys.exit(main())
