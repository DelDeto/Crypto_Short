import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from glob import glob

from .config import OUTPUT_DIR
from .v3_calibration import metrics
from .v41_main import _write_csv, _write_json


def _load(root):
    paths = sorted(glob(os.path.join(root, "**", "v41_backtest.json"), recursive=True))
    reports = []
    for path in paths:
        with open(path, "r", encoding="utf-8") as handle:
            reports.append(json.load(handle))
    return reports


def _baseline_view(rows):
    out = []
    for row in rows:
        if row.get("baseline_realized_r") is None:
            continue
        out.append({
            **row,
            "realized_r": row.get("baseline_realized_r"),
            "outcome": row.get("baseline_outcome"),
            "cost_r": row.get("baseline_cost_r"),
            "mae_r": row.get("baseline_mae_r"),
            "mfe_r": row.get("baseline_mfe_r"),
        })
    return out


def _rate(rows, key):
    vals = [bool(r.get(key)) for r in rows if r.get(key) is not None]
    return round(sum(vals) / len(vals) * 100.0, 2) if vals else None


def _avg(rows, key):
    vals = [float(r[key]) for r in rows if r.get(key) is not None]
    return round(sum(vals) / len(vals), 4) if vals else None


def _median(rows, key):
    vals = [float(r[key]) for r in rows if r.get(key) is not None]
    return round(statistics.median(vals), 4) if vals else None


def _diagnostics(rows):
    filled = [r for r in rows if r.get("optimized_entry_filled") and r.get("realized_r") is not None]
    baseline_all = _baseline_view(rows)
    baseline_filled = _baseline_view([r for r in rows if r.get("optimized_entry_filled")])

    opt_metrics = metrics(filled)
    base_all_metrics = metrics(baseline_all)
    base_filled_metrics = metrics(baseline_filled)

    losses = [r for r in filled if r.get("outcome") == "LOSS"]
    base_losses = [r for r in rows if r.get("baseline_outcome") == "LOSS"]

    post_counts = Counter(str(r.get("post_sl_class") or "UNKNOWN") for r in losses)
    reject_counts = Counter(
        str(r.get("entry_reject_reason") or "UNKNOWN")
        for r in rows
        if not r.get("optimized_entry_filled")
    )
    zone_counts = Counter(
        str(r.get("zone_source") or "NO_VALID_ZONE")
        for r in rows
    )
    base_post_counts = Counter(
        str(r.get("baseline_post_sl_class") or "UNKNOWN") for r in base_losses
    )

    opt_exp = opt_metrics.get("expectancy_r")
    base_exp = base_filled_metrics.get("expectancy_r")
    delta = (
        round(float(opt_exp) - float(base_exp), 4)
        if opt_exp is not None and base_exp is not None else None
    )

    first = Counter(str(r.get("ft_first_0_5r_move") or "UNKNOWN") for r in filled)
    base_first = Counter(
        str(r.get("baseline_ft_first_0_5r_move") or "UNKNOWN")
        for r in rows if r.get("optimized_entry_filled")
    )

    return {
        "setups": len(rows),
        "zones_found": sum(1 for r in rows if r.get("zone_source")),
        "filled": len(filled),
        "fill_rate_pct": round(len(filled) / len(rows) * 100.0, 2) if rows else None,
        "entry_funnel": {
            "zone_touched": sum(1 for r in rows if r.get("audit_zone_touched")),
            "bos_confirmed": sum(1 for r in rows if r.get("audit_bos_confirmed")),
            "retest_seen": sum(1 for r in rows if r.get("audit_retest_seen")),
            "confirmation_seen": sum(1 for r in rows if r.get("audit_confirmation_seen")),
            "execution_passed": len(filled),
        },
        "entry_reject_reasons": dict(sorted(reject_counts.items())),
        "zone_source_counts": dict(sorted(zone_counts.items())),
        "avg_zone_location_quality": _avg(filled, "zone_location_quality"),
        "avg_zone_prior_touch_count": _avg(filled, "zone_prior_touch_count"),
        "optimized": opt_metrics,
        "baseline_all_setups": base_all_metrics,
        "baseline_same_filled_setups": base_filled_metrics,
        "expectancy_improvement_r_vs_same_setups": delta,
        "avg_entry_improvement_atr": _avg(filled, "entry_improvement_atr"),
        "median_entry_improvement_atr": _median(filled, "entry_improvement_atr"),
        "avg_wait_bars_15m": _avg(filled, "wait_bars_15m"),
        "followthrough": {
            "close_below_entry_1h_pct": _rate(filled, "ft_1h_short"),
            "close_below_entry_4h_pct": _rate(filled, "ft_4h_short"),
            "close_below_entry_12h_pct": _rate(filled, "ft_12h_short"),
            "close_below_entry_24h_pct": _rate(filled, "ft_24h_short"),
            "first_0_5r_move": dict(sorted(first.items())),
            "baseline_first_0_5r_move_same_setups": dict(sorted(base_first.items())),
            "avg_1h_close_r": _avg(filled, "ft_1h_close_r"),
            "avg_4h_close_r": _avg(filled, "ft_4h_close_r"),
        },
        "post_sl": {
            "losses": len(losses),
            "classes": dict(sorted(post_counts.items())),
            "reclaim_entry_pct": _rate(losses, "post_sl_reached_entry"),
            "then_plus_1r_pct": _rate(losses, "post_sl_reached_plus_1r"),
            "then_tp2r_pct": _rate(losses, "post_sl_reached_tp2r"),
            "avg_post_sl_mfe_r": _avg(losses, "post_sl_mfe_r"),
        },
        "baseline_post_sl": {
            "losses": len(base_losses),
            "classes": dict(sorted(base_post_counts.items())),
            "reclaim_entry_pct": _rate(base_losses, "baseline_post_sl_reached_entry"),
            "then_plus_1r_pct": _rate(base_losses, "baseline_post_sl_reached_plus_1r"),
            "then_tp2r_pct": _rate(base_losses, "baseline_post_sl_reached_tp2r"),
        },
    }


