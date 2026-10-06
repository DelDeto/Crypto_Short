import csv,json,os,sys
from .config import OUTPUT_DIR
from .v428_backtest import run_v428_backtest

BASE_FIELDS=[
 "manifest_id","symbol","signal_time","current_price","atr_1h",
 "candidate_context_points","setup_type","setup_subtype","zone_source",
 "preferred_zone_lower","preferred_zone_upper","zone_distance_atr",
 "severe_bottom_rule","bottom_reasons",
 "v428_entry_zone_distance_atr","v428_strong_zone","v428_near_zone",
 "v428_in_zone","v428_below_zone",
 "v428_zone_touched_recent","v428_zone_touch_age_1h",
 "v428_reclaim_after_touch","v428_no_reclaim_after_touch",
 "v428_bearish_rejection_now","v428_rejection_upper_wick_ratio",
 "v428_rejection_close_position","v428_micro_turn_down",
 "v428_close_below_zone_mid","v428_confirmation_below_zone_atr",
 "v428_entry_confirm_score","v428_entry_confirmed",
 "v428_confirm_entry_reference","v428_confirm_stop_reference",
 "v428_confirm_tp2r_reference","v428_confirm_risk",
 "v428_confirm_support_room_r","v428_confirm_rr2_room_ok",
]

FEATURE_FIELDS=[
 "return_1h_pct","return_3h_pct","return_4h_pct","return_12h_pct","return_24h_pct",
 "relative_1h_pct","relative_3h_pct","relative_4h_pct","relative_24h_pct",
 "coin_return_1h_pct","coin_return_3h_pct",
 "relative_recovery_1h_pct","relative_recovery_3h_pct",
 "ema20_distance_atr","range_position_12h","range_position_24h","range_position_48h",
 "distance_12h_low_atr","distance_24h_low_atr","distance_12h_high_atr",
 "support_distance_atr","supply_distance_atr","atr_pct_1h","volume_ratio_1h",
 "s1_ema_bear","s1_lower_high","s1_lower_low",
 "s4_ema_bear","s4_lower_high","s4_lower_low","s4_macro_bear",
 "breakdown_detected","breakdown_retest","breakdown_age_1h","breakdown_distance_atr",
 "sweep_detected","sweep_age_1h","bearish_rejection","continuation_quality",
 "continuation_ready","break_departure_atr","break_body_atr","break_volume_ratio",
 "retest_touched","retest_rejection","reclaim_seen","acceptance_bars",
 "rebound_from_break_low_atr","anti_bottom_total","squeeze_risk",
 "market_r4_pct","market_r24_pct","market_risk_on","market_risk_off",
 "market_bull","market_bear","zone_supply_1h","zone_supply_4h",
 "zone_broken_support","zone_sweep_retest",
]

LABEL_FIELDS=[
 "y_4h_lower","y_12h_lower","y_24h_lower",
 "y_rel_12h_underperform","y_rel_24h_underperform",
 "y_trend_stable","trend_stable_block_count",
 "y_persistent_short","y_reversal_after_short",
 "y_confirmed_2r_success","confirmed_trade_outcome",
 "max_downside_24h_atr","max_adverse_24h_atr",
 "hours_to_max_downside","reclaimed_signal_after_mfe","path_class_24h",
]

CSV_FIELDS=BASE_FIELDS+FEATURE_FIELDS+LABEL_FIELDS


def _write_json(path,payload):
    with open(path,"w",encoding="utf-8") as h:
        json.dump(payload,h,ensure_ascii=False,indent=2,default=str)


def _write_csv(path,rows,fields=CSV_FIELDS):
    with open(path,"w",newline="",encoding="utf-8") as h:
        w=csv.DictWriter(h,fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow({k:row.get(k) for k in fields})


def main():
    report=run_v428_backtest()
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR,"v428_backtest.json"),report)
    _write_csv(
        os.path.join(OUTPUT_DIR,"v428_raw_candidates.csv"),
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
