"""M5 V0.4.1 — closed-OHLC entry-delay, slippage and outlier diagnostics.

All observations were chosen and examined in V0.4. This is an exploratory
sensitivity audit, NOT unseen backtest, no future hypothesis confirmation,
no alerts and NO trading. Uses cached OHLC only; no external API.
"""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics

from .data import STEP, _utc
from .v02 import dump, load
from .v04_plan import EXECUTION_ID, OUTPUT_ROOT, read_plan
from .v04_path import HORIZONS, SL_TP, _bars_for_event, _stop_tp, distribution, research_path
from .v04_run import _load_one, _paths

VERSION = "M5_V041_EXECUTION_ROBUSTNESS_DISCOVERY_ONLY_V1"
OUTPUT_NAME = "v041_entry_robustness.json"
DETAIL_NAME = "v041_event_sensitivity.jsonl.gz"
# These are a fixed descriptive stress grid, NOT measured MEXC execution prices.
SLIPPAGE_EACH_SIDE_BPS = (0, 5, 10, 20)
FEE_EACH_SIDE_BPS = 5
ENTRY_DELAYS_BARS = (1, 2)  # T+15m and T+30m opens
OUTLIER_FLAG_ABS_PCT = 10.0

def _net_short_pct(raw_entry, raw_exit, slip_bps):
    """Adverse slippage both sides of a short + explicit per-leg fees.

    0bps slippage is *still* charged 5bps fee on EACH leg. Funding excluded.
    The fee model uses executed notionals, normalized to entry notional.
    """
    if raw_entry <= 0 or raw_exit <= 0:
        raise RuntimeError("Invalid nonpositive execution price")
    entry = raw_entry * (1.0 - slip_bps / 10000.0)
    exit_ = raw_exit * (1.0 + slip_bps / 10000.0)
    fee = (entry + exit_) * FEE_EACH_SIDE_BPS / 10000.0
    return (entry - exit_ - fee) / entry * 100.0

def simulate(raw_ohlc, symbol, event_open, *, anchor=None):
    """Common EVENT-relative exit clocks. Delayed entry holds 15m LESS.

    H=4h means both versions exit at close of bar OPENING at T+4h,
    not 4 hours from the respective entries. This avoids extra lookahead
    bars and uses the exact frozen V0.4 OHLC.
    """
    bars, error = _bars_for_event(raw_ohlc, event_open)
    if error:
        return None, error
    t = _utc(event_open)
    if anchor is not None:
        a = float(anchor)
        if not math.isfinite(a) or a <= 0:
            return None, "BAD_ASOF_ANCHOR"
        if abs(float(bars.iloc[0]["close"]) / a - 1) * 100 > 0.25:
            return None, "HISTORICAL_ANCHOR_CHANGED"
    result = {"symbol": symbol, "event_open_utc": t.isoformat(), "entry_delays": {}}
    for delay in ENTRY_DELAYS_BARS:
        first = bars.iloc[delay]
        raw_entry = float(first["open"])
        mode = "immediate" if delay == 1 else "delayed_15m"
        variants = {}
        for hours in HORIZONS:
            n = hours * 4
            path = bars.iloc[delay:n + 1]
            if len(path) != n + 1 - delay:
                return None, "INCOMPLETE_FIXED_EXIT_PATH"
            final = float(path.iloc[-1]["close"])
            span = {
                "time_from_signal_close_to_entry_minutes": delay * 15 - 15,
                "actual_bars_held": len(path),
                "entry_open": raw_entry,
                "exit_close_at_fixed_event_clock": final,
                "gross_pct": (raw_entry - final) / raw_entry * 100,
                "mfe_pct": (raw_entry - float(path["low"].min())) / raw_entry * 100,
                "mae_pct": (float(path["high"].max()) - raw_entry) / raw_entry * 100,
                "close_net_fee_slippage": {
                    str(bps): _net_short_pct(raw_entry, final, bps)
                    for bps in SLIPPAGE_EACH_SIDE_BPS
                },
                "fixed_sl_tp": {},
            }
            for sl, tp in SL_TP:
                label = f"sl{sl:g}_tp{tp:g}"
                # Recompute stop path with the WORSE effective entry (short
                # sells at bid/slipped price), not just subtract costs after
                # knowing an optimistic unadjusted stop sequence.
                scenario = {}
                for bps in SLIPPAGE_EACH_SIDE_BPS:
                    effective_entry = raw_entry * (1.0 - bps / 10000.0)
                    stop = _stop_tp(path, effective_entry, sl, tp)
                    scenario[str(bps)] = {
                        "net_pct": _net_short_pct(raw_entry, float(stop["exit"]), bps),
                        "exit_reason": stop["reason"],
                        "exit_bar_index": int(stop["bar_index"]),
                    }
                span["fixed_sl_tp"][label] = scenario
            variants[f"{hours}h"] = span
        result["entry_delays"][mode] = variants
    return result, None

