"""V4.4.5 merge: M1 entry timing + M2 24h breakdown event study."""
import json
import os
import sys
from glob import glob

import numpy as np
import pandas as pd

from .config import OUTPUT_DIR
from .v428_merge import _add_cross_section_and_phase
from .v441_main import _write_csv, _write_json
from .v443_merge import _gate, _m1a, _m1b, _metrics, _terminal, _unique
from .v445_config import V445_COOLDOWN_HOURS
from .v445_main import CSV_FIELDS


def _load(root):
    reports = []
    for path in sorted(glob(os.path.join(root, "**", "v445_backtest.json"), recursive=True)):
        with open(path, "r", encoding="utf-8") as f:
            reports.append(json.load(f))
    return reports


def _num(v):
    try:
        x = float(v)
        return x if np.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _pct(n, d):
    return round(100.0 * n / d, 2) if d else None


def _mean(vals):
    x = [v for v in (_num(z) for z in vals) if v is not None]
    return round(float(np.mean(x)), 5) if x else None


def _entry_metrics(opportunities, prefix):
    m = _metrics(opportunities, prefix)
    m["opportunities"] = len(opportunities)
    m["fill_rate_pct"] = _pct(m.get("fills") or 0, len(opportunities))
    return m


def _exact_break_events(rows):
    dedup = {}
    for row in sorted(rows, key=lambda r: (str(r.get("signal_time")), str(r.get("symbol")))):
        if int(row.get("v445_m2_event_found") or 0) != 1:
            continue
        bt = row.get("v445_m2_event_break_time")
        if not bt:
            continue
        dedup.setdefault((str(row.get("symbol")), str(bt)), row)
    return list(dedup.values())


def _unique_break_events(rows):
    last = {}
    out = []
    for row in sorted(rows, key=lambda r: (str(r.get("v445_m2_event_break_time")), str(r.get("symbol")))):
        symbol = str(row.get("symbol"))
        t = pd.Timestamp(row.get("v445_m2_event_break_time"))
        previous = last.get(symbol)
        if previous is not None and (t - previous) < pd.Timedelta(hours=int(V445_COOLDOWN_HOURS)):
            continue
        last[symbol] = t
        out.append(row)
    return out


def _event_stats(rows):
    n = len(rows)
    if not n:
        return {"events": 0}
    ext = [_num(r.get("v445_m2_event_24h_max_extension_atr")) for r in rows]
    rec = [_num(r.get("v445_m2_event_24h_max_reclaim_atr")) for r in rows]
    consec = [_num(r.get("v445_m2_event_24h_max_consecutive_below")) for r in rows]
    end = [_num(r.get("v445_m2_event_24h_end_close_below_atr")) for r in rows]
    return {
        "events": n,
        "acceptance3_pct": _pct(sum(x is not None and x >= 3 for x in consec), n),
        "extension_ge_1atr_pct": _pct(sum(x is not None and x >= 1 for x in ext), n),
        "extension_ge_2atr_pct": _pct(sum(x is not None and x >= 2 for x in ext), n),
        "extension_ge_3atr_pct": _pct(sum(x is not None and x >= 3 for x in ext), n),
        "hard_reclaim_gt_0_30atr_pct": _pct(sum(x is not None and x > 0.30 for x in rec), n),
        "ends_below_support_pct": _pct(sum(x is not None and x > 0 for x in end), n),
        "avg_24h_extension_atr": _mean(ext),
        "avg_24h_reclaim_atr": _mean(rec),
        "avg_end_close_below_atr": _mean(end),
        "avg_first_retest_bars": _mean([
            r.get("v445_m2_event_24h_first_retest_bars") for r in rows
        ]),
        "avg_first_1atr_extension_bars": _mean([
            r.get("v445_m2_event_24h_first_1atr_extension_bars") for r in rows
        ]),
    }


