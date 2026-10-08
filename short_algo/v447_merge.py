"""V4.4.7 merge: persistent broken-support state-machine analysis."""
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
from .v447_config import V447_COOLDOWN_HOURS
from .v447_main import CSV_FIELDS


def _load(root):
    reports = []
    for path in sorted(
        glob(os.path.join(root, "**", "v447_backtest.json"), recursive=True)
    ):
        with open(path, "r", encoding="utf-8") as handle:
            reports.append(json.load(handle))
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
    for row in sorted(
        rows,
        key=lambda r: (
            str(r.get("signal_time")),
            str(r.get("symbol")),
        ),
    ):
        break_time = row.get("v447_m2_break_time")
        if not break_time:
            continue
        key = (
            str(row.get("symbol")),
            str(break_time),
            str(row.get("v447_m2_support_level")),
        )
        dedup.setdefault(key, row)
    return list(dedup.values())


def _unique_events(events):
    last = {}
    out = []
    for row in sorted(
        events,
        key=lambda r: (
            str(r.get("v447_m2_break_time")),
            str(r.get("symbol")),
        ),
    ):
        symbol = str(row.get("symbol"))
        t = pd.Timestamp(row.get("v447_m2_break_time"))
        previous = last.get(symbol)
        if (
            previous is not None
            and (t - previous)
            < pd.Timedelta(hours=int(V447_COOLDOWN_HOURS))
        ):
            continue
        last[symbol] = t
        out.append(row)
    return out


def _event_diagnostics(events):
    n = len(events)
    if not n:
        return {"events": 0}

    lifecycle = Counter(
        str(r.get("v447_m2_lifecycle") or "NONE")
        for r in events
    )
    ready_reason = Counter(
        str(r.get("v447_m2_ready_reason") or "NONE")
        for r in events
        if r.get("v447_m2_ready_time")
    )
    entry_states = Counter(
        str(r.get("v447_m2_entry_selection_state") or "NONE")
        for r in events
        if r.get("v447_m2_ready_time")
    )

    ready = [r for r in events if r.get("v447_m2_ready_time")]
    fills = [r for r in events if _terminal(r, "v447_m2")]
    return {
        "events": n,
        "lifecycle": dict(sorted(lifecycle.items())),
        "short_ready": len(ready),
        "short_ready_pct": _pct(len(ready), n),
        "ready_reason": dict(sorted(ready_reason.items())),
        "entry_selection_states": dict(sorted(entry_states.items())),
        "fills": len(fills),
        "fill_pct_of_events": _pct(len(fills), n),
        "fill_pct_of_short_ready": _pct(len(fills), len(ready)),
        "avg_watch_hours_to_ready_or_end": _mean([
            r.get("v447_m2_watch_hours") for r in events
        ]),
        "avg_watch_hours_for_fills": _mean([
            r.get("v447_m2_watch_hours") for r in fills
        ]),
        "avg_retest_attempts": _mean([
            r.get("v447_m2_retest_attempts") for r in events
        ]),
        "avg_entry_below_support_atr": _mean([
            r.get("v447_m2_entry_below_support_atr") for r in fills
        ]),
        "avg_risk_atr": _mean([
            r.get("v447_m2_risk_atr") for r in fills
        ]),
    }


def _summary(report):
    a = report["analysis"]
    lines = [
        "# Crypto Short V4.4.7 — Persistent Broken Support Watch",
        "",
        f"- Signal window: {report['period_start']} -> {report['period_end']}",
        f"- Future buffer through: {report['future_end']}",
        f"- Symbols: {report['selected_symbol_count']}",
        f"- Integrity: {'PASS' if report['manifest_integrity']['ok'] else 'FAIL'}",
        f"- Errors: {len(report['errors'])}",
        "- M2 break is confirmed by a 4H close below structural support.",
        "- The event remains alive for up to 7 days; entry is not tied to a fixed delay.",
        "- Reclaim requires consecutive 4H closes above the broken-support zone.",
        "- SHORT_READY is created by failed-reclaim touch OR persistent no-reclaim + lower-high.",
        "",
        "## Full 60d",
        "",
        "| Cohort | Opportunities | Fills | Fill% | Net R/fill | PF | Positive% | Stop% | Avg Cost R | Avg Room R |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key, label in (
        ("M1_A", "M1-A benchmark"),
        ("M1_B", "M1-B benchmark"),
        ("M2_V444", "M2 V4.4.4 baseline"),
        ("M2_PERSISTENT", "M2 persistent combined"),
        ("M2_TOUCH", "M2 failed-reclaim touch"),
        ("M2_NO_RECLAIM", "M2 persistent no-reclaim + LH"),
    ):
        x = a["full_60d"][key]
        lines.append(
            f"| {label} | {x['opportunities']} | {x['fills']} | "
            f"{x['fill_rate_pct']} | {x['net_expectancy_r']} | "
            f"{x['profit_factor']} | {x['positive_net_pct']} | "
            f"{x['stop_pct']} | {x['avg_cost_r']} | {x['avg_room_r']} |"
        )

    lines += ["", "## Unique 96h — primary decision table"]
    for key in (
        "M1_A",
        "M1_B",
        "M2_V444",
        "M2_PERSISTENT",
        "M2_TOUCH",
        "M2_NO_RECLAIM",
    ):
        lines.append(f"- {key}: {a['unique_96h'][key]}")

    lines += [
        "",
        "## Persistent-state diagnostics",
        f"- Exact events: {a['event_diagnostics_exact']}",
        f"- Unique 96h events: {a['event_diagnostics_unique']}",
        "",
        f"- Unique gates: {a['gates']}",
        "- RESEARCH_ONLY. The state machine is causal; no future path label is used to select an entry.",
    ]
    return "\n".join(lines)