def _mean(xs):
    return statistics.fmean(xs) if xs else None

def _rounded(value):
    return None if value is None else round(float(value), 6)

def _robustness(rows, field):
    """Leave-one-observation-out and leave-one-UTC-day-out, descriptive only."""
    values = [float(r[field]) for r in rows]
    if not values:
        return {
            "count": 0, "median": None, "min": None, "max": None,
            "leave_one_event_out_min": None, "leave_one_event_out_max": None,
            "leave_one_day_out_min": None, "leave_one_day_out_max": None,
            "positive_days": 0, "days": 0,
        }
    loo = [_mean(values[:i] + values[i+1:]) for i in range(len(values))] if len(values) > 1 else []
    days = sorted(set(r["day_utc"] for r in rows))
    daymeans = [
        _mean([r[field] for r in rows if r["day_utc"] == d])
        for d in days
    ]
    ld = [
        _mean([r[field] for r in rows if r["day_utc"] != d])
        for d in days
    ] if len(days) > 1 else []
    ld = [v for v in ld if v is not None]
    return {
        "count": len(values),
        "mean": _rounded(_mean(values)),
        "median": _rounded(statistics.median(values)),
        "min": _rounded(min(values)), "max": _rounded(max(values)),
        "trim_one_each_side_mean": _rounded(_mean(sorted(values)[1:-1])) if len(values) > 2 else None,
        "leave_one_event_out_min": _rounded(min(loo)) if loo else None,
        "leave_one_event_out_max": _rounded(max(loo)) if loo else None,
        "leave_one_day_out_min": _rounded(min(ld)) if ld else None,
        "leave_one_day_out_max": _rounded(max(ld)) if ld else None,
        "positive_days": sum(x > 0 for x in daymeans),
        "days": len(days),
        "abs_value_exceeds_10pct": sum(abs(x) > OUTLIER_FLAG_ABS_PCT for x in values),
        "largest_abs_observation": _rounded(max(values, key=abs)),
        "uncertainty_type": "DESCRIPTIVE_ONLY_NO_IID_P_VALUES",
    }

