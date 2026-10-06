import csv
import json
import os
import sys

from .config import OUTPUT_DIR
from .v426_backtest import run_v426_backtest
from .v426_model import FEATURE_NAMES


PATH_FIELDS = []
for h in (1,2,4,8,12,16,20,24):
    PATH_FIELDS += [
        f"dir_{h}h_close_pct",f"dir_{h}h_close_atr",
        f"dir_{h}h_mfe_atr",f"dir_{h}h_mae_atr",
        f"dir_{h}h_short",f"market_{h}h_return_pct",
        f"relative_{h}h_future_pct",
    ]

BASE_FIELDS = [
    "manifest_id","symbol","signal_time",
    "current_price","atr_1h","candidate_context_points",
    "setup_type","setup_subtype","zone_source",
    "preferred_zone_lower","preferred_zone_upper","zone_distance_atr",
    "severe_bottom_rule","bottom_reasons",
    "v426_entry_reference","v426_stop_reference","v426_tp2r_reference",
    "v426_risk","v426_entry_zone_distance_atr","v426_support_room_r",
    "v426_rr2_room_ok","v426_strong_zone","v426_near_zone",
    "v426_in_zone","v426_below_zone",
]

LABEL_FIELDS = [
    "y_4h_lower","y_12h_lower","y_24h_lower","y_first_short",
    "y_persistent_short","y_reversal_after_short",
    "y_zone_2r_success","zone_filled","zone_fill_hours","zone_trade_outcome",
    "dir_first_0_5atr_move","max_downside_24h_atr","max_adverse_24h_atr",
    "hours_to_max_downside","reclaimed_signal_after_mfe",
    "rebound_from_mfe_atr","path_class_24h",
]

CSV_FIELDS = BASE_FIELDS + FEATURE_NAMES + LABEL_FIELDS + PATH_FIELDS


def _write_json(path,payload):
    with open(path,"w",encoding="utf-8") as handle:
        json.dump(payload,handle,ensure_ascii=False,indent=2,default=str)


def _write_csv(path,rows,fields=CSV_FIELDS):
    with open(path,"w",newline="",encoding="utf-8") as handle:
        writer=csv.DictWriter(handle,fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k:row.get(k) for k in fields})


def main():
    report=run_v426_backtest()
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR,"v426_backtest.json"),report)
    _write_csv(
        os.path.join(OUTPUT_DIR,"v426_raw_candidates.csv"),
        report.get("trades") or [],
    )
    print(json.dumps({
        "manifest_id":report.get("manifest_id"),
        "shard_index":report.get("shard_index"),
        "symbols":report.get("selected_symbol_count"),
        "rows":len(report.get("trades") or []),
        "errors":len(report.get("errors") or []),
    },ensure_ascii=False,indent=2))
    return 0 if report.get("selected_symbol_count",0)>0 else 2


if __name__=="__main__":
    sys.exit(main())
