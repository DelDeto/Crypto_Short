"""V4.4.4 merge: unchanged M1 benchmarks, legacy M2 vs rebuilt M2."""
import json
import os
import sys
from collections import Counter
from glob import glob

from .config import OUTPUT_DIR
from .v428_merge import _add_cross_section_and_phase
from .v441_main import _write_csv, _write_json
from .v443_merge import _gate, _m1a, _m1b, _metrics, _terminal, _unique
from .v444_main import CSV_FIELDS


def _load(root):
    reports = []
    for path in sorted(glob(os.path.join(root, "**", "v444_backtest.json"), recursive=True)):
        with open(path, "r", encoding="utf-8") as f:
            reports.append(json.load(f))
    return reports


def _phase_mix(rows, context_key):
    return dict(sorted(Counter(
        str(r.get("v428_trend_phase") or "UNKNOWN")
        for r in rows
        if int(r.get(context_key) or 0) == 1
    ).items()))


def _state_funnel(rows, prefix, context_key):
    eligible = [r for r in rows if int(r.get(context_key) or 0) == 1]
    return dict(sorted(Counter(
        str(r.get(f"{prefix}_state") or "NONE")
        for r in eligible
    ).items()))


def _pressure_distribution(rows):
    c = Counter(
        int(r.get("v444_m2_pressure_score") or 0)
        for r in rows
        if int(r.get("v444_m2_context_ok") or 0) == 1
    )
    return {str(k): int(v) for k, v in sorted(c.items())}


def _component_counts(rows):
    ctx = [r for r in rows if int(r.get("v444_m2_context_ok") or 0) == 1]
    return {
        "contexts": len(ctx),
        "lower_highs": sum(int(r.get("v444_m2_lower_highs") or 0) for r in ctx),
        "close_compression": sum(int(r.get("v444_m2_close_compression") or 0) for r in ctx),
        "near_support": sum(int(r.get("v444_m2_near_support") or 0) for r in ctx),
        "bearish_alignment": sum(int(r.get("v444_m2_bearish_alignment") or 0) for r in ctx),
        "relative_weakness": sum(int(r.get("v444_m2_relative_weakness") or 0) for r in ctx),
    }


def _summary(report):
    a = report["analysis"]
    full = a["full_60d"]
    unique = a["unique_96h"]
    lines = [
        "# Crypto Short V4.4.4 — Support-Pressure Breakdown 60d",
        "",
        f"- Period: {report['period_start']} -> {report['period_end']}",
        f"- Symbols: {report['selected_symbol_count']}",
        f"- Integrity: {'PASS' if report['manifest_integrity']['ok'] else 'FAIL'}",
        f"- Errors: {len(report['errors'])}",
        "- M1 execution is unchanged. M2 is rebuilt so trend phase is diagnostic, not a hard gate.",
        "",
        "## Main comparison",
        "",
        "| Cohort | Fills | Positive% | Stop% | TP1% | Gross R | Net R | PF | Avg Cost R | Avg Room R |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key, label in (
        ("M1_A", "M1 A strict"),
        ("M1_B", "M1 B baseline"),
        ("M2_OLD", "M2 legacy EDGE"),
        ("M2_NEW", "M2 support-pressure"),
    ):
        x = full[key]
        lines.append(
            f"| {label} | {x['fills']} | {x['positive_net_pct']} | {x['stop_pct']} | "
            f"{x['tp1_hit_pct']} | {x['gross_expectancy_r']} | {x['net_expectancy_r']} | "
            f"{x['profit_factor']} | {x['avg_cost_r']} | {x['avg_room_r']} |"
        )
    lines += [
        "",
        "## Unique 96h episodes — primary decision table",
    ]
    for key in ("M1_A", "M1_B", "M2_OLD", "M2_NEW"):
        lines.append(f"- {key}: {unique[key]}")
    lines += [
        "",
        "## Rebuilt M2 diagnostics",
        f"- Phase mix (diagnostic only): {a['m2_new_phase_mix']}",
        f"- Pressure-score distribution: {a['m2_new_pressure_distribution']}",
        f"- Pressure components: {a['m2_new_pressure_components']}",
        f"- State funnel: {a['m2_new_state_funnel']}",
        "",
        f"- Unique gates: {a['gates']}",
        "- RESEARCH_ONLY. A 60d result is an iteration screen, not deployment validation.",
    ]
    return "\n".join(lines)


def merge_reports(reports):
    if not reports:
        raise RuntimeError("No V4.4.4 shard reports found")
    expected = max(int(r.get("shard_count") or 1) for r in reports)
    found = {int(r.get("shard_index")) for r in reports}
    if found != set(range(expected)):
        raise RuntimeError(f"Incomplete V4.4.4 shards: {sorted(found)}")

    ids = {str(r.get("manifest_id")) for r in reports}
    if len(ids) != 1:
        raise RuntimeError("V4.4.4 manifest mismatch")

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
        raise RuntimeError(f"V4.4.4 integrity failure: {integrity}")

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
    m2old = [r for r in rows if _terminal(r, "v441_m2")]
    m2new = [r for r in rows if _terminal(r, "v444_m2")]

    cohorts = {
        "M1_A": (m1a, "v440"),
        "M1_B": (m1b, "v441_m1"),
        "M2_OLD": (m2old, "v441_m2"),
        "M2_NEW": (m2new, "v444_m2"),
    }
    full = {k: _metrics(v[0], v[1]) for k, v in cohorts.items()}
    unique = {k: _metrics(_unique(v[0]), v[1]) for k, v in cohorts.items()}
    gates = {k: _gate(unique[k]) for k in unique}

    analysis = {
        "counts": {
            "raw": len(rows),
            "m1_a_fills": len(m1a),
            "m1_b_fills": len(m1b),
            "m2_old_fills": len(m2old),
            "m2_new_contexts": sum(int(r.get("v444_m2_context_ok") or 0) for r in rows),
            "m2_new_fills": len(m2new),
        },
        "full_60d": full,
        "unique_96h": unique,
        "m2_new_phase_mix": _phase_mix(rows, "v444_m2_context_ok"),
        "m2_new_pressure_distribution": _pressure_distribution(rows),
        "m2_new_pressure_components": _component_counts(rows),
        "m2_new_state_funnel": _state_funnel(rows, "v444_m2", "v444_m2_context_ok"),
        "gates": gates,
        "research_status": "RESEARCH_ONLY",
        "fixed_parameter_run": True,
        "parameter_grid_searched": False,
    }

    return {
        "engine": "Crypto Short V4.4.4 Support Pressure Breakdown Research",
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
    _write_json(os.path.join(OUTPUT_DIR, "v444_backtest.json"), report)
    _write_json(os.path.join(OUTPUT_DIR, "v444_analysis.json"), report["analysis"])
    _write_json(os.path.join(OUTPUT_DIR, "v444_manifest.json"), report["manifest"])
    fields = CSV_FIELDS + [
        "v428_trend_phase",
        "v428_structure_score",
        "v428_exhaustion_score",
        "v428_recovery_score",
    ]
    _write_csv(
        os.path.join(OUTPUT_DIR, "v444_scored_candidates.csv"),
        report["trades"],
        fields=fields,
    )
    with open(os.path.join(OUTPUT_DIR, "v444_summary.md"), "w", encoding="utf-8") as f:
        f.write(_summary(report))

    print(json.dumps({
        "integrity": report["manifest_integrity"],
        "errors": len(report["errors"]),
        "analysis": report["analysis"],
    }, ensure_ascii=False, indent=2))
    return 0 if not report["errors"] else 2


if __name__ == "__main__":
    sys.exit(main())