def merge_reports(reports):
    if not reports:
        raise RuntimeError("No V4.4.7 shard reports found")

    expected = max(int(r.get("shard_count") or 1) for r in reports)
    found = {int(r.get("shard_index")) for r in reports}
    if found != set(range(expected)):
        raise RuntimeError(
            f"Incomplete V4.4.7 shards: {sorted(found)}"
        )

    ids = {str(r.get("manifest_id")) for r in reports}
    if len(ids) != 1:
        raise RuntimeError("V4.4.7 manifest mismatch")

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
        raise RuntimeError(
            f"V4.4.7 integrity failure: {integrity}"
        )

    dedup = {}
    for row in raw:
        dedup.setdefault(
            (row.get("symbol"), row.get("signal_time")),
            row,
        )
    rows = sorted(
        dedup.values(),
        key=lambda r: (
            str(r.get("signal_time")),
            str(r.get("symbol")),
        ),
    )
    _add_cross_section_and_phase(rows)

    m1a = [r for r in rows if _m1a(r)]
    m1b = [r for r in rows if _m1b(r)]
    m1a_u = _unique(m1a)
    m1b_u = _unique(m1b)

    v444 = [r for r in rows if _terminal(r, "v444_m2")]
    v444_u = _unique(v444)

    events = _exact_events(rows)
    events_u = _unique_events(events)
    touch = [
        r for r in events
        if r.get("v447_m2_ready_reason") == "FAILED_RECLAIM_TOUCH"
    ]
    persist = [
        r for r in events
        if r.get("v447_m2_ready_reason")
        == "PERSISTENT_NO_RECLAIM_LOWER_HIGH"
    ]
    touch_u = [
        r for r in events_u
        if r.get("v447_m2_ready_reason") == "FAILED_RECLAIM_TOUCH"
    ]
    persist_u = [
        r for r in events_u
        if r.get("v447_m2_ready_reason")
        == "PERSISTENT_NO_RECLAIM_LOWER_HIGH"
    ]

    full = {
        "M1_A": _entry_metrics(m1a, "v440"),
        "M1_B": _entry_metrics(m1b, "v441_m1"),
        "M2_V444": _entry_metrics(v444, "v444_m2"),
        "M2_PERSISTENT": _entry_metrics(events, "v447_m2"),
        "M2_TOUCH": _entry_metrics(touch, "v447_m2"),
        "M2_NO_RECLAIM": _entry_metrics(persist, "v447_m2"),
    }
    unique = {
        "M1_A": _entry_metrics(m1a_u, "v440"),
        "M1_B": _entry_metrics(m1b_u, "v441_m1"),
        "M2_V444": _entry_metrics(v444_u, "v444_m2"),
        "M2_PERSISTENT": _entry_metrics(events_u, "v447_m2"),
        "M2_TOUCH": _entry_metrics(touch_u, "v447_m2"),
        "M2_NO_RECLAIM": _entry_metrics(persist_u, "v447_m2"),
    }

    gates = {key: _gate(value) for key, value in unique.items()}
    analysis = {
        "counts": {
            "raw": len(rows),
            "m1_a_opportunities": len(m1a),
            "m1_b_opportunities": len(m1b),
            "m2_exact_events": len(events),
            "m2_unique_events": len(events_u),
        },
        "full_60d": full,
        "unique_96h": unique,
        "event_diagnostics_exact": _event_diagnostics(events),
        "event_diagnostics_unique": _event_diagnostics(events_u),
        "gates": gates,
        "research_status": "RESEARCH_ONLY",
        "persistent_watch_days": 7,
        "future_path_labels_used_for_entry": False,
        "fixed_parameter_run": True,
        "parameter_grid_searched": False,
    }

    return {
        "engine": "Crypto Short V4.4.7 Persistent Broken Support Watch",
        "manifest_id": next(iter(ids)),
        "manifest": first.get("manifest"),
        "manifest_integrity": integrity,
        "period_start": first.get("period_start"),
        "period_end": first.get("period_end"),
        "future_end": first.get("future_end"),
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
    _write_json(
        os.path.join(OUTPUT_DIR, "v447_backtest.json"),
        report,
    )
    _write_json(
        os.path.join(OUTPUT_DIR, "v447_analysis.json"),
        report["analysis"],
    )
    _write_json(
        os.path.join(OUTPUT_DIR, "v447_manifest.json"),
        report["manifest"],
    )
    fields = CSV_FIELDS + [
        "v428_trend_phase",
        "v428_structure_score",
        "v428_exhaustion_score",
        "v428_recovery_score",
    ]
    _write_csv(
        os.path.join(OUTPUT_DIR, "v447_scored_candidates.csv"),
        report["trades"],
        fields=fields,
    )
    with open(
        os.path.join(OUTPUT_DIR, "v447_summary.md"),
        "w",
        encoding="utf-8",
    ) as handle:
        handle.write(_summary(report))

    print(json.dumps({
        "integrity": report["manifest_integrity"],
        "errors": len(report["errors"]),
        "analysis": report["analysis"],
    }, ensure_ascii=False, indent=2))
    return 0 if not report["errors"] else 2


if __name__ == "__main__":
    sys.exit(main())
