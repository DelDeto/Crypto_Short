import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import timedelta
from glob import glob

import numpy as np
import pandas as pd

from .config import OUTPUT_DIR
from .v425_config import (
    V425_EMBARGO_HOURS,
    V425_INITIAL_TRAIN_FRACTION,
    V425_MIN_TRAIN_ROWS,
    V425_OOS_FOLDS,
    V425_OPPORTUNITY_WEIGHT_4H,
    V425_OPPORTUNITY_WEIGHT_FIRST,
    V425_PERSISTENCE_WEIGHT_12H,
    V425_PERSISTENCE_WEIGHT_24H,
    V425_PRIORITY_MIN_OPPORTUNITY,
    V425_PRIORITY_TOP_PCT,
    V425_READY_ZONE_DISTANCE_ATR,
    V425_SWING_MIN_PERSISTENCE,
    V425_WAIT_MIN_OPPORTUNITY,
    V425_WAIT_TOP_PCT,
)
from .v425_main import CSV_FIELDS, _write_csv, _write_json
from .v425_model import FEATURE_NAMES, fit_logistic, predict_logistic


SCORED_FIELDS = CSV_FIELDS + [
    "oos_fold", "train_rows",
    "p_4h_lower", "p_12h_lower", "p_24h_lower", "p_first_short",
    "opportunity_probability", "persistence_probability",
    "cross_section_rank", "cross_section_rank_pct",
    "top_10pct", "top_20pct", "top_30pct",
    "entry_zone_ready", "scanner_status",
]


def _load(root):
    reports = []
    for path in sorted(glob(
        os.path.join(root, "**", "v425_backtest.json"),
        recursive=True,
    )):
        with open(path, "r", encoding="utf-8") as handle:
            reports.append(json.load(handle))
    return reports


def _avg(rows, key):
    vals = []
    for row in rows:
        value = row.get(key)
        if value is None:
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if np.isfinite(value):
            vals.append(value)
    return round(sum(vals) / len(vals), 4) if vals else None


def _median(rows, key):
    vals = []
    for row in rows:
        value = row.get(key)
        if value is None:
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if np.isfinite(value):
            vals.append(value)
    return round(statistics.median(vals), 4) if vals else None


def _rate(rows, key):
    vals = [
        bool(r.get(key))
        for r in rows
        if r.get(key) is not None
    ]
    return round(sum(vals) / len(vals) * 100.0, 2) if vals else None


def _enum_rate(rows, key, value):
    vals = [
        str(r.get(key))
        for r in rows
        if r.get(key) is not None
    ]
    if not vals:
        return None
    return round(
        sum(1 for x in vals if x == value) / len(vals) * 100.0,
        2,
    )


def _diagnostics(rows):
    path_counts = Counter(
        str(r.get("path_class_24h") or "UNKNOWN")
        for r in rows
    )
    block_moves = {}
    for start in (0, 4, 8, 12, 16, 20):
        end = start + 4
        block_moves[f"{start}_{end}h"] = {
            "avg_return_atr": _avg(
                rows, f"block_{start}_{end}h_return_atr"
            ),
            "short_rate_pct": _rate(
                rows, f"block_{start}_{end}h_short"
            ),
            "avg_relative_pct": _avg(
                rows, f"block_{start}_{end}h_relative_pct"
            ),
        }

    return {
        "count": len(rows),
        "avg_opportunity_probability": _avg(
            rows, "opportunity_probability"
        ),
        "avg_persistence_probability": _avg(
            rows, "persistence_probability"
        ),
        "short_rate": {
            "1h_pct": _rate(rows, "dir_1h_short"),
            "4h_pct": _rate(rows, "dir_4h_short"),
            "12h_pct": _rate(rows, "dir_12h_short"),
            "24h_pct": _rate(rows, "dir_24h_short"),
        },
        "relative_underperform_rate": {
            "4h_pct": _rate(rows, "y_rel_4h_underperform"),
            "12h_pct": _rate(rows, "y_rel_12h_underperform"),
            "24h_pct": _rate(rows, "y_rel_24h_underperform"),
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
            "avg_max_downside_24h_atr": _avg(
                rows, "max_downside_24h_atr"
            ),
            "avg_max_adverse_24h_atr": _avg(
                rows, "max_adverse_24h_atr"
            ),
            "median_hours_to_max_downside": _median(
                rows, "hours_to_max_downside"
            ),
            "signal_reclaim_after_mfe_pct": _rate(
                rows, "reclaimed_signal_after_mfe"
            ),
        },
        "path_class_counts": dict(sorted(path_counts.items())),
        "persistent_short_pct": _enum_rate(
            rows, "path_class_24h", "PERSISTENT_SHORT"
        ),
        "short_then_reverse_pct": _enum_rate(
            rows, "path_class_24h", "SHORT_THEN_REVERSE"
        ),
        "delayed_short_pct": _enum_rate(
            rows, "path_class_24h", "DELAYED_SHORT"
        ),
        "wrong_way_early_pct": _enum_rate(
            rows, "path_class_24h", "WRONG_WAY_EARLY"
        ),
        "blocks": block_moves,
    }


