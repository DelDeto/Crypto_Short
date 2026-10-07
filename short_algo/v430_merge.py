"""V4.3.0 research-only merge and paired A/B/C execution comparison.

A and B share the same timestamped setup, but B may not fill.
C is conditional on *realized A stop*, not a future oracle.
Raw observations and de-overlapped episodes are reported separately.
"""
import json
import os
import sys
from collections import Counter, defaultdict
from glob import glob

import numpy as np
import pandas as pd

from .config import OUTPUT_DIR
from .v428_merge import _add_cross_section_and_phase
from .v429_merge import _walk_forward, _diag, _auc, SCORED_FIELDS as V429_SCORED
from .v430_config import V430_COOLDOWN_HOURS, V430_COST_BPS, V430_STRUCTURAL_ROOM_R
from .v430_main import CSV_FIELDS, _write_csv, _write_json


EXTRA_SCORE_FIELDS = [
    f for f in V429_SCORED if f not in CSV_FIELDS
] + ["v430_core_structure", "v430_research_status", "v430_unique_episode"]
SCORED_FIELDS = CSV_FIELDS + EXTRA_SCORE_FIELDS

TERMINAL_STATES = ("TP2R_FIRST", "SL_FIRST", "SL_SAME_BAR", "TIME_EXIT")
STOP_STATES = ("SL_FIRST", "SL_SAME_BAR")


def _load(root):
    reports = []
    for path in sorted(glob(os.path.join(root, "**", "v430_backtest.json"), recursive=True)):
        with open(path, "r", encoding="utf-8") as f:
            reports.append(json.load(f))
    return reports


def _number(value):
    try:
        x = float(value)
        return x if np.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _mean(values):
    nums = [v for v in (_number(x) for x in values) if v is not None]
    return round(float(np.mean(nums)), 5) if nums else None


def _pct(num, denom):
    return round(100.0 * num / denom, 2) if denom else None


def _mode(rows, mode):
    opportunity = len(rows)
    statekey = f"v430_{mode}_state"
    netkey = f"v430_{mode}_net_r"
    grosskey = f"v430_{mode}_gross_r"
    states = Counter(str(r.get(statekey) or "NONE") for r in rows)
    filled = [r for r in rows if r.get(statekey) in TERMINAL_STATES and _number(r.get(netkey)) is not None]
    wins = sum(r.get(statekey) == "TP2R_FIRST" for r in filled)
    stop = sum(r.get(statekey) in STOP_STATES for r in filled)
    positive = sum(float(r[netkey]) > 0 for r in filled)
    net_values = [float(r[netkey]) for r in filled]
    gross_values = [float(r[grosskey]) for r in filled]
    total_net = sum(net_values)
    total_gross = sum(gross_values)
    return {
        "opportunities": opportunity,
        "filled": len(filled),
        "fill_rate_pct": _pct(len(filled), opportunity),
        "tp2r_first": wins,
        "tp2r_first_pct_of_filled": _pct(wins, len(filled)),
        "sl_first": stop,
        "sl_pct_of_filled": _pct(stop, len(filled)),
        "positive_net_pct_of_filled": _pct(positive, len(filled)),
        "gross_expectancy_r_per_fill": _mean(gross_values),
        "net_expectancy_r_per_fill": _mean(net_values),
        "net_expectancy_r_per_opportunity": (
            round(total_net / opportunity, 5) if opportunity else None
        ),
        "total_gross_r": round(total_gross, 5),
        "total_net_r": round(total_net, 5),
        "avg_cost_r": _mean([r.get(f"v430_{mode}_cost_r") for r in filled]),
        "avg_risk_pct": _mean([r.get(f"v430_{mode}_risk_pct") for r in filled]),
        "avg_wait_15m_bars": _mean([r.get(f"v430_{mode}_wait_bars") for r in filled]),
        "states": dict(sorted(states.items())),
    }


