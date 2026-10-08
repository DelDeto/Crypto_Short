"""V4.4.9 M2-only merge report with support-flip diagnostics."""
import json
import os
import sys
from collections import Counter
from glob import glob

import numpy as np
import pandas as pd

from .config import OUTPUT_DIR
from .v441_main import _write_csv, _write_json
from .v443_merge import _gate
from .v447_config import V447_COOLDOWN_HOURS
from .v449_m2_main import CSV_FIELDS


def _load(root):
    reports = []
    for path in sorted(
        glob(os.path.join(root, "**", "v449_m2_backtest.json"), recursive=True)
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


def _pct(n, d):
    return round(100.0 * n / d, 2) if d else None


def _mean(values):
    vals = [x for x in (_num(v) for v in values) if x is not None]
    return round(float(np.mean(vals)), 5) if vals else None


def _pf(net):
    gains = sum(x for x in net if x > 0)
    losses = -sum(x for x in net if x < 0)
    if losses <= 0:
        return None if gains <= 0 else float("inf")
    return round(gains / losses, 4)


def _exact_events(rows):
    dedup = {}
    for row in sorted(
        rows,
        key=lambda r: (str(r.get("signal_time")), str(r.get("symbol"))),
    ):
        break_time = row.get("v449_m2_break_time")
        if not break_time:
            continue
        key = (
            str(row.get("symbol")),
            str(break_time),
            str(row.get("v449_m2_support_level")),
        )
        dedup.setdefault(key, row)
    return list(dedup.values())


def _unique_events(events):
    last = {}
    out = []
    for row in sorted(
        events,
        key=lambda r: (
            str(r.get("v449_m2_break_time")),
            str(r.get("symbol")),
        ),
    ):
        symbol = str(row.get("symbol"))
        t = pd.Timestamp(row.get("v449_m2_break_time"))
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


def _metrics(events):
    fills = [r for r in events if _num(r.get("v449_m2_net_r")) is not None]
    net = [float(r["v449_m2_net_r"]) for r in fills]
    gross = [
        float(r["v449_m2_gross_r"])
        for r in fills
        if _num(r.get("v449_m2_gross_r")) is not None
    ]
    return {
        "opportunities": len(events),
        "fills": len(fills),
        "fill_rate_pct": _pct(len(fills), len(events)),
        "positive_net": sum(x > 0 for x in net),
        "positive_net_pct": _pct(sum(x > 0 for x in net), len(net)),
        "stop_pct": _pct(
            sum(r.get("v449_m2_state") == "SL_FIRST" for r in fills),
            len(fills),
        ),
        "tp1_hit_pct": _pct(
            sum(int(r.get("v449_m2_tp1_hit") or 0) for r in fills),
            len(fills),
        ),
        "tp2_hit_pct": _pct(
            sum(int(r.get("v449_m2_tp2_hit") or 0) for r in fills),
            len(fills),
        ),
        "gross_expectancy_r": _mean(gross),
        "net_expectancy_r": _mean(net),
        "profit_factor": _pf(net),
        "total_net_r": round(sum(net), 5),
        "avg_cost_r": _mean([r.get("v449_m2_cost_r") for r in fills]),
        "avg_risk_atr": _mean([r.get("v449_m2_risk_atr") for r in fills]),
        "avg_entry_below_support_atr": _mean([
            r.get("v449_m2_entry_below_support_atr") for r in fills
        ]),
        "avg_watch_hours": _mean([
            r.get("v449_m2_watch_hours") for r in fills
        ]),
        "avg_failed_reclaims": _mean([
            r.get("v449_m2_failed_reclaim_attempts") for r in fills
        ]),
        "states": dict(sorted(Counter(
            str(r.get("v449_m2_state") or "NONE") for r in fills
        ).items())),
        "ready_reasons": dict(sorted(Counter(
            str(r.get("v449_m2_ready_reason") or "NONE") for r in fills
        ).items())),
        "major_demand_obstacle_pct": _pct(
            sum(int(r.get("v449_m2_major_demand_obstacle") or 0) for r in fills),
            len(fills),
        ),
    }


def _funnel(events):
    ready = [r for r in events if r.get("v449_m2_ready_time")]
    entry = [
        r for r in ready
        if r.get("v449_m2_entry_selection_state") == "ENTRY"
    ]
    fills = [r for r in entry if _num(r.get("v449_m2_net_r")) is not None]
    rejected = Counter(
        str(r.get("v449_m2_state") or "NONE")
        for r in entry
        if _num(r.get("v449_m2_net_r")) is None
    )
    return {
        "break_events": len(events),
        "confirmed_support_flip": len(ready),
        "entry_confirmed_1h": len(entry),
        "fills": len(fills),
        "rejected_after_entry_confirmation": dict(sorted(rejected.items())),
        "watch_states": dict(sorted(Counter(
            str(r.get("v449_m2_watch_state") or "NONE") for r in events
        ).items())),
        "ready_reason": dict(sorted(Counter(
            str(r.get("v449_m2_ready_reason") or "NONE") for r in ready
        ).items())),
    }


def _watch_bucket(row):
    h = _num(row.get("v449_m2_watch_hours"))
    if h is None:
        return "UNKNOWN"
    if h <= 12:
        return "LE_12H"
    if h <= 24:
        return "12_24H"
    if h <= 48:
        return "24_48H"
    if h <= 72:
        return "48_72H"
    return "GT_72H"


def _risk_bucket(row):
    x = _num(row.get("v449_m2_risk_atr"))
    if x is None:
        return "UNKNOWN"
    if x <= 0.75:
        return "LE_0_75"
    if x <= 1.00:
        return "0_75_1_00"
    if x <= 1.25:
        return "1_00_1_25"
    return "1_25_1_50"


def _bucket_metrics(events, key_fn):
    buckets = {}
    for row in events:
        key = key_fn(row)
        buckets.setdefault(key, []).append(row)
    return {
        key: _metrics(values)
        for key, values in sorted(buckets.items())
    }


def _summary(report):
    a = report["analysis"]
    lines = [
        "# Crypto Short V4.4.9 — M2 Confirmed Support Flip",
        "",
        f"- Signal window: {report['period_start']} -> {report['period_end']}",
        f"- Future buffer through: {report['future_end']}",
        f"- Symbols: {report['selected_symbol_count']}",
        f"- Integrity: {'PASS' if report['manifest_integrity']['ok'] else 'FAIL'}",
        f"- Errors: {len(report['errors'])}",
        "- First failed reclaim is evidence only; it cannot arm a short by itself.",
        "- SHORT_READY requires a confirmed support->resistance flip.",
        "- Major 4H demand never rejects an entry; it is runner/obstacle context only.",
        "- Tactical risk is capped at 1.5 ATR in this fixed-parameter research run.",
        "",
        "## Full 60d",
        f"- ALL: {a['full_60d']['ALL']}",
        f"- Repeated failed reclaim + LH: {a['full_60d']['REPEATED_FAILED_RECLAIM']}",
        f"- Persistent no reclaim + LHs: {a['full_60d']['PERSISTENT_NO_RECLAIM']}",
        "",
        "## Unique 96h — primary",
        f"- ALL: {a['unique_96h']['ALL']}",
        f"- Repeated failed reclaim + LH: {a['unique_96h']['REPEATED_FAILED_RECLAIM']}",
        f"- Persistent no reclaim + LHs: {a['unique_96h']['PERSISTENT_NO_RECLAIM']}",
        "",
        "## Funnel",
        f"- Full: {a['funnel_full']}",
        f"- Unique: {a['funnel_unique']}",
        "",
        "## Unique watch-time buckets",
        f"{a['watch_time_buckets_unique']}",
        "",
        "## Unique risk buckets",
        f"{a['risk_buckets_unique']}",
        "",
        f"- Gates: {a['gates']}",
        "- RESEARCH_ONLY. Parameters were chosen from prior V4.4.8 evidence; this 60d family is not untouched out-of-sample.",
    ]
    return "\n".join(lines)


def merge_reports(reports):
    if not reports:
        raise RuntimeError("No V4.4.9 M2 shard reports found")

    expected = max(int(r.get("shard_count") or 1) for r in reports)
    found = {int(r.get("shard_index")) for r in reports}
    if found != set(range(expected)):
        raise RuntimeError(
            f"Incomplete V4.4.9 M2 shards: {sorted(found)}"
        )

    ids = {str(r.get("manifest_id")) for r in reports}
    if len(ids) != 1:
        raise RuntimeError("V4.4.9 M2 manifest mismatch")

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
            f"V4.4.9 M2 integrity failure: {integrity}"
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

    events = _exact_events(rows)
    events_u = _unique_events(events)

    def route(rows_, reason):
        return [
            r for r in rows_
            if r.get("v449_m2_ready_reason") == reason
        ]

    full = {
        "ALL": _metrics(events),
        "REPEATED_FAILED_RECLAIM": _metrics(route(
            events, "REPEATED_FAILED_RECLAIM_LOWER_HIGH"
        )),
        "PERSISTENT_NO_RECLAIM": _metrics(route(
            events, "PERSISTENT_NO_RECLAIM_LOWER_HIGHS"
        )),
    }
    unique = {
        "ALL": _metrics(events_u),
        "REPEATED_FAILED_RECLAIM": _metrics(route(
            events_u, "REPEATED_FAILED_RECLAIM_LOWER_HIGH"
        )),
        "PERSISTENT_NO_RECLAIM": _metrics(route(
            events_u, "PERSISTENT_NO_RECLAIM_LOWER_HIGHS"
        )),
    }

    gates = {key: _gate(value) for key, value in unique.items()}
    analysis = {
        "counts": {
            "raw_rows": len(rows),
            "exact_break_events": len(events),
            "unique_96h_break_events": len(events_u),
        },
        "full_60d": full,
        "unique_96h": unique,
        "funnel_full": _funnel(events),
        "funnel_unique": _funnel(events_u),
        "watch_time_buckets_unique": _bucket_metrics(events_u, _watch_bucket),
        "risk_buckets_unique": _bucket_metrics(events_u, _risk_bucket),
        "gates": gates,
        "research_status": "RESEARCH_ONLY",
        "model": "M2_CONFIRMED_SUPPORT_FLIP",
        "first_failed_reclaim_can_arm": False,
        "major_4h_demand_hard_gate": False,
        "risk_cap_atr": 1.5,
    }

    return {
        "engine": "Crypto Short V4.4.9 M2 Confirmed Support Flip",
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
    _write_json(os.path.join(OUTPUT_DIR, "v449_m2_backtest.json"), report)
    _write_json(
        os.path.join(OUTPUT_DIR, "v449_m2_analysis.json"),
        report["analysis"],
    )
    _write_json(
        os.path.join(OUTPUT_DIR, "v449_m2_manifest.json"),
        report["manifest"],
    )
    _write_csv(
        os.path.join(OUTPUT_DIR, "v449_m2_scored_candidates.csv"),
        report["trades"],
        fields=CSV_FIELDS,
    )
    with open(
        os.path.join(OUTPUT_DIR, "v449_m2_summary.md"),
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
