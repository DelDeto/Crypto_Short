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
from .v424_config import (
    V424_EMBARGO_HOURS,
    V424_INITIAL_TRAIN_FRACTION,
    V424_MIN_TRAIN_ROWS,
    V424_OOS_FOLDS,
    V424_PRIORITY_MIN_PROB,
    V424_PRIORITY_TOP_PCT,
    V424_READY_ZONE_DISTANCE_ATR,
    V424_WAIT_MIN_PROB,
    V424_WAIT_TOP_PCT,
    V424_WEIGHT_12H,
    V424_WEIGHT_4H,
    V424_WEIGHT_FIRST,
)
from .v424_main import CSV_FIELDS, _write_csv, _write_json
from .v424_model import FEATURE_NAMES, fit_logistic, predict_logistic


SCORED_FIELDS = CSV_FIELDS + [
    "oos_fold",
    "train_rows",
    "p_4h_lower",
    "p_12h_lower",
    "p_first_short",
    "directional_probability",
    "cross_section_rank",
    "cross_section_rank_pct",
    "top_10pct",
    "top_20pct",
    "top_30pct",
    "scanner_status",
    "entry_zone_ready",
]


def _load(root):
    reports = []
    for path in sorted(glob(
        os.path.join(root, "**", "v424_backtest.json"),
        recursive=True,
    )):
        with open(path, "r", encoding="utf-8") as handle:
            reports.append(json.load(handle))
    return reports


def _avg(rows, key):
    vals = [
        float(r[key])
        for r in rows
        if r.get(key) is not None
        and np.isfinite(float(r[key]))
    ]
    return round(sum(vals) / len(vals), 4) if vals else None


def _median(rows, key):
    vals = [
        float(r[key])
        for r in rows
        if r.get(key) is not None
        and np.isfinite(float(r[key]))
    ]
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
    return {
        "count": len(rows),
        "avg_directional_probability": _avg(
            rows, "directional_probability"
        ),
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
    }


def _brier(rows, prob_key, target_key):
    vals = [
        (float(r[prob_key]), 1.0 if bool(r[target_key]) else 0.0)
        for r in rows
        if r.get(prob_key) is not None
        and r.get(target_key) is not None
    ]
    if not vals:
        return None
    return round(
        sum((p - y) ** 2 for p, y in vals) / len(vals),
        5,
    )


def _probability_bins(rows):
    bins = {
        "0.40_0.50": [],
        "0.50_0.55": [],
        "0.55_0.60": [],
        "0.60_PLUS": [],
    }
    for row in rows:
        p = float(row.get("directional_probability") or 0.0)
        if p >= 0.60:
            bins["0.60_PLUS"].append(row)
        elif p >= 0.55:
            bins["0.55_0.60"].append(row)
        elif p >= 0.50:
            bins["0.50_0.55"].append(row)
        elif p >= 0.40:
            bins["0.40_0.50"].append(row)
    return {
        k: _diagnostics(v)
        for k, v in bins.items()
        if v
    }


def _feature_importance(models):
    by_head = {}
    for head in ("p4", "p12", "pfirst"):
        coefs = []
        for fold in models:
            model = fold.get(head) or {}
            if model.get("type") != "logistic":
                continue
            coefs.append(np.asarray(model.get("coef") or [], dtype=float))
        if not coefs:
            by_head[head] = []
            continue
        mat = np.vstack(coefs)
        signed = np.mean(mat, axis=0)
        absolute = np.mean(np.abs(mat), axis=0)
        order = np.argsort(-absolute)[:15]
        by_head[head] = [
            {
                "feature": FEATURE_NAMES[int(i)],
                "mean_coef": round(float(signed[i]), 4),
                "mean_abs_coef": round(float(absolute[i]), 4),
            }
            for i in order
        ]
    return by_head