def _summary_md(report):
    overall = report["analysis"]["overall"]
    opt = overall["optimized"]
    base = overall["baseline_same_filled_setups"]
    post = overall["post_sl"]
    ft = overall["followthrough"]

    lines = [
        "# Crypto Short V4.1 — Entry Quality + Post-SL Audit",
        "",
        f"- Manifest: {report.get('manifest_id')}",
        f"- Period: {report.get('period_start')} → {report.get('period_end')}",
        f"- Frozen symbols: {report.get('selected_symbol_count')}",
        f"- Manifest integrity: {'PASS' if report['manifest_integrity']['ok'] else 'FAIL'}",
        f"- Errors: {len(report.get('errors') or [])}",
        "",
        "## Entry funnel",
        f"- Hard-gated setups: {overall['setups']}",
        f"- Valid zones: {overall['zones_found']}",
        f"- Confirmed retest entries: {overall['filled']} ({overall['fill_rate_pct']}%)",
        f"- Avg entry improvement vs signal: {overall['avg_entry_improvement_atr']} ATR",
        f"- Avg wait: {overall['avg_wait_bars_15m']} x 15m bars",
        f"- Avg zone quality: {overall.get('avg_zone_location_quality')}",
        f"- Funnel: {overall.get('entry_funnel')}",
        f"- Reject reasons: {overall.get('entry_reject_reasons')}",
        "",
        "## A/B on the same filled setups",
        f"- Signal-entry expectancy: {base.get('expectancy_r')}R | PF {base.get('profit_factor')}",
        f"- Optimized-entry expectancy: {opt.get('expectancy_r')}R | PF {opt.get('profit_factor')}",
        f"- Delta expectancy: {overall.get('expectancy_improvement_r_vs_same_setups')}R/trade",
        f"- Optimized profitable rate: {opt.get('net_profitable_rate_pct')}%",
        "",
        "## Immediate Short follow-through",
        f"- Close below entry after 1h: {ft.get('close_below_entry_1h_pct')}%",
        f"- Close below entry after 4h: {ft.get('close_below_entry_4h_pct')}%",
        f"- Close below entry after 12h: {ft.get('close_below_entry_12h_pct')}%",
        f"- Avg 1h close move: {ft.get('avg_1h_close_r')}R",
        f"- Avg 4h close move: {ft.get('avg_4h_close_r')}R",
        "",
        "## Post-SL audit",
        f"- Optimized losses observed: {post.get('losses')}",
        f"- SL then reclaim entry: {post.get('reclaim_entry_pct')}%",
        f"- SL then later +1R Short: {post.get('then_plus_1r_pct')}%",
        f"- SL then later original +2R TP: {post.get('then_tp2r_pct')}%",
        "",
        "## By engine",
        "",
        "| Engine | Setups | Filled | Fill % | Signal Exp R | Optimized Exp R | Delta R | PF | SL→TP2R % |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for engine, stats in report["analysis"]["by_engine"].items():
        bo = stats["baseline_same_filled_setups"]
        oo = stats["optimized"]
        ps = stats["post_sl"]
        lines.append(
            f"| {engine} | {stats['setups']} | {stats['filled']} | {stats['fill_rate_pct']} | "
            f"{bo.get('expectancy_r')} | {oo.get('expectancy_r')} | "
            f"{stats.get('expectancy_improvement_r_vs_same_setups')} | "
            f"{oo.get('profit_factor')} | {ps.get('then_tp2r_pct')} |"
        )

    lines += [
        "",
        "## Interpretation",
        "- V4.1 only enters after a fresh/valid location is touched, a 15m bearish BOS occurs, and the broken micro level is retested and rejected.",
        "- Unknown support is rejected instead of being treated as artificial 5R room.",
        "- A positive A/B delta means waiting for the zone/retest improved the exact same setup cohort.",
        "- FALSE_STOP_THEN_TP2R means price hit SL first, then later reached the original +2R Short target within the post-SL observation window.",
        "- The stop candle itself is excluded from post-SL reversal analysis because OHLC cannot reveal intrabar ordering after the stop.",
        "- V4.1 is research-only; it does not promote signals to live trading automatically.",
        "",
    ]
    return "\n".join(lines)


def merge_reports(reports):
    if not reports:
        raise RuntimeError("No V4.1 shard reports found")

    expected = max(int(r.get("shard_count") or 1) for r in reports)
    found = {int(r.get("shard_index")) for r in reports}
    if found != set(range(expected)):
        raise RuntimeError(f"Incomplete V4.1 shards: expected {expected}, found {sorted(found)}")

    manifest_ids = {str(r.get("manifest_id")) for r in reports}
    periods = {(str(r.get("period_start")), str(r.get("period_end"))) for r in reports}
    if len(manifest_ids) != 1 or len(periods) != 1:
        raise RuntimeError("V4.1 shard manifest/period mismatch")

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
        raise RuntimeError(f"V4.1 manifest integrity failed: {integrity}")

    deduped = {}
    for row in rows:
        key = (row.get("symbol"), row.get("signal_time"), row.get("v3_engine"))
        deduped.setdefault(key, row)
    rows = sorted(deduped.values(), key=lambda r: (
        str(r.get("signal_time")), str(r.get("symbol")), str(r.get("v3_engine"))
    ))

    by_engine_rows = defaultdict(list)
    by_zone_rows = defaultdict(list)
    for row in rows:
        by_engine_rows[str(row.get("v3_engine") or "UNKNOWN")].append(row)
        by_zone_rows[str(row.get("zone_source") or "NO_ZONE")].append(row)

    analysis = {
        "overall": _diagnostics(rows),
        "by_engine": {
            k: _diagnostics(v) for k, v in sorted(by_engine_rows.items())
        },
        "by_zone_source": {
            k: _diagnostics(v) for k, v in sorted(by_zone_rows.items())
        },
    }

    return {
        "engine": "Crypto Short V4.1 Entry Quality + Post-SL Audit",
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
    _write_json(os.path.join(OUTPUT_DIR, "v41_backtest.json"), report)
    _write_json(os.path.join(OUTPUT_DIR, "v41_analysis.json"), report["analysis"])
    _write_json(os.path.join(OUTPUT_DIR, "v41_manifest.json"), report["manifest"])
    _write_csv(os.path.join(OUTPUT_DIR, "v41_trades.csv"), report.get("trades") or [])
    with open(os.path.join(OUTPUT_DIR, "v41_summary.md"), "w", encoding="utf-8") as handle:
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
