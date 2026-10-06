import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from glob import glob

from .config import OUTPUT_DIR
from .v3_calibration import metrics
from .v42_main import _write_csv, _write_json


def _load(root):
    paths = sorted(glob(os.path.join(root, "**", "v42_backtest.json"), recursive=True))
    reports = []
    for path in paths:
        with open(path, "r", encoding="utf-8") as handle:
            reports.append(json.load(handle))
    return reports


def _project(rows, prefix):
    out = []
    for row in rows:
        realized = row.get(f"{prefix}realized_r")
        outcome = row.get(f"{prefix}outcome")
        if realized is None:
            continue
        out.append({
            **row,
            "realized_r": realized,
            "outcome": outcome,
            "cost_r": row.get(f"{prefix}cost_r"),
            "mae_r": row.get(f"{prefix}mae_r"),
            "mfe_r": row.get(f"{prefix}mfe_r"),
        })
    return out


def _avg(rows, key):
    vals = [float(r[key]) for r in rows if r.get(key) is not None]
    return round(sum(vals) / len(vals), 4) if vals else None


def _median(rows, key):
    vals = [float(r[key]) for r in rows if r.get(key) is not None]
    return round(statistics.median(vals), 4) if vals else None


def _rate(rows, key):
    vals = [bool(r.get(key)) for r in rows if r.get(key) is not None]
    return round(sum(vals) / len(vals) * 100.0, 2) if vals else None


def _diagnostics(rows):
    actual = [r for r in rows if r.get("optimized_entry_filled") and r.get("realized_r") is not None]
    shadow_rows = [r for r in rows if r.get("shadow_execution_candidate")]
    shadow = _project(shadow_rows, "shadow_")
    baseline_same_shadow = _project(shadow_rows, "baseline_")
    baseline_all = _project(rows, "baseline_")

    rejects = Counter(
        str(r.get("entry_reject_reason") or "UNKNOWN")
        for r in rows
        if not r.get("optimized_entry_filled")
    )
    zones = Counter(str(r.get("zone_source") or "NO_ZONE") for r in rows)
    subtypes = Counter(str(r.get("v42_subtype") or "UNKNOWN") for r in rows)

    actual_losses = [r for r in actual if r.get("outcome") == "LOSS"]
    shadow_losses = [
        r for r in shadow_rows
        if r.get("shadow_outcome") == "LOSS"
    ]

    actual_m = metrics(actual)
    shadow_m = metrics(shadow)
    base_shadow_m = metrics(baseline_same_shadow)
    base_all_m = metrics(baseline_all)

    shadow_delta = None
    if (
        shadow_m.get("expectancy_r") is not None
        and base_shadow_m.get("expectancy_r") is not None
    ):
        shadow_delta = round(
            float(shadow_m["expectancy_r"])
            - float(base_shadow_m["expectancy_r"]),
            4,
        )

    first_shadow = Counter(
        str(r.get("shadow_ft_first_0_5r_move") or "UNKNOWN")
        for r in shadow_rows
    )
    first_actual = Counter(
        str(r.get("ft_first_0_5r_move") or "UNKNOWN")
        for r in actual
    )

    return {
        "setups": len(rows),
        "entry_funnel": {
            "zone_available": sum(1 for r in rows if r.get("zone_source")),
            "zone_touched": sum(1 for r in rows if r.get("audit_zone_touched")),
            "meaningful_pivot_found": sum(1 for r in rows if r.get("audit_meaningful_pivot_found")),
            "quality_displacement_bos": sum(1 for r in rows if r.get("audit_displacement_bos")),
            "retest_seen": sum(1 for r in rows if r.get("audit_retest_seen")),
            "failed_retest_confirmed": sum(1 for r in rows if r.get("audit_failed_retest_confirmed")),
            "shadow_execution_candidates": len(shadow_rows),
            "execution_passed": len(actual),
        },
        "reject_reasons": dict(sorted(rejects.items())),
        "zone_source_counts": dict(sorted(zones.items())),
        "subtype_counts": dict(sorted(subtypes.items())),
        "baseline_all_setups": base_all_m,
        "baseline_same_shadow_setups": base_shadow_m,
        "shadow_structural_entry": shadow_m,
        "actual_execution_passed": actual_m,
        "shadow_expectancy_delta_vs_signal_same_setups": shadow_delta,
        "shadow_followthrough": {
            "close_below_entry_1h_pct": _rate(shadow_rows, "shadow_ft_1h_short"),
            "close_below_entry_4h_pct": _rate(shadow_rows, "shadow_ft_4h_short"),
            "close_below_entry_12h_pct": _rate(shadow_rows, "shadow_ft_12h_short"),
            "close_below_entry_24h_pct": _rate(shadow_rows, "shadow_ft_24h_short"),
            "avg_1h_close_r": _avg(shadow_rows, "shadow_ft_1h_close_r"),
            "avg_4h_close_r": _avg(shadow_rows, "shadow_ft_4h_close_r"),
            "first_0_5r_move": dict(sorted(first_shadow.items())),
        },
        "actual_followthrough": {
            "close_below_entry_1h_pct": _rate(actual, "ft_1h_short"),
            "close_below_entry_4h_pct": _rate(actual, "ft_4h_short"),
            "first_0_5r_move": dict(sorted(first_actual.items())),
        },
        "shadow_entry_quality": {
            "avg_stop_pct": _avg(shadow_rows, "shadow_stop_pct"),
            "avg_support_room_r": _avg(shadow_rows, "shadow_support_room_r"),
            "avg_projected_cost_r": _avg(shadow_rows, "shadow_projected_cost_r"),
            "avg_pivot_age_bars": _avg(shadow_rows, "shadow_pivot_age_bars"),
            "avg_pivot_prominence_atr15": _avg(shadow_rows, "shadow_pivot_prominence_atr15"),
        },
        "post_sl": {
            "actual_losses": len(actual_losses),
            "actual_then_tp2r_pct": _rate(actual_losses, "post_sl_reached_tp2r"),
            "shadow_losses": len(shadow_losses),
            "shadow_then_tp2r_pct": _rate(shadow_losses, "shadow_post_sl_reached_tp2r"),
            "shadow_reclaim_entry_pct": _rate(shadow_losses, "shadow_post_sl_reached_entry"),
        },
    }


