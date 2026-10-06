import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from glob import glob

import pandas as pd

from .config import OUTPUT_DIR
from .v423_main import _write_csv, _write_json


def _load(root):
    reports = []
    for path in sorted(glob(
        os.path.join(root, "**", "v423_backtest.json"),
        recursive=True,
    )):
        with open(path, "r", encoding="utf-8") as handle:
            reports.append(json.load(handle))
    return reports


def _avg(rows, key):
    vals = [float(r[key]) for r in rows if r.get(key) is not None]
    return round(sum(vals) / len(vals), 4) if vals else None


def _median(rows, key):
    vals = [float(r[key]) for r in rows if r.get(key) is not None]
    return round(statistics.median(vals), 4) if vals else None


def _rate(rows, key):
    vals = [bool(r.get(key)) for r in rows if r.get(key) is not None]
    return round(sum(vals) / len(vals) * 100.0, 2) if vals else None


def _enum_rate(rows, key, value):
    vals = [str(r.get(key)) for r in rows if r.get(key) is not None]
    if not vals:
        return None
    return round(
        sum(1 for x in vals if x == value) / len(vals) * 100.0,
        2,
    )


def _diagnostics(rows):
    return {
        "count": len(rows),
        "avg_score": _avg(rows, "v423_score"),
        "median_score": _median(rows, "v423_score"),
        "avg_continuation_quality": _avg(
            rows, "continuation_quality_score"
        ),
        "avg_squeeze_risk": _avg(rows, "squeeze_risk"),
        "avg_anti_bottom": _avg(rows, "anti_bottom_total"),
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
                rows, "dir_first_0_5atr_move", "SHORT_0.5ATR_FIRST"
            ),
            "adverse_0_5atr_first_pct": _enum_rate(
                rows, "dir_first_0_5atr_move", "ADVERSE_0.5ATR_FIRST"
            ),
            "avg_4h_mfe_atr": _avg(rows, "dir_4h_mfe_atr"),
            "avg_4h_mae_atr": _avg(rows, "dir_4h_mae_atr"),
        },
        "strong_followthrough_pct": _enum_rate(
            rows, "dir_label", "STRONG_SHORT_FOLLOWTHROUGH"
        ),
        "bottom_or_wrong_timing_pct": _enum_rate(
            rows, "dir_label", "BOTTOM_OR_WRONG_TIMING"
        ),
    }


def _score_band(value):
    value = float(value or 0.0)
    if value >= 60.0:
        return "60_PLUS"
    if value >= 50.0:
        return "50_59"
    if value >= 40.0:
        return "40_49"
    return "BELOW_40"


def _quality_band(value):
    value = float(value or 0.0)
    if value >= 75.0:
        return "75_PLUS"
    if value >= 60.0:
        return "60_74"
    if value >= 45.0:
        return "45_59"
    return "BELOW_45"


def _risk_band(value):
    value = float(value or 0.0)
    if value >= 7.0:
        return "HIGH_7_PLUS"
    if value >= 4.0:
        return "MEDIUM_4_6"
    return "LOW_0_3"


def _temporal_stability(rows):
    ordered = sorted(
        rows,
        key=lambda r: (
            pd.Timestamp(r["signal_time"]),
            str(r.get("symbol")),
        ),
    )
    if not ordered:
        return []

    times = sorted({
        pd.Timestamp(r["signal_time"])
        for r in ordered
    })
    if len(times) < 8:
        return []

    cut1 = times[int((len(times) - 1) * 0.25)]
    cut2 = times[int((len(times) - 1) * 0.50)]
    cut3 = times[int((len(times) - 1) * 0.75)]
    bounds = [times[0], cut1, cut2, cut3, times[-1]]

    out = []
    for i in range(4):
        start = bounds[i]
        end = bounds[i + 1]
        block = [
            r for r in ordered
            if start <= pd.Timestamp(r["signal_time"]) <= end
        ]
        short_now = [
            r for r in block
            if r.get("v423_action") == "SHORT_NOW"
        ]
        out.append({
            "block": i + 1,
            "start": str(start),
            "end": str(end),
            "all": _diagnostics(block),
            "short_now": _diagnostics(short_now),
        })
    return out


