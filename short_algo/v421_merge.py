import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from glob import glob

from .config import OUTPUT_DIR
from .v421_main import _write_csv, _write_json


def _load(root):
    paths = sorted(
        glob(
            os.path.join(root, "**", "v421_backtest.json"),
            recursive=True,
        )
    )
    reports = []
    for path in paths:
        with open(path, "r", encoding="utf-8") as handle:
            reports.append(json.load(handle))
    return reports


def _avg(rows, key):
    vals = [
        float(r[key])
        for r in rows
        if r.get(key) is not None
    ]
    return round(sum(vals) / len(vals), 4) if vals else None


def _median(rows, key):
    vals = [
        float(r[key])
        for r in rows
        if r.get(key) is not None
    ]
    return (
        round(statistics.median(vals), 4)
        if vals else None
    )


def _rate(rows, key):
    vals = [
        bool(r.get(key))
        for r in rows
        if r.get(key) is not None
    ]
    return (
        round(sum(vals) / len(vals) * 100.0, 2)
        if vals else None
    )


def _enum_rate(rows, key, value):
    vals = [
        str(r.get(key))
        for r in rows
        if r.get(key) is not None
    ]
    if not vals:
        return None
    return round(
        sum(1 for item in vals if item == value)
        / len(vals) * 100.0,
        2,
    )


def _diagnostics(rows):
    labels = Counter(
        str(r.get("dir_label") or "UNKNOWN")
        for r in rows
    )
    first = Counter(
        str(r.get("dir_first_0_5atr_move") or "UNKNOWN")
        for r in rows
    )
    statuses = Counter(
        str(r.get("v421_status") or "UNKNOWN")
        for r in rows
    )
    zones = Counter(
        str(r.get("zone_source") or "NO_ZONE")
        for r in rows
    )

    return {
        "count": len(rows),
        "avg_score": _avg(rows, "v421_score"),
        "median_score": _median(rows, "v421_score"),
        "avg_directional_score": _avg(
            rows, "directional_score"
        ),
        "avg_location_score": _avg(rows, "location_score"),
        "avg_trigger_score": _avg(rows, "trigger_score"),
        "avg_bottom_risk": _avg(rows, "bottom_risk"),
        "avg_chase_risk": _avg(rows, "chase_risk"),
        "status_counts": dict(sorted(statuses.items())),
        "zone_counts": dict(sorted(zones.items())),
        "short_rate": {
            "1h_pct": _rate(rows, "dir_1h_short"),
            "4h_pct": _rate(rows, "dir_4h_short"),
            "12h_pct": _rate(rows, "dir_12h_short"),
        },
        "close_move_atr": {
            "avg_1h": _avg(rows, "dir_1h_close_atr"),
            "avg_4h": _avg(rows, "dir_4h_close_atr"),
            "avg_12h": _avg(rows, "dir_12h_close_atr"),
        },
        "path_quality": {
            "avg_4h_mfe_atr": _avg(rows, "dir_4h_mfe_atr"),
            "avg_4h_mae_atr": _avg(rows, "dir_4h_mae_atr"),
            "avg_12h_mfe_atr": _avg(rows, "dir_12h_mfe_atr"),
            "avg_12h_mae_atr": _avg(rows, "dir_12h_mae_atr"),
            "short_0_5atr_first_pct": _enum_rate(
                rows,
                "dir_first_0_5atr_move",
                "SHORT_0.5ATR_FIRST",
            ),
            "adverse_0_5atr_first_pct": _enum_rate(
                rows,
                "dir_first_0_5atr_move",
                "ADVERSE_0.5ATR_FIRST",
            ),
            "first_move_counts": dict(sorted(first.items())),
        },
        "direction_labels": dict(sorted(labels.items())),
        "strong_followthrough_pct": _enum_rate(
            rows,
            "dir_label",
            "STRONG_SHORT_FOLLOWTHROUGH",
        ),
        "bottom_or_wrong_timing_pct": _enum_rate(
            rows,
            "dir_label",
            "BOTTOM_OR_WRONG_TIMING",
        ),
        "reference_execution": {
            "avg_fee_cost_r": _avg(rows, "fee_cost_r"),
            "avg_slippage_advisory_r": _avg(
                rows, "slippage_advisory_r"
            ),
            "note": (
                "Neither fee nor slippage is used to rank or "
                "reject directional candidates. Slippage is advisory."
            ),
        },
    }


def _score_band(score):
    score = float(score or 0.0)
    if score >= 78.0:
        return "78_PLUS"
    if score >= 68.0:
        return "68_77"
    if score >= 58.0:
        return "58_67"
    return "48_57"