def analyze(output_root=OUTPUT_ROOT, *, raw_report_override=None):
    plan = read_plan(output_root)
    base = Path(output_root) / EXECUTION_ID
    original_file = base / "risk" / "v04_risk_report.json"
    raw = raw_report_override if raw_report_override is not None else load(original_file)
    if (raw.get("plan_sha256") != plan["plan_sha256"] or
        raw.get("status") != "EXPLORATORY_OHLC_PATH_AUDIT_NOT_TRADING_EDGE_VALIDATION" or
        raw.get("selected_event_total") != len(plan["events"]) or
        raw.get("complete_matched_event_total") != len(plan["events"])):
        raise RuntimeError("M5 V0.4 source report incomplete or inconsistent")
    filehash = {}
    frames = {}
    for symbol in plan["symbols"]:
        accepted, excluded = _paths(base, symbol)
        if accepted.exists() and excluded.exists():
            raise RuntimeError("Contradictory archived OHLC symbol")
        if accepted.exists():
            filehash[symbol] = hashlib.sha256(accepted.read_bytes()).hexdigest()
            frames[symbol] = _load_one(accepted)
        elif excluded.exists():
            filehash[symbol] = hashlib.sha256(excluded.read_bytes()).hexdigest()
        else:
            raise RuntimeError("M5 V0.4 OHLC incomplete: " + symbol)
    fingerprint = hashlib.sha256(json.dumps(filehash, sort_keys=True).encode()).hexdigest()
    if fingerprint != raw.get("archived_symbol_sha256"):
        raise RuntimeError("Archived OHLC changed after sealed M5 V0.4 report")

    # V0.4 per-event source is immutable. Reproduce all 1/2/4/8h case
    # next-open close results, detecting any changed computation or event.
    original_events = {}
    with gzip.open(base / "risk" / "v04_event_paths.jsonl.gz", "rt", encoding="utf-8") as fd:
        for line in fd:
            e = json.loads(line)
            key = (e["event_id"], e["symbol"], e["event_bar_open_utc"])
            if key in original_events:
                raise RuntimeError("Duplicated original V0.4 event")
            original_events[key] = e
    if len(original_events) != len(plan["events"]):
        raise RuntimeError("Original event path ledger size mismatch")
    rows = []
    family_cases = defaultdict(list)
    for event in plan["events"]:
        key = (event["event_id"], event["symbol"], event["bar_open_utc"])
        older = original_events.get(key)
        if older is None:
            raise RuntimeError("Missing V0.4 event in sealed event ledger")
        if list(older["matched_controls"]) != list(event["controls"]):
            raise RuntimeError("Changed matched controls across versions")
        t = _utc(event["bar_open_utc"])
        if t + 32 * STEP >= _utc(plan["holdout_exclusive_utc"]):
            raise RuntimeError("Event outcome crosses holdout boundary")
        case, error = simulate(frames[event["symbol"]], event["symbol"], t,
                               anchor=event["asof_close"])
        if error:
            raise RuntimeError("Case OHLC was valid in V0.4 but not V0.4.1: " + error)
        controls = []
        for control in event["controls"]:
            control_path, err = simulate(frames[control], control, t)
            if err:
                raise RuntimeError("Matched control OHLC changed or missing: " + err)
            controls.append(control_path)
        for h in HORIZONS:
            horizon = f"{h}h"
            new = case["entry_delays"]["immediate"][horizon]["gross_pct"]
            old = older["case"]["hours"][horizon]["close_only_gross_pct"]
            if abs(new - old) > 0.00001:
                raise RuntimeError("M5 V0.4 original next-open result mismatch")
        row = {
            "event_id": event["event_id"],
            "symbol": event["symbol"],
            "event_day_utc": event["event_day_utc"],
            "event_open_utc": event["bar_open_utc"],
            "case": case, "controls": controls,
        }
        rows.append(row)
        family_cases[event["event_id"]].append(row)

    summaries = {}
    for family in plan["families"]:
        frows = family_cases[family]
        per_horizon = {}
        for h in HORIZONS:
            key = f"{h}h"
            compact = []
            for e in frows:
                common = {"day_utc": e["event_day_utc"], "symbol":e["symbol"]}
                for mode in ("immediate", "delayed_15m"):
                    v = e["case"]["entry_delays"][mode][key]
                    comparison = [
                        c["entry_delays"][mode][key]["gross_pct"]
                        for c in e["controls"]
                    ]
                    common[mode + "_gross_pct"] = v["gross_pct"]
                    common[mode + "_matched_edge_pp"] = v["gross_pct"] - statistics.fmean(comparison)
                    for bps in SLIPPAGE_EACH_SIDE_BPS:
                        x = v["close_net_fee_slippage"][str(bps)]
                        control_net = statistics.fmean(
                            c["entry_delays"][mode][key]["close_net_fee_slippage"][str(bps)]
                            for c in e["controls"])
                        common[f"{mode}_net_{bps}bps_side_pct"] = x
                        common[f"{mode}_paired_net_{bps}bps_side_pp"] = x - control_net
                        for sl, tp in SL_TP:
                            label=f"sl{sl:g}_tp{tp:g}"
                            common[f"{mode}_{label}_net_{bps}bps_side_pct"] = (
                                v["fixed_sl_tp"][label][str(bps)]["net_pct"]
                            )
                common["delayed_minus_immediate_gross_pp"] = (
                    common["delayed_15m_gross_pct"] - common["immediate_gross_pct"]
                )
                compact.append(common)
            rollups = {
                "fixed_clock_horizon_hours": h,
                "delayed_holds_one_fewer_15m_bar": True,
                "selected_events": len(compact),
                "entry_delay_gross_difference_pp":
                    _robustness(compact, "delayed_minus_immediate_gross_pp"),
            }
            for mode in ("immediate", "delayed_15m"):
                rollups[mode] = {
                    "gross_pct": _robustness(compact, mode+"_gross_pct"),
                    "paired_edge_pp": _robustness(compact, mode+"_matched_edge_pp"),
                    "fee_and_slippage_net_pct": {
                        str(bps): _robustness(compact,f"{mode}_net_{bps}bps_side_pct")
                        for bps in SLIPPAGE_EACH_SIDE_BPS
                    },
                    "paired_net_edge_pp": {
                        str(bps): _robustness(compact,f"{mode}_paired_net_{bps}bps_side_pp")
                        for bps in SLIPPAGE_EACH_SIDE_BPS
                    },
                    "fixed_sl_tp_net_pct": {
                        f"sl{sl:g}_tp{tp:g}": {
                            str(bps): _robustness(compact,
                                f"{mode}_sl{sl:g}_tp{tp:g}_net_{bps}bps_side_pct")
                            for bps in SLIPPAGE_EACH_SIDE_BPS
                        }
                        for sl,tp in SL_TP
                    },
                }
            per_horizon[key] = rollups
        summaries[family] = {
            "sample":len(frows),
            "distinct_utc_days":len({e["event_day_utc"] for e in frows}),
            "distinct_symbols":len({e["symbol"] for e in frows}),
            "horizons":per_horizon,
        }
    report = {
        "version":VERSION,
        "status":"EXPLORATORY_ROBUSTNESS_ONLY_NO_EDGE_CONFIRMATION",
        "execution_id":EXECUTION_ID,
        "v04_plan_sha256":plan["plan_sha256"],
        "v04_source_risk_report_sha256":hashlib.sha256(original_file.read_bytes()).hexdigest(),
        "v04_source_ohlc_archive_sha256":fingerprint,
        "events_selected_before_outcomes":len(plan["events"]),
        "events_audited":len(rows),
        "families":summaries,
        "entry_timing": {
            "immediate":"T+15m OPEN (first bar after event CLOSE)",
            "delayed_15m":"T+30m OPEN, exactly 15m later",
            "fixed_exit_clock":"Both close at T + H hour bar CLOSE",
            "holding_time_note":"Delayed version is exposed to market one 15m bar less at each horizon",
        },
        "entry_assumptions":"ZERO_LATENCY_BAR_OPEN_UNEXECUTABLE_PROXY",
        "slippage_per_side_bps":list(SLIPPAGE_EACH_SIDE_BPS),
        "fixed_fee_per_side_bps":FEE_EACH_SIDE_BPS,
        "fees_and_adverse_slippage_mode":"ENTRY_SHORT_SELL_LOWER_EXIT_BUY_HIGHER_PLUS_BOTH_FEES",
        "stop_rules":"SAME_BAR_SL_FIRST_GAP_STOP_WORSE_OPEN",
        "unmeasured":"REAL_SPREAD_FUNDING_LATENCY_MARKET_IMPACT_LIQUIDATIONS",
        "holdout_opened":False,
        "historical_exploration_only":True,
        "prior_outcome_peeking":True,
        "no_independent_out_of_sample":True,
        "number_independent_samples_unestablished":True,
        "not_statistically_validated":True,
        "no_orders":True,
        "no_trade_signals":True,
        "outlier_warning":"Mean, median, leave-one-event/day-out and trimmed-one-tail are descriptive; no inferential p-values.",
        "multiple_testing_warning":"8 families x 4 horizons x 2 entry timings x 4 slippage levels x 3 stop pairs; no winner confirmation.",
    }
    return report, rows

