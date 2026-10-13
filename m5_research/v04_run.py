"""Resumable M5 V0.4 OHLC read-only collection and exploratory risk report.

The as-of event sample is frozen first; ALL outcome OHLC bars are fetched
only after that plan exists. No real exchange orders or live trade signals.
"""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path

import pandas as pd

from .data import STEP, _utc, request_candles
from .v02 import dump, load
from .v04_plan import EXECUTION_ID, OUTPUT_ROOT, read_plan
from .v04_path import HORIZONS, SL_TP, distribution, research_path

def _paths(base, symbol):
    return base / "ohlc" / (symbol + ".csv.gz"), base / "excluded" / (symbol + ".json")

def _windows(plan):
    all_windows = defaultdict(list)
    max_open = _utc(plan["holdout_exclusive_utc"]) - STEP
    for e in plan["events"]:
        t = _utc(e["bar_open_utc"])
        end = t + 32*STEP
        if end > max_open:
            raise RuntimeError("Selected event OHLC path would cross holdout")
        for symbol in [e["symbol"], *e["controls"]]:
            all_windows[symbol].append((t, end))
    return all_windows

def collect(max_new=8, output_root=OUTPUT_ROOT, fetch_fn=request_candles):
    if not 1 <= max_new <= 16:
        raise ValueError("V0.4 OHLC checkpoint budget 1..16 symbols")
    plan=read_plan(output_root)
    base=Path(output_root)/EXECUTION_ID
    windows=_windows(plan)
    excluded={}
    accepted=[]
    requests=0
    attempted=0
    transient={}
    for symbol in plan["symbols"]:
        data_path,excluded_path=_paths(base,symbol)
        if data_path.exists() and excluded_path.exists():
            raise RuntimeError("Contradictory OHLC archives for "+symbol)
        if data_path.exists() or excluded_path.exists():
            continue
        if attempted >= max_new:
            break
        attempted += 1
        required=windows[symbol]
        try:
            start=min(x for x,_ in required)
            end=max(y for _,y in required)
            frame,n=fetch_fn(symbol,start,end)
            requests+=n
            if frame.empty:
                dump(excluded_path,{"status":"EMPTY_HISTORY","symbol":symbol,
                                    "plan_sha256":plan["plan_sha256"]})
                excluded[symbol]="EMPTY_HISTORY"
                continue
            if frame.index.tz is None:
                raise RuntimeError("Naive candle timestamps")
            if frame.index.duplicated().any():
                raise RuntimeError("Duplicate OHLC timestamps")
            # Store only the explicitly selected event-path bars; no
            # irrelevant period and no held-out OHLC retention.
            needed=set()
            for t,end in required:
                needed.update(pd.date_range(t,end,freq="15min",tz="UTC"))
            cut=frame.loc[frame.index.isin(needed)].sort_index()
            if not cut.empty and cut.index.max()>=_utc(plan["holdout_exclusive_utc"]):
                raise RuntimeError("Holdout OHLC leakage")
            if cut.empty:
                dump(excluded_path,{"status":"MISSING_SELECTED_BARS","symbol":symbol,
                                    "plan_sha256":plan["plan_sha256"]})
                excluded[symbol]="MISSING_SELECTED_BARS"
                continue
            data_path.parent.mkdir(parents=True,exist_ok=True)
            cut[["open","high","low","close"]].to_csv(data_path,compression="gzip")
            accepted.append(symbol)
        except Exception as exc:
            transient[symbol]=str(exc)[:180]
        print(f"[M5/V04] {symbol} "+
              ("ARCHIVED" if symbol in accepted else
               "NO_HISTORY" if symbol in excluded else "RETRY_LATER"),flush=True)
    remaining=[s for s in plan["symbols"]
               if not any(p.exists() for p in _paths(base,s))]
    status={
        "status":"OHLC_COLLECTION_COMPLETE" if not remaining else "OHLC_PARTIAL",
        "plan_sha256":plan["plan_sha256"],
        "symbol_total":len(plan["symbols"]),
        "stored_count":sum(_paths(base,s)[0].exists() for s in plan["symbols"]),
        "excluded_count":sum(_paths(base,s)[1].exists() for s in plan["symbols"]),
        "pending_count":len(remaining),"pending_first":remaining[:10],
        "attempted_this_run":attempted, "new_archived":accepted,
        "new_no_history":excluded, "transient":transient,
        "http_attempts_this_run":requests,
    }
    dump(Path("output/m5_research/v04_checkpoint.json"),status)
    print(json.dumps(status,indent=2))
    return status

