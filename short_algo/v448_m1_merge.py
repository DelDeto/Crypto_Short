"""V4.4.8 M1-only merge report."""
import json
import os
import sys
from glob import glob

from .config import OUTPUT_DIR
from .v428_merge import _add_cross_section_and_phase
from .v441_main import _write_csv, _write_json, CSV_FIELDS
from .v443_merge import _gate, _m1a, _m1b, _metrics, _unique


def _load(root):
    reports = []
    for path in sorted(glob(os.path.join(root, "**", "v448_m1_backtest.json"), recursive=True)):
        with open(path, "r", encoding="utf-8") as f:
            reports.append(json.load(f))
    return reports


def _summary(report):
    a = report["analysis"]
    lines = [
        "# Crypto Short V4.4.8 — M1 Liquidity Reversal",
        "",
        f"- Signal window: {report['period_start']} -> {report['period_end']}",
        f"- Symbols: {report['selected_symbol_count']}",
        f"- Integrity: {'PASS' if report['manifest_integrity']['ok'] else 'FAIL'}",
        f"- Errors: {len(report['errors'])}",
        "- This workflow runs M1 only. No M2 engine is executed.",
        "",
        "## Full 60d",
        f"- M1-A strict: {a['full_60d']['M1_A']}",
        f"- M1-B scored: {a['full_60d']['M1_B']}",
        "",
        "## Unique 96h — primary",
        f"- M1-A strict: {a['unique_96h']['M1_A']}",
        f"- M1-B scored: {a['unique_96h']['M1_B']}",
        "",
        f"- Gates: {a['gates']}",
        "- RESEARCH_ONLY.",
    ]
    return "\n".join(lines)


def merge_reports(reports):
    if not reports:
        raise RuntimeError("No V4.4.8 M1 shard reports found")

    expected = max(int(r.get("shard_count") or 1) for r in reports)
    found = {int(r.get("shard_index")) for r in reports}
    if found != set(range(expected)):
        raise RuntimeError(f"Incomplete V4.4.8 M1 shards: {sorted(found)}")

    ids = {str(r.get("manifest_id")) for r in reports}
    if len(ids) != 1:
        raise RuntimeError("V4.4.8 M1 manifest mismatch")

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
        raise RuntimeError(f"V4.4.8 M1 integrity failure: {integrity}")

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

    full = {
        "M1_A": _metrics(m1a, "v440"),
        "M1_B": _metrics(m1b, "v441_m1"),
    }
    unique = {
        "M1_A": _metrics(m1a_u, "v440"),
        "M1_B": _metrics(m1b_u, "v441_m1"),
    }
    analysis = {
        "counts": {
            "raw": len(rows),
            "m1_a_opportunities": len(m1a),
            "m1_b_opportunities": len(m1b),
        },
        "full_60d": full,
        "unique_96h": unique,
        "gates": {k: _gate(v) for k, v in unique.items()},
        "research_status": "RESEARCH_ONLY",
        "model": "M1_ONLY",
    }

    return {
        "engine": "Crypto Short V4.4.8 M1 Liquidity Reversal",
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
    _write_json(os.path.join(OUTPUT_DIR, "v448_m1_backtest.json"), report)
    _write_json(os.path.join(OUTPUT_DIR, "v448_m1_analysis.json"), report["analysis"])
    _write_json(os.path.join(OUTPUT_DIR, "v448_m1_manifest.json"), report["manifest"])
    fields = CSV_FIELDS + [
        "v428_trend_phase",
        "v428_structure_score",
        "v428_exhaustion_score",
        "v428_recovery_score",
    ]
    _write_csv(
        os.path.join(OUTPUT_DIR, "v448_m1_scored_candidates.csv"),
        report["trades"],
        fields=fields,
    )
    with open(os.path.join(OUTPUT_DIR, "v448_m1_summary.md"), "w", encoding="utf-8") as f:
        f.write(_summary(report))
    print(json.dumps({
        "integrity": report["manifest_integrity"],
        "errors": len(report["errors"]),
        "analysis": report["analysis"],
    }, ensure_ascii=False, indent=2))
    return 0 if not report["errors"] else 2


if __name__ == "__main__":
    sys.exit(main())