def _paired(rows):
    a = _mode(rows, "A")
    b = _mode(rows, "B")
    c = _mode(rows, "C")
    paired = [
        r for r in rows
        if _number(r.get("v430_A_net_r")) is not None
        and _number(r.get("v430_B_net_r")) is not None
    ]
    both_delta = [
        float(r["v430_B_net_r"]) - float(r["v430_A_net_r"]) for r in paired
    ]
    aplusc = [
        r for r in rows
        if _number(r.get("v430_AplusC_net_r")) is not None
    ]
    aplusc_net = [float(r["v430_AplusC_net_r"]) for r in aplusc]
    a_stopped = [r for r in rows if r.get("v430_A_state") in STOP_STATES]
    c_filled_after_stop = sum(
        r.get("v430_C_state") in TERMINAL_STATES for r in a_stopped
    )
    return {
        "opportunities": len(rows),
        "A_immediate": a,
        "B_pullback_confirm": b,
        "C_after_stop_reentry_only": c,
        "A_plus_C_sequential": {
            "filled_primary": len(aplusc),
            "reentry_filled": c_filled_after_stop,
            "A_stops": len(a_stopped),
            "reentry_rate_per_A_stop_pct": _pct(c_filled_after_stop, len(a_stopped)),
            "mean_net_r_per_A_filled": _mean(aplusc_net),
            "mean_net_r_per_original_opportunity": (
                round(sum(aplusc_net) / len(rows), 5) if rows else None
            ),
            "total_net_r": round(sum(aplusc_net), 5),
            "positive_net_pct": _pct(sum(x > 0 for x in aplusc_net), len(aplusc_net)),
            "extra_r_per_A_stop": _mean([
                r.get("v430_C_net_r") for r in a_stopped
            ]),
        },
        "B_minus_A_same_filled": {
            "both_filled": len(paired),
            "mean_net_r_delta": _mean(both_delta),
            "B_better_pct": _pct(sum(d > 0 for d in both_delta), len(both_delta)),
        },
        "B_minus_A_per_opportunity_net_r": (
            round(
                b["net_expectancy_r_per_opportunity"] - a["net_expectancy_r_per_opportunity"], 5
            ) if a["net_expectancy_r_per_opportunity"] is not None
            and b["net_expectancy_r_per_opportunity"] is not None else None
        ),
    }


def _unique(rows, hours=V430_COOLDOWN_HOURS):
    """First eligible setup per symbol in a fixed time window, without using outcomes."""
    last = {}
    selected = []
    for row in sorted(rows, key=lambda r: (str(r["signal_time"]), str(r["symbol"]))):
        sym = str(row["symbol"])
        t = pd.Timestamp(row["signal_time"])
        previous = last.get(sym)
        if previous is not None and (t - previous) < pd.Timedelta(hours=int(hours)):
            row["v430_unique_episode"] = 0
            continue
        row["v430_unique_episode"] = 1
        last[sym] = t
        selected.append(row)
    return selected


def _tier(rows):
    return dict(sorted(Counter(str(r.get("v430_support_class") or "UNKNOWN") for r in rows).items()))


