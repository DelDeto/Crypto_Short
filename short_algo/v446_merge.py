"""V4.4.6 merge: unchanged M1 E0 baselines + M2 1-3h retest window."""
import json
import os
import sys
from collections import Counter
from glob import glob

import numpy as np
import pandas as pd

from .config import OUTPUT_DIR
from .v428_merge import _add_cross_section_and_phase
from .v441_main import _write_csv, _write_json
from .v443_merge import _gate, _m1a, _m1b, _metrics, _terminal, _unique
from .v445_merge import _entry_metrics
from .v446_config import V446_COOLDOWN_HOURS
from .v446_main import CSV_FIELDS


def _load(root):
    reports = []
    for path in sorted(glob(os.path.join(root, "**", "v446_backtest.json"), recursive=True)):
        with open(path, "r", encoding="utf-8") as f:
            reports.append(json.load(f))
    return reports


def _num(value):
    try:
        x = float(value)
        return x if np.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _mean(values):
    vals = [x for x in (_num(v) for v in values) if x is not None]
    return round(float(np.mean(vals)), 5) if vals else None


def _pct(n, d):
    return round(100.0 * n / d, 2) if d else None


def _exact_events(rows):
    dedup = {}
    for row in sorted(rows, key=lambda r: (str(r.get("signal_time")), str(r.get("symbol")))):
        if int(row.get("v446_m2_event_found") or 0) != 1:
            continue
        bt = row.get("v446_m2_event_break_time")
        if not bt:
            continue
        dedup.setdefault((str(row.get("symbol")), str(bt)), row)
    return list(dedup.values())


def _unique_events(rows):
    last = {}
    out = []
    for row in sorted(
        rows,
        key=lambda r: (str(r.get("v446_m2_event_break_time")), str(r.get("symbol"))),
    ):
        symbol = str(row.get("symbol"))
        t = pd.Timestamp(row.get("v446_m2_event_break_time"))
        previous = last.get(symbol)
        if previous is not None and (t - previous) < pd.Timedelta(hours=int(V446_COOLDOWN_HOURS)):
            continue
        last[symbol] = t
        out.append(row)
    return out


def _selection_stats(events, prefix):
    states = Counter(str(r.get(f"{prefix}_state") or "NONE") for r in events)
    fills = [r for r in events if _terminal(r, prefix)]
    return {
        "events": len(events),
        "states": dict(sorted(states.items())),
        "early_retest_pct": _pct(
            sum(int(r.get(f"{prefix}_early_retest") or 0) == 1 for r in events),
            len(events),
        ),
        "avg_retest_bars_after_break": _mean([
            r.get(f"{prefix}_retest_bars_after_break") for r in fills
        ]),
        "avg_pre_extension_atr": _mean([
            r.get(f"{prefix}_pre_extension_atr") for r in fills
        ]),
        "avg_entry_below_support_atr": _mean([
            r.get(f"{prefix}_entry_below_support_atr") for r in fills
        ]),
        "avg_acceptance_closes": _mean([
            r.get(f"{prefix}_acceptance_closes") for r in fills
        ]),
        "avg_rejection_wick_ratio": _mean([
            r.get(f"{prefix}_rejection_wick_ratio") for r in fills
        ]),
    }


def _summary(report):
    a = report["analysis"]
    lines = [
        "# Crypto Short V4.4.6 — Retest Window 60d",
        "",
        f"- Period: {report['period_start']} -> {report['period_end']}",
        f"- Symbols: {report['selected_symbol_count']}",
        f"- Integrity: {'PASS' if report['manifest_integrity']['ok'] else 'FAIL'}",
        f"- Errors: {len(report['errors'])}",
        "- M1-A/M1-B keep their original E0 next-open entry.",
        "- M2 only looks for a failed reclaim from 1h to 3h after support breakdown.",
        "- R1 balanced: >=2 acceptance closes, pre-extension <=1.25ATR, entry <=0.30ATR below support.",
        "- R2 strict: >=3 acceptance closes, pre-extension <=0.90ATR, entry <=0.20ATR below support.",
        "",
        "## Full 60d",
        "",
        "| Cohort | Opportunities | Fills | Fill% | Net R/fill | PF | Positive% | Stop% | Avg Cost R | Avg Room R |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key, label in (
        ("M1_A_E0", "M1-A E0"),
        ("M1_B_E0", "M1-B E0"),
        ("M2_E0_V444", "M2 V4.4.4 baseline"),
        ("M2_R1", "M2 R1 1-3h balanced"),
        ("M2_R2", "M2 R2 1-3h strict"),
    ):
        x = a["full_60d"][key]
        lines.append(
            f"| {label} | {x['opportunities']} | {x['fills']} | {x['fill_rate_pct']} | "
            f"{x['net_expectancy_r']} | {x['profit_factor']} | {x['positive_net_pct']} | "
            f"{x['stop_pct']} | {x['avg_cost_r']} | {x['avg_room_r']} |"
        )

    lines += ["", "## Unique 96h — primary decision table"]
    for key in ("M1_A_E0", "M1_B_E0", "M2_E0_V444", "M2_R1", "M2_R2"):
        lines.append(f"- {key}: {a['unique_96h'][key]}")

    lines += [
        "",
        "## Retest-window diagnostics",
        f"- Exact break events: {a['counts']['m2_exact_break_events']}",
        f"- Unique 96h break events: {a['counts']['m2_unique_break_events']}",
        f"- R1 exact: {a['r1_selection_stats']}",
        f"- R2 exact: {a['r2_selection_stats']}",
        f"- R1 unique: {a['r1_unique_selection_stats']}",
        f"- R2 unique: {a['r2_unique_selection_stats']}",
        "",
        f"- Unique gates: {a['gates']}",
        "- RESEARCH_ONLY. The 1-3h rule was discovered from the prior 60d study, so a later untouched window is still required before deployment.",
    ]
    return "\n".join(lines)