def _summary_md(report):
    o = report["analysis"]["overall"]
    funnel = o["entry_funnel"]
    sm = o["shadow_structural_entry"]
    bm = o["baseline_same_shadow_setups"]
    am = o["actual_execution_passed"]
    ft = o["shadow_followthrough"]

    lines = [
        "# Crypto Short V4.2 — Structural Validation",
        "",
        f"- Manifest: {report.get('manifest_id')}",
        f"- Period: {report.get('period_start')} → {report.get('period_end')}",
        f"- Frozen symbols: {report.get('selected_symbol_count')}",
        f"- Manifest integrity: {'PASS' if report['manifest_integrity']['ok'] else 'FAIL'}",
        f"- Errors: {len(report.get('errors') or [])}",
        "",
        "## Funnel",
        f"- Routed setups: {o['setups']}",
        f"- HTF zone available: {funnel['zone_available']}",
        f"- Zone touched: {funnel['zone_touched']}",
        f"- Meaningful pivot found: {funnel['meaningful_pivot_found']}",
        f"- Quality displacement BOS: {funnel['quality_displacement_bos']}",
        f"- Retest seen: {funnel['retest_seen']}",
        f"- Failed retest confirmed: {funnel['failed_retest_confirmed']}",
        f"- Shadow structural candidates: {funnel['shadow_execution_candidates']}",
        f"- Execution passed: {funnel['execution_passed']}",
        f"- Reject reasons: {o['reject_reasons']}",
        "",
        "## Structural entry vs signal entry — same cohort",
        f"- Signal expectancy: {bm.get('expectancy_r')}R | PF {bm.get('profit_factor')}",
        f"- Structural shadow expectancy: {sm.get('expectancy_r')}R | PF {sm.get('profit_factor')}",
        f"- Delta: {o.get('shadow_expectancy_delta_vs_signal_same_setups')}R/trade",
        f"- Structural profitable rate: {sm.get('net_profitable_rate_pct')}%",
        "",
        "## Immediate follow-through — structural shadow",
        f"- Below entry after 1h: {ft.get('close_below_entry_1h_pct')}%",
        f"- Below entry after 4h: {ft.get('close_below_entry_4h_pct')}%",
        f"- Below entry after 12h: {ft.get('close_below_entry_12h_pct')}%",
        f"- Avg 1h move: {ft.get('avg_1h_close_r')}R",
        f"- Avg 4h move: {ft.get('avg_4h_close_r')}R",
        f"- First ±0.5R: {ft.get('first_0_5r_move')}",
        "",
        "## Execution-passed trades",
        f"- Resolved: {am.get('resolved')}",
        f"- Expectancy: {am.get('expectancy_r')}R",
        f"- PF: {am.get('profit_factor')}",
        "",
        "## By setup",
        "",
        "| Setup | N | Shadow N | Signal Exp R | Structural Exp R | Delta R | Structural PF |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]

    for name, stats in report["analysis"]["by_setup"].items():
        ss = stats["shadow_structural_entry"]
        bb = stats["baseline_same_shadow_setups"]
        lines.append(
            f"| {name} | {stats['setups']} | {stats['entry_funnel']['shadow_execution_candidates']} | "
            f"{bb.get('expectancy_r')} | {ss.get('expectancy_r')} | "
            f"{stats.get('shadow_expectancy_delta_vs_signal_same_setups')} | "
            f"{ss.get('profit_factor')} |"
        )

    lines += [
        "",
        "## Interpretation",
        "- V4.2 no longer treats exhaustion or relative weakness as standalone entry engines.",
        "- One symbol/timestamp maps to one primary structural thesis: reversal or continuation.",
        "- BOS requires a pre-touch confirmed pivot plus bearish displacement, low close location and volume expansion.",
        "- Shadow results isolate structural-entry quality before support/cost/stop gates.",
        "- Research only; no automatic live promotion.",
        "",
    ]
    return "\n".join(lines)


def merge_reports(reports):
    if not reports:
        raise RuntimeError("No V4.2 shard reports found")

    expected = max(int(r.get("shard_count") or 1) for r in reports)
    found = {int(r.get("shard_index")) for r in reports}
    if found != set(range(expected)):
        raise RuntimeError(f"Incomplete V4.2 shards: expected {expected}, found {sorted(found)}")

    manifest_ids = {str(r.get("manifest_id")) for r in reports}
    periods = {(str(r.get("period_start")), str(r.get("period_end"))) for r in reports}
    if len(manifest_ids) != 1 or len(periods) != 1:
        raise RuntimeError("V4.2 shard manifest/period mismatch")

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
        raise RuntimeError(f"V4.2 manifest integrity failed: {integrity}")

    dedup = {}
    for row in rows:
        key = (row.get("symbol"), row.get("signal_time"))
        dedup.setdefault(key, row)
    rows = sorted(
        dedup.values(),
        key=lambda r: (str(r.get("signal_time")), str(r.get("symbol"))),
    )

    by_setup = defaultdict(list)
    by_subtype = defaultdict(list)
    by_zone = defaultdict(list)
    for row in rows:
        by_setup[str(row.get("v42_setup") or "UNKNOWN")].append(row)
        by_subtype[str(row.get("v42_subtype") or "UNKNOWN")].append(row)
        by_zone[str(row.get("zone_source") or "NO_ZONE")].append(row)

    analysis = {
        "overall": _diagnostics(rows),
        "by_setup": {k: _diagnostics(v) for k, v in sorted(by_setup.items())},
        "by_subtype": {k: _diagnostics(v) for k, v in sorted(by_subtype.items())},
        "by_zone": {k: _diagnostics(v) for k, v in sorted(by_zone.items())},
    }

    return {
        "engine": "Crypto Short V4.2 Structural Validation",
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
    _write_json(os.path.join(OUTPUT_DIR, "v42_backtest.json"), report)
    _write_json(os.path.join(OUTPUT_DIR, "v42_analysis.json"), report["analysis"])
    _write_json(os.path.join(OUTPUT_DIR, "v42_manifest.json"), report["manifest"])
    _write_csv(os.path.join(OUTPUT_DIR, "v42_trades.csv"), report.get("trades") or [])
    with open(os.path.join(OUTPUT_DIR, "v42_summary.md"), "w", encoding="utf-8") as handle:
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