def _summary(report):
    a = report["analysis"]
    lines = [
        "# Crypto Short V4.3.0 — Three Execution Policies, Frozen Support Tiers",
        "",
        f"- Period: {report['period_start']} → {report['period_end']}",
        f"- 120-coin cohort target; actual symbols: {report['selected_symbol_count']}",
        f"- Integrity: {'PASS' if report['manifest_integrity']['ok'] else 'FAIL'}",
        f"- Errors: {len(report['errors'])}",
        f"- Median coins/timestamp: {a['cross_section_median']}",
        f"- Fees + assumed round-trip slippage: {V430_COST_BPS}bps, deducted in R.",
        "- Findings are RESEARCH_ONLY, not deployed to live V1.",
        "",
        "## Filtering attrition",
        f"- EARLY_DOWNTREND + entry confirmed: {a['cohort_counts']['early_confirmed']}",
        f"- Strict 4h structure + strong zone: {a['cohort_counts']['strict_structure']}",
        f"- Structural support known: {a['cohort_counts']['known_structural']}",
        f"- Structural room >= {V430_STRUCTURAL_ROOM_R}R: {a['cohort_counts']['support_pass']}",
        f"- Independent strict episodes (per symbol {V430_COOLDOWN_HOURS}h cooldown): {a['cohort_counts']['unique_strict']}",
        f"- Support classes in EARLY confirmed: {a['support_classes_early']}",
        "",
        "## Three execution policies — same EARLY confirmed opportunities",
        "",
        "| Policy | Filled/opp | TP2R/fills | SL/fills | Net Exp/fill R | Net Exp/opportunity R |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for key, label in (("A_immediate", "A immediate"), ("B_pullback_confirm", "B pullback"),
                       ("C_after_stop_reentry_only", "C after A stop")):
        x = a["early_confirmed_paired"][key]
        lines.append(
            f"| {label} | {x['filled']}/{x['opportunities']} | "
            f"{x['tp2r_first_pct_of_filled']} | {x['sl_pct_of_filled']} | "
            f"{x['net_expectancy_r_per_fill']} | {x['net_expectancy_r_per_opportunity']} |"
        )
    combo = a["early_confirmed_paired"]["A_plus_C_sequential"]
    lines += [
        f"| A + conditional C | {combo['filled_primary']}/{a['cohort_counts']['early_confirmed']} | — | — | "
        f"{combo['mean_net_r_per_A_filled']} | {combo['mean_net_r_per_original_opportunity']} |",
        "",
        "## Execution-only effect in strict support-pass subset",
    ]
    strict = a["strict_support_pass_paired"]
    for key in ("A_immediate", "B_pullback_confirm", "C_after_stop_reentry_only"):
        x = strict[key]
        lines.append(
            f"- {key}: filled {x['filled']}/{x['opportunities']}; TP2 {x['tp2r_first']} ; "
            f"net expectancy/fill {x['net_expectancy_r_per_fill']}R; "
            f"per opportunity {x['net_expectancy_r_per_opportunity']}R."
        )
    lines += [
        f"- A+C: {strict['A_plus_C_sequential']['mean_net_r_per_original_opportunity']}R per opportunity.",
        "",
        "## Biases and controls",
        "- Structural support uses confirmed 4H pivots known at signal time; "
        "minor/intermediate supports are disclosed, not incorrectly assumed to be absolute floors.",
        "- Missing structural support is UNKNOWN, never treated as unlimited R room.",
        "- Only closed 15m candles trigger B/C; orders fill at the following 15m open.",
        "- SL/TP collision in the same candle counts as SL; costs deducted and no costless re-entry.",
        "- C requires a realized A stop, bearish reclaim back below old invalidation, "
        "one new trade maximum and a capped stop size.",
        "- A+B results include no-fill cases; the per-fill metric alone has fill-selection bias.",
        "- Labels have 24h holding horizon; no funding, liquidity/orderbook impact or portfolio equity sim.",
        "- Multiple signals can overlap; 96h nonoverlap episodes provided separately.",
        "- Current turnover defines frozen history universe; historical delistings not included.",
        "- This 60-day iteration reused previously inspected periods; NOT an untouched holdout.",
        "",
    ]
    return "\n".join(lines)


