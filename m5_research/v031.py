"""M5 V0.3.1 — expanded historical discovery/day stability, NOT validation.

The 14-day historical period overlaps the previously inspected 7-day cohort.
It cannot be passed off as untouched holdout, replication, or forward evidence.
Only the 75% discovery window is scored; the final 25% future closes remain unread.
"""
import argparse
import json
from pathlib import Path
from .v02 import ROOT, checked_id, dump, load, validate_plan
from .v03_discovery import analyze

REPORT_VERSION="M5_V031_EXPANDED_HISTORICAL_DESCRIPTIVE_STABILITY"
OLD_SEVEN_DAY_STUDY="m5-full-20261013-7d"

def run(study_id,root=ROOT):
    root=Path(root)
    plan=load(root/checked_id(study_id)/"plan.json")
    validate_plan(plan)
    if plan["pilot"] or plan["historical_days"]<14:
        raise RuntimeError("M5 V0.3.1 needs a merged non-pilot 14+ day cohort")
    if study_id==OLD_SEVEN_DAY_STUDY:
        raise RuntimeError("Never overwrite/re-score original V0.3 7-day study")
    report=analyze(study_id,root,include_daily=True)
    report["version"]=REPORT_VERSION
    report["status"]="EXPANDED_DISCOVERY_ONLY_UNCONFIRMED"
    report["related_previous_cohort"]=OLD_SEVEN_DAY_STUDY
    report["historical_overlap_warning"]=(
      "This 14+ day history includes calendar days previously viewed in the "
      "original 7-day exploratory research. Day stability is DESCRIPTIVE only, "
      "not independent confirmation and not a backtest of executable PnL."
    )
    report["cross_day_dependent_events"]=True
    report["ready_for_live_orders"]=False
    report["valid_untouched_confirmation"]=False
    report["next_gate"]=(
      "Separately preregister a genuinely unseen future cohort, including "
      "cost/funding/slippage, MFE/MAE from full OHLCV, and primary metric."
    )
    dest=root/study_id/"discovery"/"v031_daily_stability.json"
    if dest.exists():
        raise RuntimeError("M5 V0.3.1 report already archived: no overwrite")
    dump(dest,report)
    print(json.dumps({
        "status":report["status"],
        "study_id":study_id,
        "accepted_symbols":report["source_symbol_count"],
        "discovery_events":report["total_discovery_events_before_purge"],
        "complete_matched_events":report["eligible_complete_case_and_control_pairs"],
        "events_by_family":{
            k:{"count":v["paired_event_observations"],
               "days":v["distinct_event_days"],
               "edge_4h_pp":v["horizon_metrics"]["4h"]["mean_paired_edge_pp"],
               "positive_days_4h":report["daily_event_stability"][k]["descriptive_stability"]["4h"]["positive_day_count"]}
            for k,v in report["families"].items()
        },
        "discovery_only":True,
        "no_untouched_holdout_outcomes":True,
        "report_file":str(dest),
    },ensure_ascii=False,indent=2))
    return report

def main():
    p=argparse.ArgumentParser(description="M5 V0.3.1 historical discovery daily-stability ONLY")
    p.add_argument("--study-id",default="m5-full-20261013-14d")
    p.add_argument("--root",type=Path,default=ROOT)
    args=p.parse_args()
    run(args.study_id,args.root)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