def _brier(rows, prob_key, target_key):
    vals = []
    for row in rows:
        if row.get(prob_key) is None or row.get(target_key) is None:
            continue
        vals.append((
            float(row[prob_key]),
            1.0 if bool(row[target_key]) else 0.0,
        ))
    if not vals:
        return None
    return round(
        sum((p - y) ** 2 for p, y in vals) / len(vals),
        5,
    )


def _auc(rows, prob_key, target_key):
    pairs = []
    for row in rows:
        if row.get(prob_key) is None or row.get(target_key) is None:
            continue
        pairs.append((
            float(row[prob_key]),
            1 if bool(row[target_key]) else 0,
        ))
    pos = sum(y for _, y in pairs)
    neg = len(pairs) - pos
    if pos == 0 or neg == 0:
        return None

    pairs.sort(key=lambda x: x[0])
    rank_sum_pos = 0.0
    i = 0
    rank = 1
    while i < len(pairs):
        j = i + 1
        while j < len(pairs) and pairs[j][0] == pairs[i][0]:
            j += 1
        avg_rank = (rank + (rank + (j - i) - 1)) / 2.0
        positives_in_tie = sum(y for _, y in pairs[i:j])
        rank_sum_pos += avg_rank * positives_in_tie
        rank += j - i
        i = j

    auc = (
        rank_sum_pos - pos * (pos + 1) / 2.0
    ) / (pos * neg)
    return round(float(auc), 5)


def _cross_section_stats(rows):
    grouped = defaultdict(int)
    for row in rows:
        grouped[str(row.get("signal_time"))] += 1
    counts = list(grouped.values())
    if not counts:
        return {
            "timestamps": 0,
            "mean": None,
            "median": None,
            "p10": None,
            "p90": None,
            "min": None,
            "max": None,
        }
    return {
        "timestamps": len(counts),
        "mean": round(float(np.mean(counts)), 2),
        "median": round(float(np.median(counts)), 2),
        "p10": round(float(np.percentile(counts, 10)), 2),
        "p90": round(float(np.percentile(counts, 90)), 2),
        "min": int(min(counts)),
        "max": int(max(counts)),
    }


def _feature_importance(model_records):
    out = {}
    for head in ("p4", "p12", "p24", "pfirst"):
        arrays = []
        for fold in model_records:
            model = fold.get(head) or {}
            if model.get("type") != "logistic":
                continue
            arrays.append(np.asarray(model.get("coef") or [], dtype=float))
        if not arrays:
            out[head] = []
            continue
        mat = np.vstack(arrays)
        signed = np.mean(mat, axis=0)
        absolute = np.mean(np.abs(mat), axis=0)
        order = np.argsort(-absolute)[:15]
        out[head] = [
            {
                "feature": FEATURE_NAMES[int(i)],
                "mean_coef": round(float(signed[i]), 4),
                "mean_abs_coef": round(float(absolute[i]), 4),
            }
            for i in order
        ]
    return out


