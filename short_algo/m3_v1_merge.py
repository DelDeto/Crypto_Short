"""Merge and score M3 V1 research shards."""
import json
import os
import sys
from collections import Counter
from glob import glob

import numpy as np

from .config import OUTPUT_DIR


def _load(root):
    reports = []
    for path in sorted(glob(os.path.join(root, "**", "m3_v1_backtest.json"), recursive=True)):
        with open(path, "r", encoding="utf-8") as f:
            reports.append(json.load(f))
    return reports


def _num(x):
    try:
        y = float(x)
        return y if np.isfinite(y) else None
    except (TypeError, ValueError):
        return None


def _pct(n, d):
    return round(100.0 * n / d, 2) if d else None


def _pf(values):
    gains = sum(x for x in values if x > 0)
    losses = -sum(x for x in values if x < 0)
    if losses <= 0:
        return 999.0 if gains > 0 else None
    return round(gains / losses, 4)


def _mean(values):
    vals = [x for x in (_num(v) for v in values) if x is not None]
    return round(float(np.mean(vals)), 5) if vals else None


def _target_metrics(rows, tag):
    prefix = f"m3_t{tag}"
    fills = [r for r in rows if _num(r.get(f"{prefix}_net_r")) is not None]
    net = [float(r[f"{prefix}_net_r"]) for r in fills]
    hold = [float(r.get(f"{prefix}_hold_bars") or 0) / 4.0 for r in fills]
    return {
        "fills": len(fills),
        "positive": sum(x > 0 for x in net),
        "positive_pct": _pct(sum(x > 0 for x in net), len(net)),
        "target_hit_pct": _pct(
            sum(r.get(f"{prefix}_state") == "TARGET" for r in fills),
            len(fills),
        ),
        "stop_pct": _pct(
            sum(str(r.get(f"{prefix}_state") or "").startswith("SL_FIRST") for r in fills),
            len(fills),
        ),
        "time_exit_pct": _pct(
            sum(r.get(f"{prefix}_state") == "TIME_EXIT_24H" for r in fills),
            len(fills),
        ),
        "net_expectancy_r": _mean(net),
        "profit_factor": _pf(net),
        "total_net_r": round(sum(net), 5),
        "avg_hold_hours": _mean(hold),
        "avg_mfe_r": _mean([r.get(f"{prefix}_mfe_r") for r in fills]),
        "avg_mae_r": _mean([r.get(f"{prefix}_mae_r") for r in fills]),
        "states": dict(sorted(Counter(
            str(r.get(f"{prefix}_state") or "NONE") for r in fills
        ).items())),
    }


def _quantile(values, q):
    vals = [x for x in (_num(v) for v in values) if x is not None]
    return round(float(np.quantile(vals, q)), 5) if vals else None


def _path_hourly_summary(rows):
    entries = [r for r in rows if r.get("m3_state") == "ENTRY_BENCHMARK"]
    by_hour = {h: [] for h in range(1, 25)}
    for row in entries:
        for point in row.get("m3_path_24h") or []:
            hour = int(point.get("hour") or 0)
            if hour in by_hour:
                by_hour[hour].append(point)

    summary = {}
    for hour in range(1, 25):
        points = by_hour[hour]
        close_atr = [p.get("short_close_atr") for p in points]
        close_r = [p.get("short_close_r") for p in points]
        mfe_atr = [p.get("cum_mfe_atr") for p in points]
        mae_atr = [p.get("cum_mae_atr") for p in points]

        close_vals = [x for x in (_num(v) for v in close_atr) if x is not None]
        summary[str(hour)] = {
            "observations": len(points),
            "close_favorable_pct": _pct(sum(x > 0 for x in close_vals), len(close_vals)),
            "median_short_close_atr": _quantile(close_atr, 0.50),
            "p25_short_close_atr": _quantile(close_atr, 0.25),
            "p75_short_close_atr": _quantile(close_atr, 0.75),
            "median_short_close_r": _quantile(close_r, 0.50),
            "median_cum_mfe_atr": _quantile(mfe_atr, 0.50),
            "median_cum_mae_atr": _quantile(mae_atr, 0.50),
            "mfe_ge_0_5_atr_pct": _pct(
                sum((_num(v) or 0.0) >= 0.5 for v in mfe_atr), len(points)
            ),
            "mfe_ge_1_0_atr_pct": _pct(
                sum((_num(v) or 0.0) >= 1.0 for v in mfe_atr), len(points)
            ),
            "mfe_ge_1_5_atr_pct": _pct(
                sum((_num(v) or 0.0) >= 1.5 for v in mfe_atr), len(points)
            ),
            "mfe_ge_2_0_atr_pct": _pct(
                sum((_num(v) or 0.0) >= 2.0 for v in mfe_atr), len(points)
            ),
            "mae_ge_0_5_atr_pct": _pct(
                sum((_num(v) or 0.0) >= 0.5 for v in mae_atr), len(points)
            ),
            "mae_ge_1_0_atr_pct": _pct(
                sum((_num(v) or 0.0) >= 1.0 for v in mae_atr), len(points)
            ),
        }
    return summary


