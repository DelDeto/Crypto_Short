"""V4.4.10 M2 merge: no-stop path-distribution analysis."""
import json
import os
import sys
from collections import Counter
from glob import glob

import numpy as np
import pandas as pd

from .config import OUTPUT_DIR
from .v441_main import _write_csv, _write_json
from .v4410_m2_config import (
    V4410_COOLDOWN_HOURS,
    V4410_FAVORABLE_THRESHOLDS_ATR,
    V4410_PATH_HORIZONS_HOURS,
)
from .v4410_m2_main import CSV_FIELDS


def _load(root):
    reports = []
    for path in sorted(
        glob(os.path.join(root, "**", "v4410_m2_backtest.json"), recursive=True)
    ):
        with open(path, "r", encoding="utf-8") as handle:
            reports.append(json.load(handle))
    return reports


def _num(v):
    try:
        x = float(v)
        return x if np.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _pct(n, d):
    return round(100.0 * n / d, 2) if d else None


def _stats(values):
    vals = [x for x in (_num(v) for v in values) if x is not None]
    if not vals:
        return {"n": 0}
    arr = np.asarray(vals, dtype=float)
    return {
        "n": len(vals),
        "mean": round(float(np.mean(arr)), 5),
        "median": round(float(np.median(arr)), 5),
        "p25": round(float(np.percentile(arr, 25)), 5),
        "p75": round(float(np.percentile(arr, 75)), 5),
        "p90": round(float(np.percentile(arr, 90)), 5),
    }


def _exact_events(rows):
    dedup = {}
    for row in sorted(
        rows,
        key=lambda r: (str(r.get("signal_time")), str(r.get("symbol"))),
    ):
        bt = row.get("v4410_m2_break_time")
        if not bt:
            continue
        key = (
            str(row.get("symbol")),
            str(bt),
            str(row.get("v4410_m2_support_level")),
        )
        dedup.setdefault(key, row)
    return list(dedup.values())


def _unique_events(events):
    last = {}
    out = []
    for row in sorted(
        events,
        key=lambda r: (
            str(r.get("v4410_m2_break_time")),
            str(r.get("symbol")),
        ),
    ):
        symbol = str(row.get("symbol"))
        t = pd.Timestamp(row.get("v4410_m2_break_time"))
        previous = last.get(symbol)
        if (
            previous is not None
            and (t - previous)
            < pd.Timedelta(hours=int(V4410_COOLDOWN_HOURS))
        ):
            continue
        last[symbol] = t
        out.append(row)
    return out


def _entry_rows(rows):
    return [r for r in rows if r.get("v4410_m2_entry_time") is not None]


def _horizon_metrics(entries, hours):
    tag = f"{int(hours)}h"
    complete = [
        r for r in entries
        if int(r.get(f"v4410_m2_{tag}_complete") or 0) == 1
    ]
    return {
        "entries": len(entries),
        "complete": len(complete),
        "complete_pct": _pct(len(complete), len(entries)),
        "mae_atr": _stats([
            r.get(f"v4410_m2_{tag}_mae_atr") for r in complete
        ]),
        "mfe_atr": _stats([
            r.get(f"v4410_m2_{tag}_mfe_atr") for r in complete
        ]),
        "forward_close_atr": _stats([
            r.get(f"v4410_m2_{tag}_forward_close_atr") for r in complete
        ]),
        "time_to_mae_h": _stats([
            r.get(f"v4410_m2_{tag}_time_to_mae_h") for r in complete
        ]),
        "time_to_mfe_h": _stats([
            r.get(f"v4410_m2_{tag}_time_to_mfe_h") for r in complete
        ]),
    }