def _assign_cross_section(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[str(row["signal_time"])].append(row)

    for _, group in grouped.items():
        group.sort(
            key=lambda r: (
                -float(r.get("directional_probability") or 0.0),
                str(r.get("symbol")),
            )
        )
        n = len(group)
        for i, row in enumerate(group):
            rank_pct = 0.0 if n <= 1 else i / float(n - 1)
            row["cross_section_rank"] = i + 1
            row["cross_section_rank_pct"] = round(rank_pct, 4)
            row["top_10pct"] = rank_pct <= 0.10
            row["top_20pct"] = rank_pct <= 0.20
            row["top_30pct"] = rank_pct <= 0.30

            upper = row.get("preferred_zone_upper")
            current = float(row.get("current_price") or 0.0)
            a1 = max(float(row.get("atr_1h") or 0.0), 1e-12)
            zone_dist = row.get("zone_distance_atr")
            zone_ready = bool(
                upper is not None
                and zone_dist is not None
                and float(zone_dist) <= V424_READY_ZONE_DISTANCE_ATR
                and current <= float(upper) + 0.15 * a1
            )
            row["entry_zone_ready"] = zone_ready

            p = float(row.get("directional_probability") or 0.0)
            if bool(row.get("severe_bottom_rule")):
                status = "AVOID_SHORT"
            elif (
                rank_pct <= V424_PRIORITY_TOP_PCT
                and p >= V424_PRIORITY_MIN_PROB
            ):
                status = (
                    "PRIORITY_SHORT"
                    if zone_ready
                    else "WAIT_PULLBACK"
                )
            elif (
                rank_pct <= V424_WAIT_TOP_PCT
                and p >= V424_WAIT_MIN_PROB
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
        int(len(times) * float(V424_INITIAL_TRAIN_FRACTION)),
    )
    initial = min(initial, len(times) - 1)
    remaining = times[initial:]
    if not remaining:
        return [], [], []

    fold_count = max(1, int(V424_OOS_FOLDS))
    blocks = [
        list(x)
        for x in np.array_split(
            np.asarray(remaining, dtype=object),
            fold_count,
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
            hours=int(V424_EMBARGO_HOURS)
        )

        train = [
            r for r in ordered
            if pd.Timestamp(r["signal_time"]) < train_cutoff
        ]
        test = [
            dict(r) for r in ordered
            if test_start <= pd.Timestamp(r["signal_time"]) <= test_end
        ]

        if len(train) < int(V424_MIN_TRAIN_ROWS) or not test:
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
        mf = fit_logistic(train, "y_first_short")

        p4 = predict_logistic(m4, test)
        p12 = predict_logistic(m12, test)
        pf = predict_logistic(mf, test)

        total_weight = (
            float(V424_WEIGHT_4H)
            + float(V424_WEIGHT_12H)
            + float(V424_WEIGHT_FIRST)
        )
        for row, a, b, c in zip(test, p4, p12, pf):
            combined = (
                float(V424_WEIGHT_4H) * a
                + float(V424_WEIGHT_12H) * b
                + float(V424_WEIGHT_FIRST) * c
            ) / max(total_weight, 1e-12)
            row["oos_fold"] = fold_index
            row["train_rows"] = len(train)
            row["p_4h_lower"] = round(float(a), 6)
            row["p_12h_lower"] = round(float(b), 6)
            row["p_first_short"] = round(float(c), 6)
            row["directional_probability"] = round(
                float(combined), 6
            )

        _assign_cross_section(test)
        scored.extend(test)

        priority = [
            r for r in test
            if r.get("scanner_status") == "PRIORITY_SHORT"
        ]
        top20 = [
            r for r in test
            if r.get("top_20pct")
            and not r.get("severe_bottom_rule")
        ]

        fold_reports.append({
            "fold": fold_index,
            "test_start": str(test_start),
            "test_end": str(test_end),
            "train_rows": len(train),
            "test_rows": len(test),
            "skipped": False,
            "all": _diagnostics(test),
            "priority_short": _diagnostics(priority),
            "top20_non_bottom": _diagnostics(top20),
            "brier": {
                "4h": _brier(test, "p_4h_lower", "y_4h_lower"),
                "12h": _brier(test, "p_12h_lower", "y_12h_lower"),
                "first": _brier(test, "p_first_short", "y_first_short"),
            },
        })

        model_records.append({
            "fold": fold_index,
            "test_start": str(test_start),
            "test_end": str(test_end),
            "train_cutoff": str(train_cutoff),
            "p4": m4,
            "p12": m12,
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
    o = a["overall_oos"]
    top10 = a["top10_non_bottom"]
    top20 = a["top20_non_bottom"]
    priority = a["by_status"].get("PRIORITY_SHORT") or _diagnostics([])

    lines = [
        "# Crypto Short V4.2.4 — Scanner-First Directional Ranking",
        "",
        f"- Manifest: {report.get('manifest_id')}",
        f"- Period: {report.get('period_start')} → {report.get('period_end')}",
        f"- Frozen symbols: {report.get('selected_symbol_count')}",
        f"- Manifest integrity: {'PASS' if report['manifest_integrity']['ok'] else 'FAIL'}",
        f"- Errors: {len(report.get('errors') or [])}",
        "",
        "## Method",
        "- Three expanding walk-forward logistic heads: P(4h lower), P(12h lower), P(-0.5ATR before +0.5ATR).",
        f"- Embargo: {V424_EMBARGO_HOURS}h between training labels and each OOS block.",
        "- Cross-sectional rank is calculated only from OOS probabilities available at the same timestamp.",
        "- Entry/SL/TP are discretionary reference levels; slippage is advisory.",
        "",
        "## OOS ranking result",
        "",
        "| Cohort | N | 1h ↓ | 4h ↓ | 12h ↓ | Short first | Adverse first | Avg 4h ATR | Bottom/wrong % |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for name, stats in (
        ("All OOS", o),
        ("Top 20% non-bottom", top20),
        ("Top 10% non-bottom", top10),
        ("PRIORITY_SHORT", priority),
    ):
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
        "## Scanner status",
        "",
        "| Status | N | 4h ↓ | 12h ↓ | Short first | Avg 4h ATR |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, stats in a["by_status"].items():
        lines.append(
            f"| {name} | {stats['count']} | "
            f"{stats['short_rate']['4h_pct']} | "
            f"{stats['short_rate']['12h_pct']} | "
            f"{stats['path_quality']['short_0_5atr_first_pct']} | "
            f"{stats['close_move_atr']['avg_4h']} |"
        )

    lines += [
        "",
        "## OOS fold stability",
        "",
        "| Fold | Train N | Test N | Top20 N | Top20 4h ↓ | Top20 Short first | Priority N | Priority 4h ↓ |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for fold in a["folds"]:
        if fold.get("skipped"):
            lines.append(
                f"| {fold['fold']} | {fold['train_rows']} | "
                f"{fold['test_rows']} | skipped | - | - | - | - |"
            )
            continue
        t = fold["top20_non_bottom"]
        p = fold["priority_short"]
        lines.append(
            f"| {fold['fold']} | {fold['train_rows']} | "
            f"{fold['test_rows']} | {t['count']} | "
            f"{t['short_rate']['4h_pct']} | "
            f"{t['path_quality']['short_0_5atr_first_pct']} | "
            f"{p['count']} | {p['short_rate']['4h_pct']} |"
        )

    lines += [
        "",
        "## Calibration",
        f"- Brier P(4h lower): {a['brier']['4h']}",
        f"- Brier P(12h lower): {a['brier']['12h']}",
        f"- Brier P(first Short): {a['brier']['first']}",
        "",
        "## Promotion criterion",
        "- The model should materially improve Top10/Top20 directional follow-through over All OOS and remain reasonably stable across folds.",
        "- If ranking does not improve OOS results, do not promote the learned score to the live scanner.",
        "",
    ]
    return "\n".join(lines)


def merge_reports(reports):
    if not reports:
        raise RuntimeError("No V4.2.4 shard reports found")

    expected = max(int(r.get("shard_count") or 1) for r in reports)
    found = {int(r.get("shard_index")) for r in reports}
    if found != set(range(expected)):
        raise RuntimeError(
            f"Incomplete V4.2.4 shards: expected {expected}, "
            f"found {sorted(found)}"
        )

    manifest_ids = {str(r.get("manifest_id")) for r in reports}
    periods = {
        (str(r.get("period_start")), str(r.get("period_end")))
        for r in reports
    }
    if len(manifest_ids) != 1 or len(periods) != 1:
        raise RuntimeError("V4.2.4 shard manifest/period mismatch")

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
            f"V4.2.4 manifest integrity failed: {integrity}"
        )

    dedup = {}
    for row in rows:
        key = (row.get("symbol"), row.get("signal_time"))
        dedup.setdefault(key, row)
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
        by_status[
            str(row.get("scanner_status") or "UNKNOWN")
        ].append(row)

    non_bottom = [
        r for r in scored
        if not r.get("severe_bottom_rule")
    ]
    top10 = [r for r in non_bottom if r.get("top_10pct")]
    top20 = [r for r in non_bottom if r.get("top_20pct")]
    top30 = [r for r in non_bottom if r.get("top_30pct")]

    analysis = {
        "raw_candidate_count": len(raw_rows),
        "oos_scored_count": len(scored),
        "overall_oos": _diagnostics(scored),
        "non_bottom_oos": _diagnostics(non_bottom),
        "top10_non_bottom": _diagnostics(top10),
        "top20_non_bottom": _diagnostics(top20),
        "top30_non_bottom": _diagnostics(top30),
        "by_status": {
            k: _diagnostics(v)
            for k, v in sorted(by_status.items())
        },
        "probability_bins": _probability_bins(scored),
        "brier": {
            "4h": _brier(scored, "p_4h_lower", "y_4h_lower"),
            "12h": _brier(scored, "p_12h_lower", "y_12h_lower"),
            "first": _brier(scored, "p_first_short", "y_first_short"),
        },
        "folds": folds,
        "feature_importance": _feature_importance(models),
    }

    return {
        "engine": "Crypto Short V4.2.4 Scanner-First Ranking",
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
        os.path.join(OUTPUT_DIR, "v424_backtest.json"),
        report,
    )
    _write_json(
        os.path.join(OUTPUT_DIR, "v424_analysis.json"),
        report["analysis"],
    )
    _write_json(
        os.path.join(OUTPUT_DIR, "v424_fold_models.json"),
        report["models"],
    )
    _write_json(
        os.path.join(OUTPUT_DIR, "v424_manifest.json"),
        report["manifest"],
    )
    _write_csv(
        os.path.join(OUTPUT_DIR, "v424_scored_candidates.csv"),
        report.get("trades") or [],
        fields=SCORED_FIELDS,
    )

    with open(
        os.path.join(OUTPUT_DIR, "v424_summary.md"),
        "w",
        encoding="utf-8",
    ) as handle:
        handle.write(_summary_md(report))

    print(json.dumps({
        "manifest_id": report.get("manifest_id"),
        "integrity": report.get("manifest_integrity"),
        "raw_candidates": report.get("raw_candidate_count"),
        "oos_scored": report.get("analysis", {}).get("oos_scored_count"),
        "top20": report.get("analysis", {}).get("top20_non_bottom"),
        "priority": (
            report.get("analysis", {})
            .get("by_status", {})
            .get("PRIORITY_SHORT")
        ),
        "errors": len(report.get("errors") or []),
    }, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