def _summary(report):
    a = report["analysis"]
    lines = [
        "# Crypto Short V4.4.5 — 60d Execution Lab",
        "",
        f"- Period: {report['period_start']} -> {report['period_end']}",
        f"- Symbols: {report['selected_symbol_count']}",
        f"- Integrity: {'PASS' if report['manifest_integrity']['ok'] else 'FAIL'}",
        f"- Errors: {len(report['errors'])}",
        "- M1 setup detection is unchanged; only entry timing differs.",
        "- M2 24h path is diagnostic only. Trade rules A/B/C use only information known before their entry.",
        "",
        "## M1 Entry Lab — full 60d",
        "",
        "| Cohort | Opportunities | Fills | Fill% | Net R/fill | PF | Positive% | Stop% | Avg Cost R | Avg Room R |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key, label in (
        ("M1_A_E0", "M1-A E0 next-open"),
        ("M1_A_E1", "M1-A E1 50% retest <=2h"),
        ("M1_A_E2", "M1-A E2 65% retest <=4h"),
        ("M1_B_E0", "M1-B E0 next-open"),
        ("M1_B_E1", "M1-B E1 50% retest <=2h"),
        ("M1_B_E2", "M1-B E2 65% retest <=4h"),
    ):
        x = a["m1_full_60d"][key]
        lines.append(
            f"| {label} | {x['opportunities']} | {x['fills']} | {x['fill_rate_pct']} | "
            f"{x['net_expectancy_r']} | {x['profit_factor']} | {x['positive_net_pct']} | "
            f"{x['stop_pct']} | {x['avg_cost_r']} | {x['avg_room_r']} |"
        )

    lines += [
        "",
        "## M1 Unique 96h — primary comparison",
    ]
    for key in ("M1_A_E0","M1_A_E1","M1_A_E2","M1_B_E0","M1_B_E1","M1_B_E2"):
        lines.append(f"- {key}: {a['m1_unique_96h'][key]}")

    lines += [
        "",
        "## M2 breakdown event study — future 24h diagnostics only",
        f"- Exact events: {a['m2_event_stats_exact']}",
        f"- Unique 96h events: {a['m2_event_stats_unique']}",
        "",
        "## M2 causal entry variants — full 60d",
        "",
        "| Cohort | Opportunities | Fills | Fill% | Net R/fill | PF | Positive% | Stop% | Avg Cost R | Avg Room R |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key, label in (
        ("M2_E0_V444", "M2 E0 V4.4.4"),
        ("M2_A_ACCEPT3", "M2-A 3 closes acceptance"),
        ("M2_B_NEAR", "M2-B acceptance + near <=0.20ATR"),
        ("M2_C_RETEST", "M2-C acceptance + failed reclaim"),
    ):
        x = a["m2_full_60d"][key]
        lines.append(
            f"| {label} | {x['opportunities']} | {x['fills']} | {x['fill_rate_pct']} | "
            f"{x['net_expectancy_r']} | {x['profit_factor']} | {x['positive_net_pct']} | "
            f"{x['stop_pct']} | {x['avg_cost_r']} | {x['avg_room_r']} |"
        )

    lines += [
        "",
        "## M2 Unique 96h — primary comparison",
    ]
    for key in ("M2_E0_V444","M2_A_ACCEPT3","M2_B_NEAR","M2_C_RETEST"):
        lines.append(f"- {key}: {a['m2_unique_96h'][key]}")

    lines += [
        "",
        f"- Unique validation gates: {a['gates']}",
        "- RESEARCH_ONLY. Any rule discovered from this 60d window must be locked before testing on a different window.",
    ]
    return "\n".join(lines)