def _threshold_metrics(entries, threshold):
    tag = str(threshold).replace(".", "_")
    complete = [
        r for r in entries
        if int(r.get(f"v4410_m2_fav_{tag}atr_complete") or 0) == 1
    ]
    hits = [
        r for r in complete
        if int(r.get(f"v4410_m2_fav_{tag}atr_hit") or 0) == 1
    ]
    return {
        "complete": len(complete),
        "hits": len(hits),
        "hit_pct": _pct(len(hits), len(complete)),
        "time_to_hit_h": _stats([
            r.get(f"v4410_m2_fav_{tag}atr_time_to_hit_h") for r in hits
        ]),
        "mae_before_hit_atr": _stats([
            r.get(f"v4410_m2_fav_{tag}atr_mae_before_hit_atr")
            for r in hits
        ]),
        "mae_before_hit_pct": _stats([
            r.get(f"v4410_m2_fav_{tag}atr_mae_before_hit_pct")
            for r in hits
        ]),
    }


def _reclaim_metrics(entries):
    reclaimed = [
        r for r in entries
        if int(r.get("v4410_m2_reclaimed_after_entry") or 0) == 1
    ]
    return {
        "entries": len(entries),
        "reclaimed": len(reclaimed),
        "reclaimed_pct": _pct(len(reclaimed), len(entries)),
        "time_to_reclaim_h": _stats([
            r.get("v4410_m2_time_to_reclaim_h") for r in reclaimed
        ]),
        "max_close_above_zone_atr": _stats([
            r.get("v4410_m2_max_close_above_zone_atr") for r in entries
        ]),
    }


def _watch_bucket(row):
    h = _num(row.get("v4410_m2_watch_hours"))
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


def _entry_distance_bucket(row):
    x = _num(row.get("v4410_m2_entry_below_support_atr"))
    if x is None:
        return "UNKNOWN"
    if x <= 0.5:
        return "LE_0_5"
    if x <= 1.0:
        return "0_5_1_0"
    if x <= 1.5:
        return "1_0_1_5"
    return "GT_1_5"


def _cohort_summary(entries):
    if not entries:
        return {"entries": 0}
    return {
        "entries": len(entries),
        "watch_hours": _stats([
            r.get("v4410_m2_watch_hours") for r in entries
        ]),
        "entry_below_support_atr": _stats([
            r.get("v4410_m2_entry_below_support_atr") for r in entries
        ]),
        "horizon_72h": _horizon_metrics(entries, 72),
        "horizon_168h": _horizon_metrics(entries, 168),
        "fav_2atr": _threshold_metrics(entries, 2.0),
        "fav_3atr": _threshold_metrics(entries, 3.0),
        "reclaim": _reclaim_metrics(entries),
    }


def _group_summary(entries, key_fn):
    groups = {}
    for row in entries:
        groups.setdefault(key_fn(row), []).append(row)
    return {
        key: _cohort_summary(values)
        for key, values in sorted(groups.items())
    }


def _summary(report):
    a = report["analysis"]
    lines = [
        "# Crypto Short V4.4.10 — M2 Entry Path Study / No Stop",
        "",
        f"- Signal window: {report['period_start']} -> {report['period_end']}",
        f"- Future buffer through: {report['future_end']}",
        f"- Symbols: {report['selected_symbol_count']}",
        f"- Integrity: {'PASS' if report['manifest_integrity']['ok'] else 'FAIL'}",
        f"- Errors: {len(report['errors'])}",
        "- Entry logic is frozen from V4.4.9 Confirmed Support Flip.",
        "- NO stop-loss, NO take-profit, NO PF/win-rate calculation.",
        "- All post-entry metrics are diagnostic only.",
        "",
        "## Funnel — unique 96h",
        f"{a['funnel_unique']}",
        "",
        "## Forward path — unique 96h",
    ]
    for hours in V4410_PATH_HORIZONS_HOURS:
        lines.append(
            f"- {int(hours)}h: {a['horizons_unique'][str(int(hours))]}"
        )
    lines += ["", "## Favorable excursion thresholds — unique 96h"]
    for threshold in V4410_FAVORABLE_THRESHOLDS_ATR:
        lines.append(
            f"- {threshold:g} ATR: "
            f"{a['thresholds_unique'][str(threshold)]}"
        )
    lines += [
        "",
        "## Reclaim after entry",
        f"{a['reclaim_unique']}",
        "",
        "## Entry-route cohorts",
        f"{a['route_cohorts_unique']}",
        "",
        "## Watch-time cohorts",
        f"{a['watch_time_cohorts_unique']}",
        "",
        "## Entry-distance cohorts",
        f"{a['entry_distance_cohorts_unique']}",
        "",
        "- RESEARCH_ONLY. This study is designed to learn the path first, then build SL/TP later.",
    ]
    return "\n".join(lines)