def run(output_root=OUTPUT_ROOT):
    base = Path(output_root) / EXECUTION_ID / "risk"
    dest = base / OUTPUT_NAME
    audit_file = base / DETAIL_NAME
    if dest.exists() or audit_file.exists():
        raise RuntimeError("M5 V0.4.1 already sealed; never overwrite")
    report, rows=analyze(output_root)
    # Write summaries only after all validation passes, no partial success.
    base.mkdir(parents=True,exist_ok=True)
    with gzip.open(audit_file,"wt",encoding="utf-8") as fd:
        for row in rows:
            fd.write(json.dumps(row,ensure_ascii=False)+"\n")
    report["per_event_audit_sha256"]=hashlib.sha256(audit_file.read_bytes()).hexdigest()
    dump(dest,report)
    print(json.dumps({
        "status":report["status"],
        "events":report["events_audited"],
        "families":{
            key:{
                "count":m["sample"],
                "immediate_4h_gross":m["horizons"]["4h"]["immediate"]["gross_pct"]["mean"],
                "delayed_4h_gross":m["horizons"]["4h"]["delayed_15m"]["gross_pct"]["mean"],
                "gross_change_pp":m["horizons"]["4h"]["entry_delay_gross_difference_pp"]["mean"],
                "immediate_4h_net_10bps_slippage_each_side":m["horizons"]["4h"]["immediate"]["fee_and_slippage_net_pct"]["10"]["mean"],
                "immediate_4h_paired_edge_leave_one_day_out": [
                    m["horizons"]["4h"]["immediate"]["paired_edge_pp"]["leave_one_day_out_min"],
                    m["horizons"]["4h"]["immediate"]["paired_edge_pp"]["leave_one_day_out_max"]
                ],
            } for key,m in report["families"].items()
        },
        "discovery_only":True,"report_file":str(dest),
    },ensure_ascii=False,indent=2))
    return report

def main():
    p=argparse.ArgumentParser(description="M5 V0.4.1 read-only entry robustness diagnostics")
    p.add_argument("--source-root",type=Path,default=OUTPUT_ROOT)
    args=p.parse_args()
    run(args.source_root)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