def merge_reports(reports):
    if not reports:
        raise RuntimeError("No V4.4.5 shard reports found")

    expected = max(int(r.get("shard_count") or 1) for r in reports)
    found = {int(r.get("shard_index")) for r in reports}
    if found != set(range(expected)):
        raise RuntimeError(f"Incomplete V4.4.5 shards: {sorted(found)}")

    ids = {str(r.get("manifest_id")) for r in reports}
    if len(ids) != 1:
        raise RuntimeError("V4.4.5 manifest mismatch")

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
        raise RuntimeError(f"V4.4.5 integrity failure: {integrity}")

    dedup = {}
    for row in raw:
        dedup.setdefault((row.get("symbol"), row.get("signal_time")), row)
    rows = sorted(
        dedup.values(),
        key=lambda r: (str(r.get("signal_time")), str(r.get("symbol"))),
    )
    _add_cross_section_and_phase(rows)

    # M1: setup universe is exactly the existing baseline cohort.
    m1a = [r for r in rows if _m1a(r)]
    m1b = [r for r in rows if _m1b(r)]
    m1a_u = _unique(m1a)
    m1b_u = _unique(m1b)

    m1_full = {
        "M1_A_E0": _entry_metrics(m1a, "v440"),
        "M1_A_E1": _entry_metrics(m1a, "v445_m1a_e1"),
        "M1_A_E2": _entry_metrics(m1a, "v445_m1a_e2"),
        "M1_B_E0": _entry_metrics(m1b, "v441_m1"),
        "M1_B_E1": _entry_metrics(m1b, "v445_m1b_e1"),
        "M1_B_E2": _entry_metrics(m1b, "v445_m1b_e2"),
    }
    m1_unique = {
        "M1_A_E0": _entry_metrics(m1a_u, "v440"),
        "M1_A_E1": _entry_metrics(m1a_u, "v445_m1a_e1"),
        "M1_A_E2": _entry_metrics(m1a_u, "v445_m1a_e2"),
        "M1_B_E0": _entry_metrics(m1b_u, "v441_m1"),
        "M1_B_E1": _entry_metrics(m1b_u, "v445_m1b_e1"),
        "M1_B_E2": _entry_metrics(m1b_u, "v445_m1b_e2"),
    }

    # M2: exact breakdown event de-duplication, then 96h independent episodes.
    events = _exact_break_events(rows)
    events_u = _unique_break_events(events)
    v444 = [r for r in rows if _terminal(r, "v444_m2")]
    v444_u = _unique(v444)

    m2_full = {
        "M2_E0_V444": _entry_metrics(v444, "v444_m2"),
        "M2_A_ACCEPT3": _entry_metrics(events, "v445_m2_a"),
        "M2_B_NEAR": _entry_metrics(events, "v445_m2_b"),
        "M2_C_RETEST": _entry_metrics(events, "v445_m2_c"),
    }
    m2_unique = {
        "M2_E0_V444": _entry_metrics(v444_u, "v444_m2"),
        "M2_A_ACCEPT3": _entry_metrics(events_u, "v445_m2_a"),
        "M2_B_NEAR": _entry_metrics(events_u, "v445_m2_b"),
        "M2_C_RETEST": _entry_metrics(events_u, "v445_m2_c"),
    }

    gate_source = {
        **{k: v for k, v in m1_unique.items()},
        **{k: v for k, v in m2_unique.items()},
    }
    gates = {k: _gate(v) for k, v in gate_source.items()}

    analysis = {
        "counts": {
            "raw": len(rows),
            "m1_a_opportunities": len(m1a),
            "m1_b_opportunities": len(m1b),
            "m2_exact_break_events": len(events),
            "m2_unique_96h_events": len(events_u),
        },
        "m1_full_60d": m1_full,
        "m1_unique_96h": m1_unique,
        "m2_event_stats_exact": _event_stats(events),
        "m2_event_stats_unique": _event_stats(events_u),
        "m2_full_60d": m2_full,
        "m2_unique_96h": m2_unique,
        "gates": gates,
        "research_status": "RESEARCH_ONLY",
        "future_24h_labels_used_for_entry": False,
        "fixed_parameter_run": True,
        "parameter_grid_searched": False,
    }

    return {
        "engine": "Crypto Short V4.4.5 Execution Lab",
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
    _write_json(os.path.join(OUTPUT_DIR, "v445_backtest.json"), report)
    _write_json(os.path.join(OUTPUT_DIR, "v445_analysis.json"), report["analysis"])
    _write_json(os.path.join(OUTPUT_DIR, "v445_manifest.json"), report["manifest"])
    fields = CSV_FIELDS + [
        "v428_trend_phase",
        "v428_structure_score",
        "v428_exhaustion_score",
        "v428_recovery_score",
    ]
    _write_csv(
        os.path.join(OUTPUT_DIR, "v445_scored_candidates.csv"),
        report["trades"],
        fields=fields,
    )
    with open(os.path.join(OUTPUT_DIR, "v445_summary.md"), "w", encoding="utf-8") as f:
        f.write(_summary(report))

    print(json.dumps({
        "integrity": report["manifest_integrity"],
        "errors": len(report["errors"]),
        "analysis": report["analysis"],
    }, ensure_ascii=False, indent=2))
    return 0 if not report["errors"] else 2


if __name__ == "__main__":
    sys.exit(main())