def _bottom_band(value):
    value = float(value or 0.0)
    if value >= 15.0:
        return "HIGH_15_PLUS"
    if value >= 8.0:
        return "MEDIUM_8_14"
    return "LOW_0_7"


def _summary_md(report):
    a = report["analysis"]
    o = a["overall"]

    lines = [
        "# Crypto Short V4.2.1 — Discretionary Directional Filter",
        "",
        f"- Manifest: {report.get('manifest_id')}",
        f"- Period: {report.get('period_start')} → {report.get('period_end')}",
        f"- Frozen symbols: {report.get('selected_symbol_count')}",
        f"- Manifest integrity: {'PASS' if report['manifest_integrity']['ok'] else 'FAIL'}",
        f"- Errors: {len(report.get('errors') or [])}",
        "",
        "## Primary objective",
        "- Rank coins for discretionary Short decisions.",
        "- Main validation is future directional follow-through, not automatic trade PnL.",
        "- Slippage is advisory only and never removes a candidate.",
        "",
        "## Overall",
        f"- Candidates emitted: {o['count']}",
        f"- 1h close below scan price: {o['short_rate']['1h_pct']}%",
        f"- 4h close below scan price: {o['short_rate']['4h_pct']}%",
        f"- 12h close below scan price: {o['short_rate']['12h_pct']}%",
        f"- Short +0.5 ATR before adverse +0.5 ATR: {o['path_quality']['short_0_5atr_first_pct']}%",
        f"- Adverse +0.5 ATR first: {o['path_quality']['adverse_0_5atr_first_pct']}%",
        f"- Avg 4h close move: {o['close_move_atr']['avg_4h']} ATR in Short direction",
        f"- Strong Short follow-through: {o['strong_followthrough_pct']}%",
        f"- Bottom/wrong-timing label: {o['bottom_or_wrong_timing_pct']}%",
        "",
        "## By recommendation status",
        "",
        "| Status | N | 1h ↓ | 4h ↓ | 12h ↓ | Short 0.5ATR first | Avg 4h ATR | Bottom/wrong % |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for name, stats in a["by_status"].items():
        lines.append(
            f"| {name} | {stats['count']} | "
            f"{stats['short_rate']['1h_pct']} | "
            f"{stats['short_rate']['4h_pct']} | "
            f"{stats['short_rate']['12h_pct']} | "
            f"{stats['path_quality']['short_0_5atr_first_pct']} | "
            f"{stats['close_move_atr']['avg_4h']} | "
            f"{stats['bottom_or_wrong_timing_pct']} |"
        )

    lines += [
        "",
        "## By score band",
        "",
        "| Score | N | 4h ↓ | 12h ↓ | Short 0.5ATR first | Avg 4h ATR | Strong follow-through % |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, stats in a["by_score_band"].items():
        lines.append(
            f"| {name} | {stats['count']} | "
            f"{stats['short_rate']['4h_pct']} | "
            f"{stats['short_rate']['12h_pct']} | "
            f"{stats['path_quality']['short_0_5atr_first_pct']} | "
            f"{stats['close_move_atr']['avg_4h']} | "
            f"{stats['strong_followthrough_pct']} |"
        )

    lines += [
        "",
        "## Anti-bottom validation",
        "",
        "| Bottom risk | N | 4h ↓ | 12h ↓ | Short 0.5ATR first | Adverse first | Avg 4h ATR |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, stats in a["by_bottom_band"].items():
        lines.append(
            f"| {name} | {stats['count']} | "
            f"{stats['short_rate']['4h_pct']} | "
            f"{stats['short_rate']['12h_pct']} | "
            f"{stats['path_quality']['short_0_5atr_first_pct']} | "
            f"{stats['path_quality']['adverse_0_5atr_first_pct']} | "
            f"{stats['close_move_atr']['avg_4h']} |"
        )

    lines += [
        "",
        "## Interpretation rules",
        "- A useful filter should show higher Short follow-through as score rises.",
        "- SHORT_CANDIDATE should outperform WAIT_FOR_PULLBACK on 4h/12h direction.",
        "- AVOID_BOTTOM_SHORT should show worse immediate path quality; otherwise the anti-bottom penalty needs recalibration.",
        "- Reference Entry/SL/TP are guidance only; no exact fill is assumed in the primary directional metrics.",
        "",
    ]
    return "\n".join(lines)


def merge_reports(reports):
    if not reports:
        raise RuntimeError("No V4.2.1 shard reports found")

    expected = max(
        int(r.get("shard_count") or 1)
        for r in reports
    )
    found = {
        int(r.get("shard_index"))
        for r in reports
    }
    if found != set(range(expected)):
        raise RuntimeError(
            f"Incomplete V4.2.1 shards: "
            f"expected {expected}, found {sorted(found)}"
        )

    manifest_ids = {
        str(r.get("manifest_id"))
        for r in reports
    }
    periods = {
        (
            str(r.get("period_start")),
            str(r.get("period_end")),
        )
        for r in reports
    }
    if len(manifest_ids) != 1 or len(periods) != 1:
        raise RuntimeError("V4.2.1 shard manifest/period mismatch")

    first = reports[0]
    manifest = first.get("manifest") or {}
    frozen = set(manifest.get("symbols") or [])

    merged_symbols = []
    rows = []
    errors = []
    for report in reports:
        merged_symbols.extend(
            report.get("selected_symbols") or []
        )
        rows.extend(report.get("trades") or [])
        errors.extend(report.get("errors") or [])

    unique = set(merged_symbols)
    integrity = {
        "ok": (
            len(reports) == expected
            and len(merged_symbols) == len(unique)
            and unique == frozen
        ),
        "expected_shards": expected,
        "found_shards": len(reports),
        "frozen_symbol_count": len(frozen),
        "merged_symbol_count": len(unique),
        "duplicate_symbols": (
            len(merged_symbols) - len(unique)
        ),
        "missing_symbols": sorted(frozen - unique),
        "unexpected_symbols": sorted(unique - frozen),
    }
    if not integrity["ok"]:
        raise RuntimeError(
            f"V4.2.1 manifest integrity failed: {integrity}"
        )

    dedup = {}
    for row in rows:
        key = (
            row.get("symbol"),
            row.get("signal_time"),
        )
        dedup.setdefault(key, row)
    rows = sorted(
        dedup.values(),
        key=lambda r: (
            str(r.get("signal_time")),
            str(r.get("symbol")),
        ),
    )

    by_status = defaultdict(list)
    by_thesis = defaultdict(list)
    by_score = defaultdict(list)
    by_bottom = defaultdict(list)

    for row in rows:
        by_status[
            str(row.get("v421_status") or "UNKNOWN")
        ].append(row)
        by_thesis[
            str(row.get("v421_thesis") or "UNKNOWN")
        ].append(row)
        by_score[_score_band(row.get("v421_score"))].append(row)
        by_bottom[
            _bottom_band(row.get("bottom_risk"))
        ].append(row)

    analysis = {
        "overall": _diagnostics(rows),
        "by_status": {
            k: _diagnostics(v)
            for k, v in sorted(by_status.items())
        },
        "by_thesis": {
            k: _diagnostics(v)
            for k, v in sorted(by_thesis.items())
        },
        "by_score_band": {
            k: _diagnostics(v)
            for k, v in sorted(by_score.items())
        },
        "by_bottom_band": {
            k: _diagnostics(v)
            for k, v in sorted(by_bottom.items())
        },
    }

    return {
        "engine": (
            "Crypto Short V4.2.1 "
            "Discretionary Directional Filter"
        ),
        "manifest_id": next(iter(manifest_ids)),
        "manifest": manifest,
        "manifest_integrity": integrity,
        "period_start": first.get("period_start"),
        "period_end": first.get("period_end"),
        "days": first.get("days"),
        "selected_symbols": sorted(unique),
        "selected_symbol_count": len(unique),
        "analysis": analysis,
        "trades": rows,
        "errors": errors,
    }


def main():
    root = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "shard_outputs"
    )
    report = merge_reports(_load(root))
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    _write_json(
        os.path.join(OUTPUT_DIR, "v421_backtest.json"),
        report,
    )
    _write_json(
        os.path.join(OUTPUT_DIR, "v421_analysis.json"),
        report["analysis"],
    )
    _write_json(
        os.path.join(OUTPUT_DIR, "v421_manifest.json"),
        report["manifest"],
    )
    _write_csv(
        os.path.join(OUTPUT_DIR, "v421_candidates.csv"),
        report.get("trades") or [],
    )
    with open(
        os.path.join(OUTPUT_DIR, "v421_summary.md"),
        "w",
        encoding="utf-8",
    ) as handle:
        handle.write(_summary_md(report))

    print(json.dumps({
        "manifest_id": report.get("manifest_id"),
        "integrity": report.get("manifest_integrity"),
        "overall": report.get("analysis", {}).get("overall"),
        "errors": len(report.get("errors") or []),
    }, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