def _summary_md(report):
    a = report["analysis"]
    o = a["overall"]

    lines = [
        "# Crypto Short V4.2.3 — Continuation-First Filter",
        "",
        f"- Manifest: {report.get('manifest_id')}",
        f"- Period: {report.get('period_start')} → {report.get('period_end')}",
        f"- Frozen symbols: {report.get('selected_symbol_count')}",
        f"- Manifest integrity: {'PASS' if report['manifest_integrity']['ok'] else 'FAIL'}",
        f"- Errors: {len(report.get('errors') or [])}",
        "",
        "## Design",
        "- SHORT_NOW is continuation-only.",
        "- Reversal setups remain WAIT_REVERSAL / research-only.",
        "- A continuation needs real breakdown departure, current retest rejection, no reclaim/acceptance, acceptable anti-bottom risk and no squeeze/recovery warning.",
        "- Score ranks candidates; structural gates decide SHORT_NOW.",
        "- Slippage is advisory only.",
        "",
        "## Overall",
        f"- Emitted: {o['count']}",
        f"- 1h below scan: {o['short_rate']['1h_pct']}%",
        f"- 4h below scan: {o['short_rate']['4h_pct']}%",
        f"- 12h below scan: {o['short_rate']['12h_pct']}%",
        f"- Short 0.5ATR first: {o['path_quality']['short_0_5atr_first_pct']}%",
        f"- Adverse 0.5ATR first: {o['path_quality']['adverse_0_5atr_first_pct']}%",
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
        "## Continuation quality bands",
        "",
        "| Quality | N | 4h ↓ | 12h ↓ | Short first | Avg 4h ATR |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, stats in a["by_quality_band"].items():
        lines.append(
            f"| {name} | {stats['count']} | "
            f"{stats['short_rate']['4h_pct']} | "
            f"{stats['short_rate']['12h_pct']} | "
            f"{stats['path_quality']['short_0_5atr_first_pct']} | "
            f"{stats['close_move_atr']['avg_4h']} |"
        )

    lines += [
        "",
        "## Squeeze risk",
        "",
        "| Squeeze risk | N | 4h ↓ | Short first | Adverse first | Avg 4h ATR |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, stats in a["by_squeeze_band"].items():
        lines.append(
            f"| {name} | {stats['count']} | "
            f"{stats['short_rate']['4h_pct']} | "
            f"{stats['path_quality']['short_0_5atr_first_pct']} | "
            f"{stats['path_quality']['adverse_0_5atr_first_pct']} | "
            f"{stats['close_move_atr']['avg_4h']} |"
        )

    lines += [
        "",
        "## Temporal stability of fixed SHORT_NOW rule",
        "",
        "| Block | SHORT_NOW N | 1h ↓ | 4h ↓ | 12h ↓ | Short first | Avg 4h ATR |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for block in a["temporal_stability"]:
        s = block["short_now"]
        lines.append(
            f"| {block['block']} | {s['count']} | "
            f"{s['short_rate']['1h_pct']} | "
            f"{s['short_rate']['4h_pct']} | "
            f"{s['short_rate']['12h_pct']} | "
            f"{s['path_quality']['short_0_5atr_first_pct']} | "
            f"{s['close_move_atr']['avg_4h']} |"
        )

    lines += [
        "",
        "## Reject / wait reasons",
        f"- {a['action_reason_counts']}",
        "",
        "## Promotion rule",
        "- Do not promote V4.2.3 to the live shortlist merely because aggregate results are positive.",
        "- SHORT_NOW must outperform WAIT_PULLBACK on immediate path quality and remain directionally consistent across time blocks.",
        "",
    ]
    return "\n".join(lines)


def merge_reports(reports):
    if not reports:
        raise RuntimeError("No V4.2.3 shard reports found")

    expected = max(int(r.get("shard_count") or 1) for r in reports)
    found = {int(r.get("shard_index")) for r in reports}
    if found != set(range(expected)):
        raise RuntimeError(
            f"Incomplete V4.2.3 shards: expected {expected}, "
            f"found {sorted(found)}"
        )

    manifest_ids = {str(r.get("manifest_id")) for r in reports}
    periods = {
        (str(r.get("period_start")), str(r.get("period_end")))
        for r in reports
    }
    if len(manifest_ids) != 1 or len(periods) != 1:
        raise RuntimeError("V4.2.3 shard manifest/period mismatch")

    first = reports[0]
    manifest = first.get("manifest") or {}
    frozen = set(manifest.get("symbols") or [])

    merged_symbols = []
    rows = []
    errors = []
    for report in reports:
        merged_symbols.extend(report.get("selected_symbols") or [])
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
            f"V4.2.3 manifest integrity failed: {integrity}"
        )

    dedup = {}
    for row in rows:
        key = (row.get("symbol"), row.get("signal_time"))
        dedup.setdefault(key, row)
    rows = sorted(
        dedup.values(),
        key=lambda r: (
            str(r.get("signal_time")),
            str(r.get("symbol")),
        ),
    )

    by_action = defaultdict(list)
    by_thesis = defaultdict(list)
    by_score = defaultdict(list)
    by_quality = defaultdict(list)
    by_squeeze = defaultdict(list)
    action_reasons = Counter()

    for row in rows:
        by_action[str(row.get("v423_action") or "UNKNOWN")].append(row)
        by_thesis[str(row.get("v423_thesis") or "UNKNOWN")].append(row)
        by_score[_score_band(row.get("v423_score"))].append(row)
        by_quality[
            _quality_band(row.get("continuation_quality_score"))
        ].append(row)
        by_squeeze[
            _risk_band(row.get("squeeze_risk"))
        ].append(row)
        action_reasons[str(
            row.get("v423_action_reason") or "UNKNOWN"
        )] += 1

    analysis = {
        "overall": _diagnostics(rows),
        "by_action": {
            k: _diagnostics(v) for k, v in sorted(by_action.items())
        },
        "by_thesis": {
            k: _diagnostics(v) for k, v in sorted(by_thesis.items())
        },
        "by_score_band": {
            k: _diagnostics(v) for k, v in sorted(by_score.items())
        },
        "by_quality_band": {
            k: _diagnostics(v) for k, v in sorted(by_quality.items())
        },
        "by_squeeze_band": {
            k: _diagnostics(v) for k, v in sorted(by_squeeze.items())
        },
        "action_reason_counts": dict(sorted(action_reasons.items())),
        "temporal_stability": _temporal_stability(rows),
    }

    return {
        "engine": "Crypto Short V4.2.3 Continuation-First Filter",
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
    root = sys.argv[1] if len(sys.argv) > 1 else "shard_outputs"
    report = merge_reports(_load(root))
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    _write_json(
        os.path.join(OUTPUT_DIR, "v423_backtest.json"),
        report,
    )
    _write_json(
        os.path.join(OUTPUT_DIR, "v423_analysis.json"),
        report["analysis"],
    )
    _write_json(
        os.path.join(OUTPUT_DIR, "v423_manifest.json"),
        report["manifest"],
    )
    _write_csv(
        os.path.join(OUTPUT_DIR, "v423_candidates.csv"),
        report.get("trades") or [],
    )
    with open(
        os.path.join(OUTPUT_DIR, "v423_summary.md"),
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