def merge_reports(reports):
    if not reports:
        raise RuntimeError("No V4.3.0 shards found")
    expected = max(int(r.get("shard_count") or 1) for r in reports)
    found = {int(r.get("shard_index")) for r in reports}
    if found != set(range(expected)):
        raise RuntimeError(f"Incomplete V4.3 shards: {sorted(found)}")

    ids = {str(r.get("manifest_id")) for r in reports}
    if len(ids) != 1:
        raise RuntimeError("V4.3 manifest mismatch")
    first = reports[0]
    frozen = set((first.get("manifest") or {}).get("symbols") or [])

    symbols, raw, errors = [], [], []
    for r in reports:
        symbols.extend(r.get("selected_symbols") or [])
        raw.extend(r.get("trades") or [])
        errors.extend(r.get("errors") or [])
    unique_symbols = set(symbols)
    integrity = {
        "ok": (
            len(reports) == expected
            and len(symbols) == len(unique_symbols)
            and unique_symbols == frozen
        ),
        "expected_shards": expected,
        "found_shards": len(reports),
        "frozen_symbol_count": len(frozen),
        "merged_symbol_count": len(unique_symbols),
    }
    if not integrity["ok"]:
        raise RuntimeError(f"V4.3 manifest mismatch: {integrity}")

    dedup = {}
    for row in raw:
        dedup.setdefault((row.get("symbol"), row.get("signal_time")), row)
    raw_rows = sorted(
        dedup.values(),
        key=lambda r: (str(r.get("signal_time")), str(r.get("symbol"))),
    )
    _add_cross_section_and_phase(raw_rows)
    scored, folds, model_meta = _walk_forward(raw_rows)

    early = [
        r for r in scored
        if r.get("v428_trend_phase") == "EARLY_DOWNTREND"
        and int(r.get("v428_entry_confirmed") or 0) == 1
    ]
    strict_structure = [
        r for r in early if int(r.get("v429_core_preconfirm") or 0) == 1
    ]
    known_structure = [
        r for r in strict_structure if r.get("v430_support_structural") is not None
    ]
    support_pass = [
        r for r in strict_structure if int(r.get("v430_support_pass") or 0) == 1
    ]
    for row in scored:
        strict = int(
            row.get("v428_trend_phase") == "EARLY_DOWNTREND"
            and int(row.get("v428_entry_confirmed") or 0) == 1
            and int(row.get("v429_core_preconfirm") or 0) == 1
        )
        row["v430_core_structure"] = strict
        if strict and int(row.get("v430_support_pass") or 0) == 1:
            status = "V430_RESEARCH_ENTRY"
        elif strict and row.get("v430_support_structural") is None:
            status = "SUPPORT_UNKNOWN_REVIEW"
        elif strict:
            status = "INSUFFICIENT_STRUCTURAL_ROOM"
        else:
            status = "RESEARCH_WATCH"
        row["v430_research_status"] = status
        row["v430_unique_episode"] = 0

    unique_strict = _unique(support_pass)
    unique_early = _unique(early)
    statuses = Counter(str(r["v430_research_status"]) for r in scored)
    counts_by_time = Counter(str(r["signal_time"]) for r in scored)
    analysis = {
        "raw_count": len(raw_rows),
        "oos_count": len(scored),
        "cross_section_median": (
            round(float(np.median(list(counts_by_time.values()))), 2)
            if counts_by_time else None
        ),
        "cohort_counts": {
            "early_confirmed": len(early),
            "strict_structure": len(strict_structure),
            "known_structural": len(known_structure),
            "support_pass": len(support_pass),
            "unique_strict": len(unique_strict),
            "unique_early": len(unique_early),
        },
        "status_counts": dict(sorted(statuses.items())),
        "support_classes_early": _tier(early),
        "support_classes_strict": _tier(strict_structure),
        "early_confirmed_outcome_diagnostic": _diag(early),
        "early_confirmed_paired": _paired(early),
        "strict_structure_paired": _paired(strict_structure),
        "strict_support_pass_paired": _paired(support_pass),
        "unique_early_paired": _paired(unique_early),
        "unique_strict_paired": _paired(unique_strict),
        "oos_auc": {
            "4h": _auc(scored, "p_4h_lower", "y_4h_lower"),
            "12h": _auc(scored, "p_12h_lower", "y_12h_lower"),
            "24h": _auc(scored, "p_24h_lower", "y_24h_lower"),
            "reversal": _auc(scored, "p_reversal_after_short", "y_reversal_after_short"),
            "confirmed2r": _auc(scored, "p_confirmed_2r", "y_confirmed_2r_success"),
        },
        "folds": folds,
    }
    return {
        "engine": "Crypto Short V4.3.0 Execution A/B/C Research Only",
        "manifest_id": next(iter(ids)),
        "manifest": first.get("manifest"),
        "manifest_integrity": integrity,
        "period_start": first.get("period_start"),
        "period_end": first.get("period_end"),
        "days": first.get("days"),
        "selected_symbols": sorted(unique_symbols),
        "selected_symbol_count": len(unique_symbols),
        "analysis": analysis,
        "model_meta": model_meta,
        "trades": scored,
        "errors": errors,
    }


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "shard_outputs"
    report = merge_reports(_load(root))
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR, "v430_backtest.json"), report)
    _write_json(os.path.join(OUTPUT_DIR, "v430_analysis.json"), report["analysis"])
    _write_json(os.path.join(OUTPUT_DIR, "v430_model_meta.json"), report["model_meta"])
    _write_json(os.path.join(OUTPUT_DIR, "v430_manifest.json"), report["manifest"])
    _write_csv(
        os.path.join(OUTPUT_DIR, "v430_scored_candidates.csv"),
        report["trades"],
        fields=SCORED_FIELDS,
    )
    with open(os.path.join(OUTPUT_DIR, "v430_summary.md"), "w", encoding="utf-8") as f:
        f.write(_summary(report))

    a = report["analysis"]
    print(json.dumps({
        "integrity": report["manifest_integrity"],
        "errors": len(report["errors"]),
        "cohorts": a["cohort_counts"],
        "support_classes": a["support_classes_early"],
        "A_B_C_all_early": a["early_confirmed_paired"],
        "A_B_C_strict": a["strict_support_pass_paired"],
        "A_B_C_unique_strict": a["unique_strict_paired"],
        "oos_auc": a["oos_auc"],
    }, ensure_ascii=False, indent=2))
    # Force failure on data errors, not just an apparently successful merge.
    return 0 if not report["errors"] else 2


if __name__ == "__main__":
    sys.exit(main())