def _assign_cross_section(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[str(row["signal_time"])].append(row)

    for group in grouped.values():
        group.sort(
            key=lambda r: (
                -float(r.get("opportunity_probability") or 0.0),
                -float(r.get("persistence_probability") or 0.0),
                str(r.get("symbol")),
            )
        )
        n = len(group)
        for i, row in enumerate(group):
            rank_pct = i / float(max(n, 1))
            row["cross_section_rank"] = i + 1
            row["cross_section_rank_pct"] = round(rank_pct, 4)
            row["top_10pct"] = rank_pct < 0.10
            row["top_20pct"] = rank_pct < 0.20
            row["top_30pct"] = rank_pct < 0.30

            upper = row.get("preferred_zone_upper")
            current = float(row.get("current_price") or 0.0)
            a1 = max(float(row.get("atr_1h") or 0.0), 1e-12)
            zone_dist = row.get("zone_distance_atr")
            zone_ready = bool(
                upper is not None
                and zone_dist is not None
                and float(zone_dist) <= V425_READY_ZONE_DISTANCE_ATR
                and current <= float(upper) + 0.15 * a1
            )
            row["entry_zone_ready"] = zone_ready

            opportunity = float(
                row.get("opportunity_probability") or 0.0
            )
            persistence = float(
                row.get("persistence_probability") or 0.0
            )

            if bool(row.get("severe_bottom_rule")):
                status = "AVOID_SHORT"
            elif (
                rank_pct < V425_PRIORITY_TOP_PCT
                and opportunity >= V425_PRIORITY_MIN_OPPORTUNITY
            ):
                if not zone_ready:
                    status = "WAIT_PULLBACK"
                elif persistence >= V425_SWING_MIN_PERSISTENCE:
                    status = "PRIORITY_SHORT_SWING"
                else:
                    status = "PRIORITY_SHORT_SCALP"
            elif (
                rank_pct < V425_WAIT_TOP_PCT
                and opportunity >= V425_WAIT_MIN_OPPORTUNITY
            ):
                status = "WAIT_PULLBACK"
            else:
                status = "WATCH"
            row["scanner_status"] = status


def _walk_forward(rows):
    ordered = sorted(
        rows,
        key=lambda r: (
            pd.Timestamp(r["signal_time"]),
            str(r.get("symbol")),
        ),
    )
    times = sorted({
        pd.Timestamp(r["signal_time"])
        for r in ordered
    })
    if len(times) < 12:
        return [], [], []

    initial = max(
        2,
        int(len(times) * float(V425_INITIAL_TRAIN_FRACTION)),
    )
    initial = min(initial, len(times) - 1)
    remaining = times[initial:]
    if not remaining:
        return [], [], []

    blocks = [
        list(x)
        for x in np.array_split(
            np.asarray(remaining, dtype=object),
            max(1, int(V425_OOS_FOLDS)),
        )
        if len(x)
    ]

    scored = []
    fold_reports = []
    model_records = []

    for fold_index, block in enumerate(blocks, start=1):
        test_start = pd.Timestamp(block[0])
        test_end = pd.Timestamp(block[-1])
        train_cutoff = test_start - timedelta(
            hours=int(V425_EMBARGO_HOURS)
        )

        train = [
            r for r in ordered
            if pd.Timestamp(r["signal_time"]) < train_cutoff
        ]
        test = [
            dict(r)
            for r in ordered
            if test_start <= pd.Timestamp(r["signal_time"]) <= test_end
        ]

        if len(train) < int(V425_MIN_TRAIN_ROWS) or not test:
            fold_reports.append({
                "fold": fold_index,
                "test_start": str(test_start),
                "test_end": str(test_end),
                "train_rows": len(train),
                "test_rows": len(test),
                "skipped": True,
            })
            continue

        m4 = fit_logistic(train, "y_4h_lower")
        m12 = fit_logistic(train, "y_12h_lower")
        m24 = fit_logistic(train, "y_24h_lower")
        mf = fit_logistic(train, "y_first_short")

        p4 = predict_logistic(m4, test)
        p12 = predict_logistic(m12, test)
        p24 = predict_logistic(m24, test)
        pf = predict_logistic(mf, test)

        opp_den = (
            float(V425_OPPORTUNITY_WEIGHT_4H)
            + float(V425_OPPORTUNITY_WEIGHT_FIRST)
        )
        per_den = (
            float(V425_PERSISTENCE_WEIGHT_12H)
            + float(V425_PERSISTENCE_WEIGHT_24H)
        )

        for row, a, b, c, d in zip(test, p4, p12, p24, pf):
            opportunity = (
                float(V425_OPPORTUNITY_WEIGHT_4H) * a
                + float(V425_OPPORTUNITY_WEIGHT_FIRST) * d
            ) / max(opp_den, 1e-12)
            persistence = (
                float(V425_PERSISTENCE_WEIGHT_12H) * b
                + float(V425_PERSISTENCE_WEIGHT_24H) * c
            ) / max(per_den, 1e-12)

            row["oos_fold"] = fold_index
            row["train_rows"] = len(train)
            row["p_4h_lower"] = round(float(a), 6)
            row["p_12h_lower"] = round(float(b), 6)
            row["p_24h_lower"] = round(float(c), 6)
            row["p_first_short"] = round(float(d), 6)
            row["opportunity_probability"] = round(
                float(opportunity), 6
            )
            row["persistence_probability"] = round(
                float(persistence), 6
            )

        _assign_cross_section(test)
        scored.extend(test)

        top20 = [
            r for r in test
            if r.get("top_20pct")
            and not r.get("severe_bottom_rule")
        ]
        priority = [
            r for r in test
            if str(r.get("scanner_status", "")).startswith(
                "PRIORITY_SHORT"
            )
        ]

        fold_reports.append({
            "fold": fold_index,
            "test_start": str(test_start),
            "test_end": str(test_end),
            "train_rows": len(train),
            "test_rows": len(test),
            "skipped": False,
            "cross_section": _cross_section_stats(test),
            "all": _diagnostics(test),
            "top20_non_bottom": _diagnostics(top20),
            "priority": _diagnostics(priority),
            "auc": {
                "4h": _auc(test, "p_4h_lower", "y_4h_lower"),
                "12h": _auc(test, "p_12h_lower", "y_12h_lower"),
                "24h": _auc(test, "p_24h_lower", "y_24h_lower"),
                "first": _auc(test, "p_first_short", "y_first_short"),
            },
        })

        model_records.append({
            "fold": fold_index,
            "test_start": str(test_start),
            "test_end": str(test_end),
            "train_cutoff": str(train_cutoff),
            "p4": m4,
            "p12": m12,
            "p24": m24,
            "pfirst": mf,
        })

    scored.sort(
        key=lambda r: (
            str(r.get("signal_time")),
            str(r.get("symbol")),
        )
    )
    return scored, fold_reports, model_records


def _summary_md(report):
    a = report["analysis"]
    overall = a["overall_oos"]
    top10 = a["top10_non_bottom"]
    top20 = a["top20_non_bottom"]
    priority = a["priority_all"]

    lines = [
        "# Crypto Short V4.2.5 — Dense 24h Scanner",
        "",
        f"- Manifest: {report.get('manifest_id')}",
        f"- Period: {report.get('period_start')} → {report.get('period_end')}",
        f"- Frozen symbols: {report.get('selected_symbol_count')}",
        f"- Manifest integrity: {'PASS' if report['manifest_integrity']['ok'] else 'FAIL'}",
        f"- Errors: {len(report.get('errors') or [])}",
        "",
        "## Cross-sectional density",
        f"- Raw timestamps: {a['raw_cross_section']['timestamps']}",
        f"- Raw coins/timestamp mean: {a['raw_cross_section']['mean']}",
        f"- Raw coins/timestamp median: {a['raw_cross_section']['median']}",
        f"- Raw p10/p90: {a['raw_cross_section']['p10']} / {a['raw_cross_section']['p90']}",
        f"- Raw min/max: {a['raw_cross_section']['min']} / {a['raw_cross_section']['max']}",
        "",
        "## OOS cohorts",
        "",
        "| Cohort | N | 1h ↓ | 4h ↓ | 12h ↓ | 24h ↓ | Short first | Persistent | Short→Reverse | Avg max downside 24h |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for name, stats in (
        ("All OOS", overall),
        ("Top 20% non-bottom", top20),
        ("Top 10% non-bottom", top10),
        ("All priority", priority),
    ):
        lines.append(
            f"| {name} | {stats['count']} | "
            f"{stats['short_rate']['1h_pct']} | "
            f"{stats['short_rate']['4h_pct']} | "
            f"{stats['short_rate']['12h_pct']} | "
            f"{stats['short_rate']['24h_pct']} | "
            f"{stats['path_quality']['short_0_5atr_first_pct']} | "
            f"{stats['persistent_short_pct']} | "
            f"{stats['short_then_reverse_pct']} | "
            f"{stats['path_quality']['avg_max_downside_24h_atr']} |"
        )

    lines += [
        "",
        "## Priority type",
        "",
        "| Status | N | 4h ↓ | 12h ↓ | 24h ↓ | Short first | Persistent | Short→Reverse |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, stats in a["by_status"].items():
        lines.append(
            f"| {name} | {stats['count']} | "
            f"{stats['short_rate']['4h_pct']} | "
            f"{stats['short_rate']['12h_pct']} | "
            f"{stats['short_rate']['24h_pct']} | "
            f"{stats['path_quality']['short_0_5atr_first_pct']} | "
            f"{stats['persistent_short_pct']} | "
            f"{stats['short_then_reverse_pct']} |"
        )

    lines += [
        "",
        "## Average 4h path blocks — Priority",
        "",
        "| Block | Avg Short-direction ATR | Block ↓ % | Avg relative % |",
        "|---|---:|---:|---:|",
    ]
    for block, stats in priority["blocks"].items():
        lines.append(
            f"| {block} | {stats['avg_return_atr']} | "
            f"{stats['short_rate_pct']} | "
            f"{stats['avg_relative_pct']} |"
        )

    lines += [
        "",
        "## Model discrimination OOS",
        f"- AUC 4h: {a['auc']['4h']}",
        f"- AUC 12h: {a['auc']['12h']}",
        f"- AUC 24h: {a['auc']['24h']}",
        f"- AUC first-move: {a['auc']['first']}",
        "",
        "## Interpretation",
        "- PRIORITY_SHORT_SCALP means near-term opportunity is stronger than 12–24h persistence.",
        "- PRIORITY_SHORT_SWING requires both strong opportunity and stronger persistence probability.",
        "- The six 4h blocks show when downside usually appears and when reversal starts.",
        "- Shard count affects compute only; cross-sectional sample is created by the 120-symbol dense universe and aligned scan timestamps.",
        "",
    ]
    return "\n".join(lines)


def merge_reports(reports):
    if not reports:
        raise RuntimeError("No V4.2.5 shard reports found")

    expected = max(int(r.get("shard_count") or 1) for r in reports)
    found = {int(r.get("shard_index")) for r in reports}
    if found != set(range(expected)):
        raise RuntimeError(
            f"Incomplete V4.2.5 shards: expected {expected}, "
            f"found {sorted(found)}"
        )

    manifest_ids = {str(r.get("manifest_id")) for r in reports}
    periods = {
        (str(r.get("period_start")), str(r.get("period_end")))
        for r in reports
    }
    if len(manifest_ids) != 1 or len(periods) != 1:
        raise RuntimeError("V4.2.5 shard manifest/period mismatch")

    first = reports[0]
    manifest = first.get("manifest") or {}
    frozen = set(manifest.get("symbols") or [])

    merged_symbols = []
    raw = []
    errors = []
    for report in reports:
        merged_symbols.extend(report.get("selected_symbols") or [])
        raw.extend(report.get("trades") or [])
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
            f"V4.2.5 manifest integrity failed: {integrity}"
        )

    dedup = {}
    for row in raw:
        dedup.setdefault(
            (row.get("symbol"), row.get("signal_time")),
            row,
        )
    raw_rows = sorted(
        dedup.values(),
        key=lambda r: (
            str(r.get("signal_time")),
            str(r.get("symbol")),
        ),
    )

    scored, folds, models = _walk_forward(raw_rows)

    by_status = defaultdict(list)
    for row in scored:
        by_status[str(row.get("scanner_status") or "UNKNOWN")].append(row)

    non_bottom = [
        r for r in scored
        if not r.get("severe_bottom_rule")
    ]
    top10 = [r for r in non_bottom if r.get("top_10pct")]
    top20 = [r for r in non_bottom if r.get("top_20pct")]
    top30 = [r for r in non_bottom if r.get("top_30pct")]
    priority = [
        r for r in scored
        if str(r.get("scanner_status", "")).startswith(
            "PRIORITY_SHORT"
        )
    ]

    analysis = {
        "raw_candidate_count": len(raw_rows),
        "oos_scored_count": len(scored),
        "raw_cross_section": _cross_section_stats(raw_rows),
        "oos_cross_section": _cross_section_stats(scored),
        "overall_oos": _diagnostics(scored),
        "non_bottom_oos": _diagnostics(non_bottom),
        "top10_non_bottom": _diagnostics(top10),
        "top20_non_bottom": _diagnostics(top20),
        "top30_non_bottom": _diagnostics(top30),
        "priority_all": _diagnostics(priority),
        "by_status": {
            k: _diagnostics(v)
            for k, v in sorted(by_status.items())
        },
        "auc": {
            "4h": _auc(scored, "p_4h_lower", "y_4h_lower"),
            "12h": _auc(scored, "p_12h_lower", "y_12h_lower"),
            "24h": _auc(scored, "p_24h_lower", "y_24h_lower"),
            "first": _auc(scored, "p_first_short", "y_first_short"),
        },
        "brier": {
            "4h": _brier(scored, "p_4h_lower", "y_4h_lower"),
            "12h": _brier(scored, "p_12h_lower", "y_12h_lower"),
            "24h": _brier(scored, "p_24h_lower", "y_24h_lower"),
            "first": _brier(scored, "p_first_short", "y_first_short"),
        },
        "folds": folds,
        "feature_importance": _feature_importance(models),
    }

    return {
        "engine": "Crypto Short V4.2.5 Dense 24h Scanner",
        "manifest_id": next(iter(manifest_ids)),
        "manifest": manifest,
        "manifest_integrity": integrity,
        "period_start": first.get("period_start"),
        "period_end": first.get("period_end"),
        "days": first.get("days"),
        "selected_symbols": sorted(unique),
        "selected_symbol_count": len(unique),
        "analysis": analysis,
        "models": models,
        "trades": scored,
        "raw_candidate_count": len(raw_rows),
        "errors": errors,
    }


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "shard_outputs"
    report = merge_reports(_load(root))
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    _write_json(
        os.path.join(OUTPUT_DIR, "v425_backtest.json"),
        report,
    )
    _write_json(
        os.path.join(OUTPUT_DIR, "v425_analysis.json"),
        report["analysis"],
    )
    _write_json(
        os.path.join(OUTPUT_DIR, "v425_fold_models.json"),
        report["models"],
    )
    _write_json(
        os.path.join(OUTPUT_DIR, "v425_manifest.json"),
        report["manifest"],
    )
    _write_csv(
        os.path.join(OUTPUT_DIR, "v425_scored_candidates.csv"),
        report.get("trades") or [],
        fields=SCORED_FIELDS,
    )

    with open(
        os.path.join(OUTPUT_DIR, "v425_summary.md"),
        "w",
        encoding="utf-8",
    ) as handle:
        handle.write(_summary_md(report))

    print(json.dumps({
        "manifest_id": report.get("manifest_id"),
        "integrity": report.get("manifest_integrity"),
        "raw_cross_section": (
            report.get("analysis", {}).get("raw_cross_section")
        ),
        "priority": (
            report.get("analysis", {}).get("priority_all")
        ),
        "errors": len(report.get("errors") or []),
    }, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