def _path_key_checkpoints(path_summary):
    return {
        str(h): path_summary.get(str(h))
        for h in (1, 2, 4, 6, 8, 12, 18, 24)
    }


def _slice_metrics(rows, days):
    entries = [r for r in rows if r.get("m3_state") == "ENTRY_BENCHMARK"]
    return {
        "candidates": len(rows),
        "candidates_per_day": round(len(rows) / max(float(days), 1.0), 3),
        "benchmark_entries": len(entries),
        "entries_per_day": round(len(entries) / max(float(days), 1.0), 3),
        "tier_counts": dict(sorted(Counter(
            str(r.get("m3_tier") or "NONE") for r in rows
        ).items())),
        "resistance_sources": dict(sorted(Counter(
            str(r.get("m3_resistance_source") or "NONE") for r in rows
        ).items())),
        "market_states": dict(sorted(Counter(
            str(r.get("m3_market_state") or "NONE") for r in rows
        ).items())),
        "target_1_0_atr": _target_metrics(entries, "1_0"),
        "target_1_5_atr": _target_metrics(entries, "1_5"),
        "target_2_0_atr": _target_metrics(entries, "2_0"),
    }


def _summary(report):
    a = report["analysis"]
    lines = [
        "# M3 V1.1 — 24h Path Study",
        "",
        f"- Window: {report['period_start']} -> {report['period_end']}",
        f"- Symbols: {report['selected_symbol_count']}",
        f"- Errors: {len(report['errors'])}",
        f"- Integrity: {'PASS' if report['manifest_integrity']['ok'] else 'FAIL'}",
        "",
        "## Goal",
        "- More opportunities than M2, maximum benchmark hold 24h.",
        "- User remains the live entry/exit decision maker; benchmark entry is only for research.",
        "",
        "## Overall",
        f"- Candidates: {a['overall']['candidates']} ({a['overall']['candidates_per_day']}/day)",
        f"- Benchmark entries: {a['overall']['benchmark_entries']} ({a['overall']['entries_per_day']}/day)",
        f"- Tier counts: {a['overall']['tier_counts']}",
        f"- Resistance sources: {a['overall']['resistance_sources']}",
        f"- Market states: {a['overall']['market_states']}",
        "",
        "## Target comparison",
        f"- 1.0 ATR: {a['overall']['target_1_0_atr']}",
        f"- 1.5 ATR: {a['overall']['target_1_5_atr']}",
        f"- 2.0 ATR: {a['overall']['target_2_0_atr']}",
        "",
        "## 24h raw path study (uncensored by SL/TP)",
        f"- Key checkpoints: {a['path_study']['key_checkpoints']}",
        f"- Tier A checkpoints: {a['path_study']['tier_A_key_checkpoints']}",
        f"- Tier B checkpoints: {a['path_study']['tier_B_key_checkpoints']}",
        "",
        "## Tier A",
        f"{a['tier_A']}",
        "",
        "## Tier B",
        f"{a['tier_B']}",
        "",
        "## Regime slices",
        f"- Risk-Off: {a['risk_off']}",
        f"- Neutral: {a['neutral']}",
        f"- Strong Risk-On: {a['risk_on_strong']}",
        "",
        "RESEARCH ONLY — do not promote thresholds from this same sample without a later validation run.",
    ]
    return "\n".join(lines)