def merge_reports(reports):
    if not reports:
        raise RuntimeError("No V4.4.6 shard reports found")

    expected = max(int(r.get("shard_count") or 1) for r in reports)
    found = {int(r.get("shard_index")) for r in reports}
    if found != set(range(expected)):
        raise RuntimeError(f"Incomplete V4.4.6 shards: {sorted(found)}")

    ids = {str(r.get("manifest_id")) for r in reports}
    if len(ids) != 1:
        raise RuntimeError("V4.4.6 manifest mismatch")

    first = reports[0]
    frozen = set((first.get("manifest") or {}).get("symbols") or [])
    symbols, raw, errors = [], [], []
    for report in reports:
        symbols.extend(report.get("selected_symbols") or [])
        raw.extend(report.get("trades") or [])
        errors.extend(report.get("errors") or [])

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
        raise RuntimeError(f"V4.4.6 integrity failure: {integrity}")

    dedup = {}
    for row in raw:
        dedup.setdefault((row.get("symbol"), row.get("signal_time")), row)
    rows = sorted(
        dedup.values(),
        key=lambda r: (str(r.get("signal_time")), str(r.get("symbol"))),
    )
    _add_cross_section_and_phase(rows)

    m1a = [r for r in rows if _m1a(r)]
    m1b = [r for r in rows if _m1b(r)]
    m1a_u = _unique(m1a)
    m1b_u = _unique(m1b)

    events = _exact_events(rows)
    events_u = _unique_events(events)
    v444 = [r for r in rows if _terminal(r, "v444_m2")]
    v444_u = _unique(v444)

    full = {
        "M1_A_E0": _entry_metrics(m1a, "v440"),
        "M1_B_E0": _entry_metrics(m1b, "v441_m1"),
        "M2_E0_V444": _entry_metrics(v444, "v444_m2"),
        "M2_R1": _entry_metrics(events, "v446_m2_r1"),
        "M2_R2": _entry_metrics(events, "v446_m2_r2"),
    }
    unique = {
        "M1_A_E0": _entry_metrics(m1a_u, "v440"),
        "M1_B_E0": _entry_metrics(m1b_u, "v441_m1"),
        "M2_E0_V444": _entry_metrics(v444_u, "v444_m2"),
        "M2_R1": _entry_metrics(events_u, "v446_m2_r1"),
        "M2_R2": _entry_metrics(events_u, "v446_m2_r2"),
    }

    gates = {k: _gate(v) for k, v in unique.items()}
    analysis = {
        "counts": {
            "raw": len(rows),
            "m1_a_opportunities": len(m1a),
            "m1_b_opportunities": len(m1b),
            "m2_exact_break_events": len(events),
            "m2_unique_break_events": len(events_u),
        },
        "full_60d": full,
        "unique_96h": unique,
        "r1_selection_stats": _selection_stats(events, "v446_m2_r1"),
        "r2_selection_stats": _selection_stats(events, "v446_m2_r2"),
        "r1_unique_selection_stats": _selection_stats(events_u, "v446_m2_r1"),
        "r2_unique_selection_stats": _selection_stats(events_u, "v446_m2_r2"),
        "gates": gates,
        "research_status": "RESEARCH_ONLY",
        "future_24h_labels_used_for_entry": False,
        "fixed_parameter_run": True,
        "parameter_grid_searched": False,
    }

    return {
        "engine": "Crypto Short V4.4.6 Retest Window Research",
        "manifest_id": next(iter(ids)),
        "manifest": first.get("manifest"),
        "manifest_integrity": integrity,
        "period_start": first.get("period_start"),
        "period_end": first.get("period_end"),
        "days": first.get("days"),
        "selected_symbols": sorted(unique_symbols),
        "selected_symbol_count": len(unique_symbols),
        "analysis": analysis,
        "trades": rows,
        "errors": errors,
    }


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "shard_outputs"
    report = merge_reports(_load(root))
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR, "v446_backtest.json"), report)
    _write_json(os.path.join(OUTPUT_DIR, "v446_analysis.json"), report["analysis"])
    _write_json(os.path.join(OUTPUT_DIR, "v446_manifest.json"), report["manifest"])
    fields = CSV_FIELDS + [
        "v428_trend_phase",
        "v428_structure_score",
        "v428_exhaustion_score",
        "v428_recovery_score",
    ]
    _write_csv(
        os.path.join(OUTPUT_DIR, "v446_scored_candidates.csv"),
        report["trades"],
        fields=fields,
    )
    with open(os.path.join(OUTPUT_DIR, "v446_summary.md"), "w", encoding="utf-8") as f:
        f.write(_summary(report))

    print(json.dumps({
        "integrity": report["manifest_integrity"],
        "errors": len(report["errors"]),
        "analysis": report["analysis"],
    }, ensure_ascii=False, indent=2))
    return 0 if not report["errors"] else 2


if __name__ == "__main__":
    sys.exit(main())