def merge_reports(reports):
    if not reports:
        raise RuntimeError("No V4.4.10 M2 shard reports found")

    expected = max(int(r.get("shard_count") or 1) for r in reports)
    found = {int(r.get("shard_index")) for r in reports}
    if found != set(range(expected)):
        raise RuntimeError(
            f"Incomplete V4.4.10 M2 shards: {sorted(found)}"
        )

    ids = {str(r.get("manifest_id")) for r in reports}
    if len(ids) != 1:
        raise RuntimeError("V4.4.10 M2 manifest mismatch")

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
            f"V4.4.10 M2 integrity failure: {integrity}"
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
    entries = _entry_rows(events)
    entries_u = _entry_rows(events_u)

    def funnel(events_):
        ready = [r for r in events_ if r.get("v4410_m2_ready_time")]
        entry = _entry_rows(events_)
        return {
            "break_events": len(events_),
            "confirmed_support_flip": len(ready),
            "entries": len(entry),
            "watch_states": dict(sorted(Counter(
                str(r.get("v4410_m2_watch_state") or "NONE")
                for r in events_
            ).items())),
            "entry_selection_states": dict(sorted(Counter(
                str(r.get("v4410_m2_entry_selection_state") or "NONE")
                for r in ready
            ).items())),
        }

    routes = {}
    for row in entries_u:
        routes.setdefault(
            str(row.get("v4410_m2_ready_reason") or "NONE"), []
        ).append(row)

    analysis = {
        "counts": {
            "raw_rows": len(rows),
            "exact_break_events": len(events),
            "unique_96h_break_events": len(events_u),
            "exact_entries": len(entries),
            "unique_96h_entries": len(entries_u),
        },
        "funnel_full": funnel(events),
        "funnel_unique": funnel(events_u),
        "horizons_unique": {
            str(int(h)): _horizon_metrics(entries_u, h)
            for h in V4410_PATH_HORIZONS_HOURS
        },
        "thresholds_unique": {
            str(t): _threshold_metrics(entries_u, t)
            for t in V4410_FAVORABLE_THRESHOLDS_ATR
        },
        "reclaim_unique": _reclaim_metrics(entries_u),
        "route_cohorts_unique": {
            key: _cohort_summary(values)
            for key, values in sorted(routes.items())
        },
        "watch_time_cohorts_unique": _group_summary(
            entries_u, _watch_bucket
        ),
        "entry_distance_cohorts_unique": _group_summary(
            entries_u, _entry_distance_bucket
        ),
        "research_status": "RESEARCH_ONLY",
        "model": "M2_ENTRY_PATH_STUDY_NO_STOP",
        "stop_loss_used": False,
        "take_profit_used": False,
        "profit_factor_computed": False,
        "future_path_used_for_entry": False,
    }

    return {
        "engine": "Crypto Short V4.4.10 M2 Entry Path Study",
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

    _write_json(
        os.path.join(OUTPUT_DIR, "v4410_m2_backtest.json"),
        report,
    )
    _write_json(
        os.path.join(OUTPUT_DIR, "v4410_m2_analysis.json"),
        report["analysis"],
    )
    _write_json(
        os.path.join(OUTPUT_DIR, "v4410_m2_manifest.json"),
        report["manifest"],
    )
    _write_csv(
        os.path.join(OUTPUT_DIR, "v4410_m2_path_candidates.csv"),
        report["trades"],
        fields=CSV_FIELDS,
    )
    with open(
        os.path.join(OUTPUT_DIR, "v4410_m2_summary.md"),
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