def merge_reports(reports):
    if not reports:
        raise RuntimeError("No M3 V1 shard reports found")

    expected = max(int(r.get("shard_count") or 1) for r in reports)
    found = {int(r.get("shard_index")) for r in reports}
    if found != set(range(expected)):
        raise RuntimeError(f"Incomplete M3 V1 shards: {sorted(found)}")

    ids = {str(r.get("manifest_id")) for r in reports}
    if len(ids) != 1:
        raise RuntimeError("M3 V1 manifest mismatch")

    first = reports[0]
    frozen = set((first.get("manifest") or {}).get("symbols") or [])
    symbols, rows, errors = [], [], []
    for report in reports:
        symbols.extend(report.get("selected_symbols") or [])
        rows.extend(report.get("candidates") or [])
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
        raise RuntimeError(f"M3 V1 integrity failure: {integrity}")

    dedup = {}
    for row in rows:
        dedup.setdefault((row.get("symbol"), row.get("signal_time")), row)
    rows = sorted(
        dedup.values(),
        key=lambda r: (str(r.get("signal_time")), str(r.get("symbol"))),
    )

    days = int(first.get("days") or 60)
    tier_a = [r for r in rows if r.get("m3_tier") == "A"]
    tier_b = [r for r in rows if r.get("m3_tier") == "B"]
    risk_off = [r for r in rows if r.get("m3_market_state") == "RISK_OFF"]
    neutral = [r for r in rows if r.get("m3_market_state") == "NEUTRAL"]
    risk_on = [r for r in rows if r.get("m3_market_state") == "RISK_ON_STRONG"]

    overall_path = _path_hourly_summary(rows)
    tier_a_path = _path_hourly_summary(tier_a)
    tier_b_path = _path_hourly_summary(tier_b)

    analysis = {
        "overall": _slice_metrics(rows, days),
        "tier_A": _slice_metrics(tier_a, days),
        "tier_B": _slice_metrics(tier_b, days),
        "risk_off": _slice_metrics(risk_off, days),
        "neutral": _slice_metrics(neutral, days),
        "risk_on_strong": _slice_metrics(risk_on, days),
        "path_study": {
            "uncensored_after_sl_tp": True,
            "hourly_1_to_24": overall_path,
            "key_checkpoints": _path_key_checkpoints(overall_path),
            "tier_A_key_checkpoints": _path_key_checkpoints(tier_a_path),
            "tier_B_key_checkpoints": _path_key_checkpoints(tier_b_path),
        },
        "research_status": "RESEARCH_ONLY",
        "model": "M3_INTRADAY_BEARISH_PULLBACK_CONTINUATION",
        "max_hold_hours": 24,
    }

    return {
        "engine": "M3 V1.1 Intraday Bearish Pullback Continuation + 24h Path Study",
        "manifest_id": next(iter(ids)),
        "manifest": first.get("manifest"),
        "manifest_integrity": integrity,
        "period_start": first.get("period_start"),
        "period_end": first.get("period_end"),
        "future_end": first.get("future_end"),
        "days": days,
        "selected_symbol_count": len(unique_symbols),
        "errors": errors,
        "analysis": analysis,
        "candidates": rows,
    }


def main(root="shard_outputs"):
    reports = _load(root)
    merged = merge_reports(reports)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(os.path.join(OUTPUT_DIR, "m3_v1_analysis.json"), "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2, default=str)
    with open(os.path.join(OUTPUT_DIR, "m3_v1_summary.md"), "w", encoding="utf-8") as f:
        f.write(_summary(merged))
    with open(os.path.join(OUTPUT_DIR, "m3_v1_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(merged.get("manifest"), f, ensure_ascii=False, indent=2)

    print(json.dumps(merged["analysis"], ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "shard_outputs"))
