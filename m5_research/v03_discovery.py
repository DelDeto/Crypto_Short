"""M5 V0.3: DISCOVERY-ONLY historical CLOSE-return outcome audit.

Strict chronological firewall: no event from the last 25% holdout and no
outcome candle reaching that boundary enters any calculation. Earlier public
all-market event counts have already been inspected, so this held-out segment
is NOT an untouched dataset for all exploratory decisions.

This is not a trade simulator. Reference is the last known event-bar CLOSE,
not a guaranteed executable entry. No high/low OHLCV were retained in V0.2,
so MFE, MAE, intra-bar stops, execution and funding CANNOT be estimated.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics

import pandas as pd

from .config import EVENTS
from .data import STEP, _utc
from .v02 import ROOT, checked_id, digest, dump, load, validate_plan, _files

HORIZONS_HOURS = (1, 2, 4, 8)
BAR_STEPS = {h: h * 4 for h in HORIZONS_HOURS}
COST_STRESS_BPS = 20   # purely descriptive, not real exchange fees
REPORT_VERSION = "M5_V03_DISCOVERY_CLOSE_ONLY_V1"

def _finite_price(x):
    try:
        v = float(x)
        return v if math.isfinite(v) and v > 0 else None
    except (TypeError, ValueError):
        return None

def load_asof_closes(study_root, plan):
    """Use ONLY timestamped close columns from frozen V0.2 cohort.

    Read the discovery portion; do not inspect any held-out future returns.
    """
    cutoff = _utc(plan["holdout_reserved_start_utc"])
    result = {}
    digests = {}
    symbols_loaded = 0
    for i in range(plan["shards"]):
        from .data import select_universe
        for sym in select_universe(plan["symbols"], plan["shards"], i, 0):
            path, rejection = _files(study_root, i, sym)
            if not path.exists():
                if not rejection.exists():
                    raise RuntimeError(f"Missing archived symbol {sym}")
                marker = load(rejection)
                if marker.get("plan_sha256") != plan["plan_sha256"]:
                    raise RuntimeError("Rejection marker checksum conflict")
                digests[sym] = hashlib.sha256(rejection.read_bytes()).hexdigest()
                continue
            if rejection.exists():
                raise RuntimeError("Both accepted and rejected symbol in frozen archive")
            digests[sym] = hashlib.sha256(path.read_bytes()).hexdigest()
            f = pd.read_csv(path, usecols=["bar_open_utc", "close"])
            stamps = pd.to_datetime(f["bar_open_utc"], utc=True)
            if stamps.duplicated().any() or not stamps.is_monotonic_increasing:
                raise RuntimeError(f"Bad as-of history for {sym}")
            # No close from holdout is imported into the pricing dictionary.
            mask = stamps < cutoff
            lookup = {}
            for t, value in zip(stamps[mask], f.loc[mask, "close"]):
                price = _finite_price(value)
                if price is not None:
                    lookup[t.value] = price
            result[sym] = lookup
            symbols_loaded += 1
    return result, symbols_loaded, digest(digests)

def series_short_returns(symbol, t, market, cutoff):
    """Hypothetical event-close to 1/2/4/8h later CLOSE: not a fill.

    Require 32 consecutive future 15m bars and forbid HOLDOUT timestamps,
    rather than cherry-picking a sparse lookahead endpoint.
    """
    prices = market.get(symbol)
    if not prices:
        return None
    t = _utc(t)
    if t + 32 * STEP >= cutoff:
        return None
    entry = prices.get(t.value)
    if entry is None:
        return None
    sequence = []
    for step in range(1, 33):
        x = prices.get((t + step * STEP).value)
        if x is None:
            return None
        sequence.append(x)
    return {h: (entry - sequence[n - 1]) / entry * 100
            for h, n in BAR_STEPS.items()}

def _stats(rows, key):
    vals = [float(r[key]) for r in rows if math.isfinite(float(r[key]))]
    if not vals:
        return None
    return round(statistics.fmean(vals), 6)

def _summarize(rows):
    days = sorted({r["event_day_utc"] for r in rows})
    summary = {
        "paired_event_observations": len(rows),
        "distinct_event_days": len(days),
        "distinct_symbols": len({r["symbol"] for r in rows}),
        "non_independent_within_coin_and_common_utc": True,
        "day_cluster_uncertainty": "NOT_ESTIMATED_7D_DISCOVERY_IS_TOO_SHORT",
        "horizon_metrics": {},
    }
    for h in HORIZONS_HOURS:
        x = "case_short_" + str(h) + "h_pct"
        y = "control_short_" + str(h) + "h_pct"
        z = "paired_edge_" + str(h) + "h_pp"
        day_means = [
            statistics.fmean(float(r[z]) for r in rows if r["event_day_utc"] == d)
            for d in days
        ]
        summary["horizon_metrics"][str(h)+"h"] = {
            "mean_case_close_to_close_short_pct": _stats(rows, x),
            "mean_control_close_to_close_short_pct": _stats(rows, y),
            "mean_paired_edge_pp": _stats(rows, z),
            "mean_case_minus_20bps_cost_sensitivity_pct":
                round(_stats(rows, x) - COST_STRESS_BPS / 100, 6) if rows else None,
            "fraction_event_observations_case_short_positive":
                round(sum(r[x] > 0 for r in rows) / len(rows), 5) if rows else None,
            "positive_day_fraction_paired_edge":
                round(sum(v > 0 for v in day_means) / len(days), 5) if days else None,
        }
    return summary

def analyze(study_id, root=ROOT, *, max_event_rows=0, include_daily=False):
    study_root = Path(root) / checked_id(study_id)
    plan = load(study_root / "plan.json")
    validate_plan(plan)
    if plan["pilot"]:
        raise RuntimeError("Do not present pilot outcomes as market-wide research")
    if plan["historical_days"] < 7:
        raise RuntimeError("Discovery window too short for even preliminary descriptive outcomes")
    manifest = load(study_root / "merged" / "research_manifest.json")
    if manifest.get("plan_sha256") != plan["plan_sha256"] or        manifest.get("status") != "FULL_FROZEN_COHORT_MERGED":
        raise RuntimeError("Missing or mismatched immutable full-market V0.2 merge")
    source = study_root / "merged" / "market_events.jsonl.gz"
    if not source.exists():
        raise RuntimeError("Missing archived market-wide as-of event registry")
    # Disallow partial selection from a file for actual reports.
    if max_event_rows:
        raise ValueError("Subsampled event reports are not accepted")

    discovery_cutoff = _utc(plan["holdout_reserved_start_utc"])
    discovery_start = _utc(plan["first_bar_open_utc"])
    market, loaded, file_fingerprint = load_asof_closes(study_root, plan)
    if file_fingerprint != manifest.get("all_symbol_file_hash_sha256"):
        raise RuntimeError("Stored M5 V0.2 feature/rejection files changed since immutable merge")
    if loaded != manifest["accepted_symbols"]:
        raise RuntimeError("As-of closed-price feature coverage does not match frozen merge")
    rows_by_family = {name: [] for name in EVENTS}
    discovered = Counter()
    attrition = Counter()
    day_counts = Counter()
    seen = set()
    max_observed_t = None
    with gzip.open(source, "rt", encoding="utf-8") as file:
        for line in file:
            event = json.loads(line)
            t = _utc(event["last_closed_bar_open_utc"])
            # Skip holdout event metadata; no outcomes or counts may be exposed.
            if t >= discovery_cutoff:
                continue
            if not discovery_start <= t:
                raise RuntimeError("Event outside frozen study")
            fam = event["event_id"]
            if fam not in EVENTS:
                raise RuntimeError("Unexpected event family")
            sym = event["symbol"]
            key = (fam, sym, t.value)
            if key in seen:
                raise RuntimeError("Duplicate as-of event in immutable merged registry")
            seen.add(key)
            discovered[fam] += 1
            if t + 32 * STEP >= discovery_cutoff:
                attrition["PURGED_NEAR_HOLDOUT_8H"] += 1
                continue
            eligible_controls = list(event.get("control_symbols", []))
            if not eligible_controls:
                attrition["NO_MATCHED_CONTROLS_ASOF"] += 1
                continue
            case = series_short_returns(sym, t, market, discovery_cutoff)
            if case is None:
                attrition["MISSING_CONSECUTIVE_CASE_8H"] += 1
                continue
            controls = []
            for control in eligible_controls:
                if control == sym:
                    raise RuntimeError("Control cannot match itself")
                out = series_short_returns(control, t, market, discovery_cutoff)
                if out is not None:
                    controls.append((control, out))
            if not controls:
                attrition["NO_MATURE_MATCHED_CONTROL_8H"] += 1
                continue
            result = {
                "symbol": sym,
                "event_id": fam,
                "last_closed_bar_open_utc": t.isoformat(),
                "event_day_utc": t.strftime("%Y-%m-%d"),
                "complete_controls": len(controls),
            }
            for h in HORIZONS_HOURS:
                mean_control = statistics.fmean(ret[h] for _, ret in controls)
                result[f"case_short_{h}h_pct"] = case[h]
                result[f"control_short_{h}h_pct"] = mean_control
                result[f"paired_edge_{h}h_pp"] = case[h] - mean_control
            rows_by_family[fam].append(result)
            day_counts[result["event_day_utc"]] += 1
            if max_observed_t is None or t > max_observed_t:
                max_observed_t = t

    summaries = {k: _summarize(v) for k, v in rows_by_family.items()}
    report = {
        "version": REPORT_VERSION,
        "research_only": True,
        "status": "DISCOVERY_DESCRIPTIVE_ONLY_NO_EDGE_CONFIRMATION",
        "study_id": study_id,
        "study_plan_sha256": plan["plan_sha256"],
        "source_merged_event_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "historical_days": plan["historical_days"],
        "discovery_period_start_utc": discovery_start.isoformat(),
        "discovery_period_exclusive_end_utc": discovery_cutoff.isoformat(),
        "embargo_hours_to_prevent_cross_holdout_label": max(HORIZONS_HOURS),
        "holdout_outcome_rows_read": 0,
        "holdout_performance_disclosed": False,
        "holdout_warning": (
            "Holdout event counts were inspected in V0.2 aggregate reports. "
            "Holdout future returns remain unopened in V0.3; "
            "this is NOT a pristine untouched holdout for all research decisions."
        ),
        "source_kind": "historical CLOSED 15m as-of COIN CLOSES only",
        "virtual_short_reference": "EVENT_CANDLE_CLOSE_NO_EXECUTABLE_FILL",
        "outcome_horizons_h": list(HORIZONS_HOURS),
        "round_trip_cost_sensitivity_bps": COST_STRESS_BPS,
        "fees_funding_slippage_not_observed": True,
        "cannot_compute_true_mfe_mae_without_ohlc_high_low": True,
        "matched_control_source": "M5_V0.2_FROZEN_ALL_ELIGIBLE_SYMBOLS_SAME_UTC",
        "source_symbol_count": loaded,
        "total_discovery_events_before_purge": sum(discovered.values()),
        "eligible_complete_case_and_control_pairs": sum(len(v) for v in rows_by_family.values()),
        "attrition": dict(attrition),
        "discovery_family_event_counts": {key: discovered[key] for key in EVENTS},
        "families": summaries,
        "sample_caveats": [
            "The discovery phase uses 75% of this cohort; few independent calendar days even after extension",
            "Simultaneous crypto coins and consecutive hours violate IID assumptions",
            "Eight families and four horizons require predeclared multiple testing control",
            "Close-to-close hypothetical results are NOT executable trade returns",
            "Survivorship bias: no delisted contracts in the original live catalogue",
            "Only descriptive means; no p-values, no independent proof, no live promotion",
        ],
        "recommended_action": "PRESERVE_7D_REPORT_THEN_PREREGISTER_NEW_14_21D_HOLDOUT_BEFORE_CONFIRMATION",
        "no_orders": True, "no_short_recommendations": True, "no_live_promotion": True,
    }
    if include_daily:
        # Descriptive daily variation only: simultaneous coin events are NOT
        # independent, so daily signs and leave-one-day-out are not p-values.
        daily = {}
        for fam, rows in rows_by_family.items():
            days = sorted({row["event_day_utc"] for row in rows})
            by_day = {}
            for day in days:
                rday = [r for r in rows if r["event_day_utc"] == day]
                by_day[day] = {
                    "event_count": len(rday),
                    "unique_symbols": len({r["symbol"] for r in rday}),
                    "paired_edge_1h_pp": _stats(rday, "paired_edge_1h_pp"),
                    "paired_edge_2h_pp": _stats(rday, "paired_edge_2h_pp"),
                    "paired_edge_4h_pp": _stats(rday, "paired_edge_4h_pp"),
                    "paired_edge_8h_pp": _stats(rday, "paired_edge_8h_pp"),
                    "case_short_4h_pct": _stats(rday, "case_short_4h_pct"),
                    "control_short_4h_pct": _stats(rday, "control_short_4h_pct"),
                }
            stability = {}
            for h in HORIZONS_HOURS:
                key = f"paired_edge_{h}h_pp"
                positive = sum(by_day[d][key] > 0 for d in days)
                leave_one_day_out = [
                    _stats([r for r in rows if r["event_day_utc"] != d], key)
                    for d in days
                ] if len(days) >= 2 else []
                vals = [v for v in leave_one_day_out if v is not None]
                stability[f"{h}h"] = {
                    "positive_day_count": positive,
                    "observed_day_count": len(days),
                    "fraction_days_positive": round(positive / len(days), 6) if days else None,
                    "unweighted_mean_daily_edge_pp": (
                        round(statistics.fmean(by_day[d][key] for d in days), 6)
                        if days else None),
                    "leave_one_day_out_min_edge_pp": min(vals) if vals else None,
                    "leave_one_day_out_max_edge_pp": max(vals) if vals else None,
                    "all_leave_one_day_out_positive": (
                        all(v > 0 for v in vals) if vals else None),
                }
            daily[fam] = {
                "calendar_days_with_events": len(days),
                "by_day": by_day,
                "descriptive_stability": stability,
            }
        report["daily_event_stability"] = daily
        report["daily_summary_warning"] = (
            "Non-independent, exploratory daily variation. "
            "Not an inferential test, not a p-value or proof of Short edge."
        )
        report["multiple_testing"] = (
            "8 event families x 4 outcome horizons. Do not select a "
            "winner from positive descriptive means without new untouched evidence.")
    return report

def main():
    p = argparse.ArgumentParser(description="M5 discovery only historical outcomes, no orders")
    p.add_argument("--study-id", default="m5-full-20261013-7d")
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()
    study_root = args.root / checked_id(args.study_id)
    out = args.out or (study_root / "discovery" / "v03_close_only_report.json")
    if out.exists():
        # Never silently replace a filed discovery result.
        raise RuntimeError(f"Existing discovery report is immutable: {out}")
    report = analyze(args.study_id, args.root)
    dump(out, report)
    print(json.dumps({
        "status": report["status"],
        "discovery_event_count_before_purge": report["total_discovery_events_before_purge"],
        "fully_matched_pairs": report["eligible_complete_case_and_control_pairs"],
        "attrition": report["attrition"],
        "event_summary": {
            k: {"events": v["paired_event_observations"],
                "unique_days": v["distinct_event_days"],
                "paired_edge_4h_pp": v["horizon_metrics"]["4h"]["mean_paired_edge_pp"],
                "paired_edge_8h_pp": v["horizon_metrics"]["8h"]["mean_paired_edge_pp"]}
            for k, v in report["families"].items()
        },
        "no_independent_edge_conclusion": True, "holdout_performance_disclosed": False,
        "written_to": str(out),
    }, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
