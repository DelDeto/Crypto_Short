import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from glob import glob

import pandas as pd

from .config import OUTPUT_DIR
from .v422_main import _write_csv, _write_json


def _load(root):
    paths = sorted(
        glob(
            os.path.join(root, "**", "v422_backtest.json"),
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
    return round(statistics.median(vals), 4) if vals else None


def _rate(rows, key):
    vals = [
        bool(r.get(key))
        for r in rows
        if r.get(key) is not None
    ]
    if not vals:
        return None
    return round(sum(vals) / len(vals) * 100.0, 2)


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
    return {
        "count": len(rows),
        "avg_score": _avg(rows, "v422_score"),
        "median_score": _median(rows, "v422_score"),
        "avg_directional_score": _avg(rows, "directional_score"),
        "avg_location_score": _avg(rows, "location_score"),
        "avg_trigger_score": _avg(rows, "trigger_score"),
        "avg_bottom_risk": _avg(rows, "bottom_risk"),
        "avg_rebound_risk": _avg(rows, "rebound_risk"),
        "avg_anti_bottom_total": _avg(rows, "anti_bottom_total"),
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
            "avg_4h_mfe_atr": _avg(rows, "dir_4h_mfe_atr"),
            "avg_4h_mae_atr": _avg(rows, "dir_4h_mae_atr"),
            "first_move_counts": dict(sorted(first.items())),
        },
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
        "direction_labels": dict(sorted(labels.items())),
    }


def _score_band(score):
    score = float(score or 0.0)
    if score >= 64.0:
        return "64_PLUS"
    if score >= 56.0:
        return "56_63"
    if score >= 48.0:
        return "48_55"
    return "BELOW_48"


def _risk_band(value):
    value = float(value or 0.0)
    if value >= 12.0:
        return "HIGH_12_PLUS"
    if value >= 6.0:
        return "MEDIUM_6_11"
    return "LOW_0_5"


def _threshold_utility(rows):
    if len(rows) < 12:
        return None
    short_first = _enum_rate(
        rows, "dir_first_0_5atr_move", "SHORT_0.5ATR_FIRST"
    )
    adverse_first = _enum_rate(
        rows, "dir_first_0_5atr_move", "ADVERSE_0.5ATR_FIRST"
    )
    short4 = _rate(rows, "dir_4h_short")
    avg4 = _avg(rows, "dir_4h_close_atr")
    if (
        short_first is None
        or adverse_first is None
        or short4 is None
        or avg4 is None
    ):
        return None
    return (
        (short_first - adverse_first) / 100.0
        + 0.20 * float(avg4)
        + 0.15 * ((short4 - 50.0) / 50.0)
    )


def _walk_forward_threshold(rows):
    if len(rows) < 40:
        return {
            "folds": [],
            "oos_selected": _diagnostics([]),
            "note": "Not enough rows for walk-forward threshold audit.",
        }

    ordered = sorted(
        rows,
        key=lambda r: (
            pd.Timestamp(r["signal_time"]),
            str(r.get("symbol")),
        ),
    )
    unique_times = sorted({
        pd.Timestamp(r["signal_time"])
        for r in ordered
    })
    if len(unique_times) < 8:
        return {
            "folds": [],
            "oos_selected": _diagnostics([]),
            "note": "Not enough unique timestamps for walk-forward audit.",
        }

    # Four chronological blocks. Fold 0 is seed training only; folds 1-3 are
    # OOS tests. Threshold is selected only from timestamps before each test.
    cuts = [
        unique_times[
            min(
                len(unique_times) - 1,
                int(len(unique_times) * frac),
            )
        ]
        for frac in (0.25, 0.50, 0.75)
    ]
    bounds = [unique_times[0], *cuts, unique_times[-1]]

    thresholds = [40.0, 44.0, 48.0, 52.0, 56.0, 60.0, 64.0]
    folds = []
    oos_selected = []

    for fold in range(1, 4):
        test_start = bounds[fold]
        test_end = bounds[fold + 1]

        train = [
            r for r in ordered
            if pd.Timestamp(r["signal_time"]) < test_start
            and r.get("v422_action") != "AVOID_BOTTOM_SHORT"
        ]
        test = [
            r for r in ordered
            if test_start <= pd.Timestamp(r["signal_time"]) <= test_end
            and r.get("v422_action") != "AVOID_BOTTOM_SHORT"
        ]

        candidates = []
        for threshold in thresholds:
            selected = [
                r for r in train
                if float(r.get("v422_score") or 0.0) >= threshold
            ]
            utility = _threshold_utility(selected)
            if utility is not None:
                candidates.append((
                    float(utility),
                    threshold,
                    len(selected),
                ))

        if not candidates:
            folds.append({
                "fold": fold,
                "test_start": str(test_start),
                "test_end": str(test_end),
                "threshold": None,
                "train_selected": 0,
                "test_selected": 0,
                "test_metrics": _diagnostics([]),
            })
            continue

        # Tie-break toward the stricter threshold.
        candidates.sort(
            key=lambda x: (-x[0], -x[1])
        )
        _, threshold, train_n = candidates[0]

        selected_test = [
            r for r in test
            if float(r.get("v422_score") or 0.0) >= threshold
        ]
        oos_selected.extend(selected_test)

        folds.append({
            "fold": fold,
            "test_start": str(test_start),
            "test_end": str(test_end),
            "threshold": threshold,
            "train_selected": train_n,
            "test_selected": len(selected_test),
            "test_metrics": _diagnostics(selected_test),
        })

    return {
        "folds": folds,
        "oos_selected": _diagnostics(oos_selected),
        "note": (
            "Each test threshold is chosen only from earlier timestamps. "
            "This audits score usefulness; it does not alter historical rows."
        ),
    }


def _summary_md(report):
    a = report["analysis"]
    o = a["overall"]
    wf = a["walk_forward_threshold"]

    lines = [
        "# Crypto Short V4.2.2 — Pullback + Anti-Bottom Directional Filter",
        "",
        f"- Manifest: {report.get('manifest_id')}",
        f"- Period: {report.get('period_start')} → {report.get('period_end')}",
        f"- Frozen symbols: {report.get('selected_symbol_count')}",
        f"- Manifest integrity: {'PASS' if report['manifest_integrity']['ok'] else 'FAIL'}",
        f"- Errors: {len(report.get('errors') or [])}",
        "",
        "## Objective",
        "- Find coins with bearish follow-through without shorting an exhausted local bottom.",
        "- SHORT_BIAS and SHORT_NOW are separate decisions.",
        "- Continuation SHORT_NOW requires an actual pullback/retest rejection.",
        "- Slippage remains advisory only.",
        "",
        "## Overall emitted universe",
        f"- Candidates: {o['count']}",
        f"- 1h below scan price: {o['short_rate']['1h_pct']}%",
        f"- 4h below scan price: {o['short_rate']['4h_pct']}%",
        f"- 12h below scan price: {o['short_rate']['12h_pct']}%",
        f"- Short 0.5 ATR first: {o['path_quality']['short_0_5atr_first_pct']}%",
        f"- Adverse 0.5 ATR first: {o['path_quality']['adverse_0_5atr_first_pct']}%",
        f"- Avg 4h Short move: {o['close_move_atr']['avg_4h']} ATR",
        "",
        "## By action",
        "",
        "| Action | N | 1h ↓ | 4h ↓ | 12h ↓ | Short first | Adverse first | Avg 4h ATR | Bottom/wrong % |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for name, stats in a["by_action"].items():
        lines.append(
            f"| {name} | {stats['count']} | "
            f"{stats['short_rate']['1h_pct']} | "
            f"{stats['short_rate']['4h_pct']} | "
            f"{stats['short_rate']['12h_pct']} | "
            f"{stats['path_quality']['short_0_5atr_first_pct']} | "
            f"{stats['path_quality']['adverse_0_5atr_first_pct']} | "
            f"{stats['close_move_atr']['avg_4h']} | "
            f"{stats['bottom_or_wrong_timing_pct']} |"
        )

    lines += [
        "",
        "## By thesis",
        "",
        "| Thesis | N | 4h ↓ | 12h ↓ | Short first | Avg 4h ATR |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, stats in a["by_thesis"].items():
        lines.append(
            f"| {name} | {stats['count']} | "
            f"{stats['short_rate']['4h_pct']} | "
            f"{stats['short_rate']['12h_pct']} | "
            f"{stats['path_quality']['short_0_5atr_first_pct']} | "
            f"{stats['close_move_atr']['avg_4h']} |"
        )

    lines += [
        "",
        "## Score monotonicity",
        "",
        "| Score | N | 4h ↓ | 12h ↓ | Short first | Avg 4h ATR |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, stats in a["by_score_band"].items():
        lines.append(
            f"| {name} | {stats['count']} | "
            f"{stats['short_rate']['4h_pct']} | "
            f"{stats['short_rate']['12h_pct']} | "
            f"{stats['path_quality']['short_0_5atr_first_pct']} | "
            f"{stats['close_move_atr']['avg_4h']} |"
        )

    lines += [
        "",
        "## Anti-bottom calibration",
        "",
        "| Risk | N | 4h ↓ | 12h ↓ | Short first | Adverse first | Avg 4h ATR |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, stats in a["by_anti_bottom_band"].items():
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
        "## Walk-forward score threshold audit",
        "",
        "| Fold | OOS start | Threshold from past | Test N | 4h ↓ | Short first | Avg 4h ATR |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]

    for fold in wf.get("folds") or []:
        m = fold.get("test_metrics") or {}
        lines.append(
            f"| {fold.get('fold')} | {fold.get('test_start')} | "
            f"{fold.get('threshold')} | {fold.get('test_selected')} | "
            f"{(m.get('short_rate') or {}).get('4h_pct')} | "
            f"{(m.get('path_quality') or {}).get('short_0_5atr_first_pct')} | "
            f"{(m.get('close_move_atr') or {}).get('avg_4h')} |"
        )

    oos = wf.get("oos_selected") or {}
    lines += [
        "",
        f"- Combined OOS selected N: {oos.get('count')}",
        f"- Combined OOS 4h ↓: {(oos.get('short_rate') or {}).get('4h_pct')}%",
        f"- Combined OOS Short-first: {(oos.get('path_quality') or {}).get('short_0_5atr_first_pct')}%",
        f"- Combined OOS avg 4h move: {(oos.get('close_move_atr') or {}).get('avg_4h')} ATR",
        "",
        "## Interpretation",
        "- SHORT_NOW must beat WAIT_PULLBACK on immediate path quality before promotion to the live shortlist.",
        "- High anti-bottom risk should show worse path quality; otherwise the blocker needs recalibration.",
        "- Higher score bands should improve OOS results. If they do not, score must not be used as a ranker.",
        "- Walk-forward thresholds are selected from prior timestamps only.",
        "",
    ]
    return "\n".join(lines)


def merge_reports(reports):
    if not reports:
        raise RuntimeError("No V4.2.2 shard reports found")

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
            f"Incomplete V4.2.2 shards: "
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
        raise RuntimeError("V4.2.2 shard manifest/period mismatch")

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
        "duplicate_symbols": len(merged_symbols) - len(unique),
        "missing_symbols": sorted(frozen - unique),
        "unexpected_symbols": sorted(unique - frozen),
    }
    if not integrity["ok"]:
        raise RuntimeError(
            f"V4.2.2 manifest integrity failed: {integrity}"
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

    by_action = defaultdict(list)
    by_bias = defaultdict(list)
    by_thesis = defaultdict(list)
    by_score = defaultdict(list)
    by_risk = defaultdict(list)

    for row in rows:
        by_action[
            str(row.get("v422_action") or "UNKNOWN")
        ].append(row)
        by_bias[
            str(row.get("v422_bias") or "UNKNOWN")
        ].append(row)
        by_thesis[
            str(row.get("v422_thesis") or "UNKNOWN")
        ].append(row)
        by_score[
            _score_band(row.get("v422_score"))
        ].append(row)
        by_risk[
            _risk_band(row.get("anti_bottom_total"))
        ].append(row)

    analysis = {
        "overall": _diagnostics(rows),
        "by_action": {
            k: _diagnostics(v)
            for k, v in sorted(by_action.items())
        },
        "by_bias": {
            k: _diagnostics(v)
            for k, v in sorted(by_bias.items())
        },
        "by_thesis": {
            k: _diagnostics(v)
            for k, v in sorted(by_thesis.items())
        },
        "by_score_band": {
            k: _diagnostics(v)
            for k, v in sorted(by_score.items())
        },
        "by_anti_bottom_band": {
            k: _diagnostics(v)
            for k, v in sorted(by_risk.items())
        },
        "walk_forward_threshold": _walk_forward_threshold(rows),
    }

    return {
        "engine": (
            "Crypto Short V4.2.2 "
            "Pullback-Aware Directional Filter"
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
        os.path.join(OUTPUT_DIR, "v422_backtest.json"),
        report,
    )
    _write_json(
        os.path.join(OUTPUT_DIR, "v422_analysis.json"),
        report["analysis"],
    )
    _write_json(
        os.path.join(OUTPUT_DIR, "v422_manifest.json"),
        report["manifest"],
    )
    _write_csv(
        os.path.join(OUTPUT_DIR, "v422_candidates.csv"),
        report.get("trades") or [],
    )
    with open(
        os.path.join(OUTPUT_DIR, "v422_summary.md"),
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