def _load_one(path):
    f=pd.read_csv(path,index_col=0,parse_dates=True)
    if f.index.tz is None:
        raise RuntimeError("Archived OHLC timezone missing")
    return f.sort_index()

def summarize(output_root=OUTPUT_ROOT):
    plan=read_plan(output_root)
    base=Path(output_root)/EXECUTION_ID
    dest=base/"risk"/"v04_risk_report.json"
    if dest.exists():
        raise RuntimeError("M5 V0.4 pilot risk report already sealed")
    for s in plan["symbols"]:
        x,y=_paths(base,s)
        if not x.exists() and not y.exists():
            raise RuntimeError("Missing OHLC checkpoint for "+s)
    frames={}
    file_sha={}
    excluded={}
    for s in plan["symbols"]:
        x,y=_paths(base,s)
        if x.exists() and y.exists():
            raise RuntimeError("Accepted and rejected same symbol")
        if x.exists():
            frames[s]=_load_one(x)
            file_sha[s]=hashlib.sha256(x.read_bytes()).hexdigest()
        else:
            rejection=load(y)
            if rejection["plan_sha256"]!=plan["plan_sha256"]:
                raise RuntimeError("Excluded OHLC belongs to another frozen plan")
            excluded[s]=rejection["status"]
            file_sha[s]=hashlib.sha256(y.read_bytes()).hexdigest()
    by_fam=defaultdict(list)
    attrition=Counter()
    invalid=[]
    all_case_records=[]
    for event in plan["events"]:
        fam=event["event_id"]
        symbol=event["symbol"]
        t=_utc(event["bar_open_utc"])
        if symbol not in frames:
            attrition["CASE_OHLC_NOT_AVAILABLE"]+=1
            continue
        case,reason=research_path(symbol,t,frames[symbol],
                                  anchor_close=event["asof_close"])
        if reason:
            attrition["CASE_"+reason]+=1
            invalid.append({"event_id":fam,"symbol":symbol,"reason":reason})
            continue
        controls=[]
        for s in event["controls"]:
            if s not in frames:
                continue
            control,why=research_path(s,t,frames[s])
            if control:
                controls.append(control)
        if not controls:
            attrition["NO_COMPLETE_CONTROL_8H_PATH"]+=1
            continue
        # Preserve individual case results in traceable JSONL for manual
        # audit; neither sample selection nor parameters depend on outcomes.
        row={
            "event_id":fam,"symbol":symbol,"event_day_utc":event["event_day_utc"],
            "event_bar_open_utc":event["bar_open_utc"],
            "entry_proxy_time_utc":case["entry_proxy_time_utc"],
            "matched_controls":[x["symbol"] for x in controls],
            "case":case,"controls":controls,
        }
        by_fam[fam].append(row)
        all_case_records.append(row)
    pairs_path=base/"risk"/"v04_event_paths.jsonl.gz"
    pairs_path.parent.mkdir(parents=True,exist_ok=True)
    with gzip.open(pairs_path,"wt",encoding="utf-8") as fd:
        for row in all_case_records:
            fd.write(json.dumps(row,ensure_ascii=False)+"\n")
    metrics={}
    for fam in plan["families"]:
        events=by_fam[fam]
        horizons={}
        for h in HORIZONS:
            key=f"{h}h"
            case_paths=[r["case"]["hours"][key] for r in events]
            ctl_close=[
                sum(c["hours"][key]["close_only_gross_pct"] for c in r["controls"])/len(r["controls"])
                for r in events
            ]
            paired=[
                r["case"]["hours"][key]["close_only_gross_pct"]-ctl
                for r,ctl in zip(events,ctl_close)
            ]
            sl_metrics={}
            for sl,tp in SL_TP:
                label=f"sl{sl:g}_tp{tp:g}"
                sl_metrics[label]={
                    "gross_pct":distribution([p["path_sl_tp"][label]["gross_pct"] for p in case_paths]),
                    "stress_20bps_pct":distribution([p["path_sl_tp"][label]["stress_20bps_pct"] for p in case_paths]),
                    "stress_40bps_pct":distribution([p["path_sl_tp"][label]["stress_40bps_pct"] for p in case_paths]),
                    "exit_reasons":dict(Counter(p["path_sl_tp"][label]["exit_reason"] for p in case_paths)),
                    "sltp_intrabar_ambiguity":"SAME_BAR_SL_FIRST",
                }
            horizons[key]={
                "mfe_pct":distribution([p["mfe_pct"] for p in case_paths]),
                "mae_pct":distribution([p["mae_pct"] for p in case_paths]),
                "case_next_open_to_close_gross_pct":distribution([p["close_only_gross_pct"] for p in case_paths]),
                "paired_case_minus_controls_close_edge_pp":distribution(paired),
                "stress_20bps_close_pct":distribution([p["close_minus_20bps_pct"] for p in case_paths]),
                "stress_40bps_close_pct":distribution([p["close_minus_40bps_pct"] for p in case_paths]),
                "stop_take_profit":sl_metrics,
            }
        metrics[fam]={
            "selected_before_ohlc":plan["selected_family_counts"][fam],
            "complete_case_with_asof_control":len(events),
            "unique_utc_days":len({e["event_day_utc"] for e in events}),
            "horizon_metrics":horizons,
        }
    report={
        "version":"M5_V04_EXECUTION_RISK_PILOT_EXPLORATORY_V1",
        "status":"EXPLORATORY_OHLC_PATH_AUDIT_NOT_TRADING_EDGE_VALIDATION",
        "execution_id":plan["execution_id"],
        "source_study_id":plan["source_study_id"],
        "plan_sha256":plan["plan_sha256"],
        "archived_symbol_sha256":hashlib.sha256(json.dumps(file_sha,sort_keys=True).encode()).hexdigest(),
        "instrument_count":len(plan["symbols"]),
        "ohlc_archived_count":len(frames),"ohlc_excluded":excluded,
        "selected_event_total":len(plan["events"]),
        "complete_matched_event_total":len(all_case_records),
        "attrition":dict(attrition),"invalid_examples":invalid[:20],
        "families":metrics,
        "entry":"NEXT_15M_BAR_OPEN_ZERO_LATENCY_PROXY_NOT_EXECUTABLE_FILL",
        "holdout_performance_read":False,
        "bars_after_event_exclude_holdout":True,
        "historical_14d_overlaps_previously_seen_7d":True,
        "selection_before_ohlc_fetched":True,
        "same_bar_hit_resolution":"SL_FIRST",
        "fees_spread_slippage_funding_unmeasured":True,
        "cost_sensitivity_bps":[20,40],
        "sample_is_small_and_not_random_independent":True,
        "research_only":True,"orders":False,"no_signal_promotion":True,
        "warnings":[
            "Next-bar open is an idealized zero-latency fill proxy, not executable price",
            "Intrabar stop/take-profit sequencing unknown; simultaneous triggers resolved SL-first",
            "Gaps beyond SL assumed worse open execution; favorable TP gap capped at TP",
            "Even 40bps cost stress is NOT market-specific realized fees/funding/spread",
            "Historical 14-day discovery overlaps prior model exploration, so NOT untouched validation",
            "Small as-of deterministic date-stratified pilot of at most six events per family",
            "Same-symbol and same-time crypto events are NOT independent",
            "No position sizing/liquidation/leverage/portfolio allocation represented",
        ],
    }
    dump(dest,report)
    print(json.dumps({
        "status":report["status"],
        "selected_events":report["selected_event_total"],
        "complete_matched_events":report["complete_matched_event_total"],
        "archived_symbols":report["ohlc_archived_count"],
        "families":{key:{
            "cases":v["complete_case_with_asof_control"],
            "mfe4h":v["horizon_metrics"]["4h"]["mfe_pct"]["mean"],
            "mae4h":v["horizon_metrics"]["4h"]["mae_pct"]["mean"],
            "next_open_edge4h":v["horizon_metrics"]["4h"]["paired_case_minus_controls_close_edge_pp"]["mean"]}
            for key,v in metrics.items()},
        "report":str(dest),"not_live_strategy":True,
    },indent=2))
    return report

def main():
    p=argparse.ArgumentParser("M5 v0.4 bounded execution proxy research only")
    p.add_argument("mode",choices=("collect","summarize","status"))
    p.add_argument("--max-new",type=int,default=8)
    a=p.parse_args()
    if a.mode=="collect":
        result=collect(a.max_new)
        return 0 if result["status"]=="OHLC_COLLECTION_COMPLETE" else 3
    if a.mode=="summarize":
        summarize()
        return 0
    plan=read_plan()
    base=OUTPUT_ROOT/EXECUTION_ID
    pending=[s for s in plan["symbols"] if not any(p.exists() for p in _paths(base,s))]
    print(json.dumps({"study":EXECUTION_ID,"pending":len(pending),"total":len(plan["symbols"]),
                      "complete":not pending},indent=2))
    return 0 if not pending else 3

if __name__=="__main__":
    raise SystemExit(main())
