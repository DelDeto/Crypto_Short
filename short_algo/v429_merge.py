"""V4.2.9 merge: rule-gated Early Downtrend, model-ranked only."""

import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import timedelta
from glob import glob

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from .config import OUTPUT_DIR
from .v428_merge import _add_cross_section_and_phase
from .v428_model import (
    ENTRY_FEATURE_NAMES,
    REVERSAL_FEATURE_NAMES,
    TREND_FEATURE_NAMES,
    fit_model,
    predict_model,
)
from .v429_config import (
    V429_EMBARGO_HOURS,
    V429_INITIAL_TRAIN_FRACTION,
    V429_MAX_BREAKDOWN_AGE_HOURS,
    V429_MIN_TRAIN_ROWS,
    V429_MODEL_WEIGHT,
    V429_OOS_FOLDS,
    V429_REVERSAL_PENALTY_POWER,
    V429_RULE_WEIGHT,
    V429_ZONE_WAIT_MAX_ATR,
)
from .v429_main import CSV_FIELDS, _write_csv, _write_json


SCORED_FIELDS = CSV_FIELDS + [
    "xs_weak_rank_4h", "xs_weak_rank_12h", "xs_weak_rank_24h",
    "xs_relative_weak_rank_4h", "xs_relative_weak_rank_24h",
    "xs_weak_consistency", "xs_weak_average",
    "v428_structure_score", "v428_exhaustion_score", "v428_recovery_score",
    "v428_fast_drop_atr_proxy", "v428_extreme_weakness",
    "v428_trend_phase", "v428_phase_early", "v428_phase_mature",
    "v428_phase_exhausted", "v428_phase_recovery",
    "oos_fold", "train_rows",
    "p_4h_lower", "p_12h_lower", "p_24h_lower",
    "p_rel_12h_underperform", "p_rel_24h_underperform",
    "p_trend_stable", "p_reversal_after_short", "p_confirmed_2r",
    "direction_consensus", "context_consensus",
    "v429_rule_quality", "v429_model_quality", "v429_rank_score",
    "v429_rank", "v429_rank_pct",
    "v429_fresh_breakdown", "v429_structure_ok", "v429_core_preconfirm",
    "v429_priority_core", "scanner_status",
]


def _load(root):
    out = []
    for path in sorted(glob(os.path.join(root, "**", "v429_backtest.json"), recursive=True)):
        with open(path, "r", encoding="utf-8") as h:
            out.append(json.load(h))
    return out


def _rate(rows, key):
    vals = [bool(r.get(key)) for r in rows if r.get(key) is not None]
    return round(sum(vals) / len(vals) * 100.0, 2) if vals else None


def _avg(rows, key):
    vals = []
    for row in rows:
        try:
            value = float(row.get(key))
        except (TypeError, ValueError):
            continue
        if np.isfinite(value):
            vals.append(value)
    return round(float(np.mean(vals)), 4) if vals else None


def _auc(rows, prob, target):
    vals = [
        (float(r[prob]), 1 if bool(r[target]) else 0)
        for r in rows
        if r.get(prob) is not None and r.get(target) is not None
    ]
    if not vals:
        return None
    y = np.asarray([v[1] for v in vals], dtype=int)
    if np.unique(y).size < 2:
        return None
    p = np.asarray([v[0] for v in vals], dtype=float)
    return round(float(roc_auc_score(y, p)), 5)


def _geom(values):
    vals = [max(1e-4, min(0.9999, float(v))) for v in values]
    return math.exp(sum(math.log(v) for v in vals) / len(vals))


def _model_cfg():
    # Same model family as V4.2.8; V4.2.9 changes how predictions are used.
    return {
        "learning_rate": 0.04,
        "max_iter": 180,
        "max_leaf_nodes": 15,
        "min_samples_leaf": 70,
        "l2": 2.0,
    }


def _base(model):
    return float(model.get("base_rate", model.get("probability", 0.5)) or 0.5)


def _post_sl_diag(rows):
    losses = [r for r in rows if r.get("post_sl_class")]
    classes = Counter(str(r.get("post_sl_class")) for r in losses)
    if not losses:
        return {"losses_audited": 0, "classes": {}}
    return {
        "losses_audited": len(losses),
        "classes": dict(sorted(classes.items())),
        "reclaim_entry_pct": _rate(losses, "post_sl_reclaim_entry"),
        "then_plus_1r_pct": _rate(losses, "post_sl_plus_1r"),
        "then_plus_2r_pct": _rate(losses, "post_sl_plus_2r"),
        "avg_post_sl_mfe_r": _avg(losses, "post_sl_mfe_r"),
        "avg_additional_adverse_r": _avg(losses, "post_sl_additional_adverse_r"),
    }


def _diag(rows):
    ft = Counter(
        str(r.get("ft_first_0_5r_move"))
        for r in rows
        if r.get("ft_first_0_5r_move") is not None
    )
    confirmed = [
        r for r in rows if r.get("y_confirmed_2r_success") is not None
    ]
    wins = sum(bool(r.get("y_confirmed_2r_success")) for r in confirmed)
    win_rate = (wins / len(confirmed)) if confirmed else None
    gross_exp = None if win_rate is None else round(3.0 * win_rate - 1.0, 4)
    return {
        "count": len(rows),
        "short_rate": {
            "4h": _rate(rows, "y_4h_lower"),
            "12h": _rate(rows, "y_12h_lower"),
            "24h": _rate(rows, "y_24h_lower"),
        },
        "all3_short_pct": _rate(rows, "y_persistent_short"),
        "trend_stable_pct": _rate(rows, "y_trend_stable"),
        "reversal_after_short_pct": _rate(rows, "y_reversal_after_short"),
        "entry_confirmed_pct": _rate(rows, "v428_entry_confirmed"),
        "confirmed_trades": len(confirmed),
        "confirmed_2r_success_pct": (
            round(win_rate * 100.0, 2) if win_rate is not None else None
        ),
        "binary_2r_gross_expectancy_r": gross_exp,
        "avg_support_room_r": _avg(rows, "v428_confirm_support_room_r"),
        "avg_rule_quality": _avg(rows, "v429_rule_quality"),
        "avg_model_quality": _avg(rows, "v429_model_quality"),
        "avg_rank_score": _avg(rows, "v429_rank_score"),
        "followthrough_first_0_5r": dict(sorted(ft.items())),
        "avg_close_r": {
            "1h": _avg(rows, "ft_close_r_1h"),
            "4h": _avg(rows, "ft_close_r_4h"),
            "12h": _avg(rows, "ft_close_r_12h"),
            "24h": _avg(rows, "ft_close_r_24h"),
        },
        "avg_mfe_r": {
            "4h": _avg(rows, "ft_mfe_r_4h"),
            "24h": _avg(rows, "ft_mfe_r_24h"),
        },
        "avg_mae_r": {
            "4h": _avg(rows, "ft_mae_r_4h"),
            "24h": _avg(rows, "ft_mae_r_24h"),
        },
        "post_sl": _post_sl_diag(rows),
    }


def _rule_fields(row):
    phase = str(row.get("v428_trend_phase") or "UNCONFIRMED")
    try:
        age = float(row.get("breakdown_age_1h"))
    except (TypeError, ValueError):
        age = 999.0

    fresh_break = bool(
        int(row.get("breakdown_detected") or 0) == 1
        and age <= float(V429_MAX_BREAKDOWN_AGE_HOURS)
    )
    structure_ok = bool(
        int(row.get("s4_ema_bear") or 0) == 1
        and int(row.get("s4_lower_high") or 0) == 1
        and fresh_break
    )
    strong_zone = int(row.get("v428_strong_zone") or 0) == 1
    touched = int(row.get("v428_zone_touched_recent") or 0) == 1
    confirmed = int(row.get("v428_entry_confirmed") or 0) == 1
    rr_room = int(row.get("v428_confirm_rr2_room_ok") or 0) == 1
    no_reclaim = int(row.get("v428_no_reclaim_after_touch") or 0) == 1
    severe_bottom = bool(row.get("severe_bottom_rule"))

    core_preconfirm = bool(
        phase == "EARLY_DOWNTREND"
        and structure_ok
        and strong_zone
        and not severe_bottom
    )
    priority_core = bool(
        core_preconfirm and touched and confirmed and rr_room and no_reclaim
    )
    return (
        phase, fresh_break, structure_ok, strong_zone, touched,
        confirmed, rr_room, no_reclaim, severe_bottom,
        core_preconfirm, priority_core,
    )


def _quality(row):
    (
        phase, fresh_break, structure_ok, strong_zone, touched,
        confirmed, rr_room, no_reclaim, severe_bottom,
        core_preconfirm, priority_core,
    ) = _rule_fields(row)

    structure = min(1.0, max(0.0, float(row.get("v428_structure_score") or 0.0) / 7.5))
    confirm_score = min(1.0, max(0.0, float(row.get("v428_entry_confirm_score") or 0.0) / 5.0))
    weakness = min(1.0, max(0.0, float(row.get("xs_weak_average") or 0.5)))
    try:
        room = float(row.get("v428_confirm_support_room_r"))
        room_score = min(1.0, max(0.0, room / 4.0))
    except (TypeError, ValueError):
        room_score = 0.0

    rule = (
        0.24 * structure
        + 0.16 * float(fresh_break)
        + 0.14 * float(strong_zone)
        + 0.18 * confirm_score
        + 0.14 * room_score
        + 0.08 * weakness
        + 0.06 * float(phase == "EARLY_DOWNTREND")
    )
    if severe_bottom:
        rule *= 0.35
    if bool(row.get("v428_reclaim_after_touch")):
        rule *= 0.35
    return max(0.0, min(1.0, rule))


def _rank_and_status(test):
    groups = defaultdict(list)
    for row in test:
        groups[str(row["signal_time"])].append(row)

    for group in groups.values():
        for row in group:
            phase, fresh_break, structure_ok, strong_zone, touched, confirmed, rr_room, no_reclaim, severe_bottom, core_preconfirm, priority_core = _rule_fields(row)
            rule_quality = _quality(row)
            model_quality = _geom([
                row.get("direction_consensus") or 0.5,
                row.get("context_consensus") or 0.5,
                max(1e-4, 1.0 - float(row.get("p_reversal_after_short") or 0.5)),
                row.get("p_confirmed_2r") or 0.5,
            ])
            rank_score = (
                float(V429_RULE_WEIGHT) * rule_quality
                + float(V429_MODEL_WEIGHT) * model_quality
            )

            row["v429_rule_quality"] = round(rule_quality, 6)
            row["v429_model_quality"] = round(model_quality, 6)
            row["v429_rank_score"] = round(rank_score, 6)
            row["v429_fresh_breakdown"] = int(fresh_break)
            row["v429_structure_ok"] = int(structure_ok)
            row["v429_core_preconfirm"] = int(core_preconfirm)
            row["v429_priority_core"] = int(priority_core)

            reclaimed = int(row.get("v428_reclaim_after_touch") or 0) == 1
            below = int(row.get("v428_below_zone") or 0) == 1
            try:
                distance = float(row.get("v428_entry_zone_distance_atr"))
            except (TypeError, ValueError):
                distance = 999.0

            if phase in ("EXHAUSTED_DOWNTREND", "RECOVERY_RECLAIM"):
                status = "AVOID_SHORT"
            elif severe_bottom or reclaimed:
                status = "AVOID_SHORT"
            elif priority_core:
                status = "PRIORITY_SHORT"
            elif phase == "EARLY_DOWNTREND" and confirmed and not rr_room:
                status = "AVOID_SHORT_RR"
            elif core_preconfirm and touched and not confirmed:
                status = "ZONE_TOUCHED_WAIT_CONFIRMATION"
            elif (
                core_preconfirm and strong_zone and below and not touched
                and distance <= float(V429_ZONE_WAIT_MAX_ATR)
            ):
                status = "WAIT_ENTRY_ZONE"
            elif phase == "EARLY_DOWNTREND":
                status = "EARLY_WATCH"
            elif phase == "MATURE_DOWNTREND":
                status = "MATURE_WATCH"
            else:
                status = "WATCH"
            row["scanner_status"] = status

        group.sort(key=lambda r: (-float(r.get("v429_rank_score") or 0.0), str(r.get("symbol"))))
        n = len(group)
        for i, row in enumerate(group):
            row["v429_rank"] = i + 1
            row["v429_rank_pct"] = round(i / float(max(n, 1)), 4)


def _walk_forward(rows):
    ordered = sorted(rows, key=lambda r: (pd.Timestamp(r["signal_time"]), str(r.get("symbol"))))
    times = sorted({pd.Timestamp(r["signal_time"]) for r in ordered})
    if len(times) < 12:
        return [], [], []

    initial = min(
        max(2, int(len(times) * float(V429_INITIAL_TRAIN_FRACTION))),
        len(times) - 1,
    )
    remaining = times[initial:]
    blocks = [
        list(x)
        for x in np.array_split(np.asarray(remaining, dtype=object), max(1, int(V429_OOS_FOLDS)))
        if len(x)
    ]

    scored = []
    folds = []
    meta = []
    cfg = _model_cfg()

    for fold_idx, block in enumerate(blocks, start=1):
        test_start = pd.Timestamp(block[0])
        test_end = pd.Timestamp(block[-1])
        cutoff = test_start - timedelta(hours=int(V429_EMBARGO_HOURS))
        train = [r for r in ordered if pd.Timestamp(r["signal_time"]) < cutoff]
        test = [
            dict(r) for r in ordered
            if test_start <= pd.Timestamp(r["signal_time"]) <= test_end
        ]
        if len(train) < int(V429_MIN_TRAIN_ROWS) or not test:
            folds.append({
                "fold": fold_idx,
                "train_rows": len(train),
                "test_rows": len(test),
                "skipped": True,
            })
            continue

        heads = {
            "4h": fit_model(train, "y_4h_lower", TREND_FEATURE_NAMES, cfg),
            "12h": fit_model(train, "y_12h_lower", TREND_FEATURE_NAMES, cfg),
            "24h": fit_model(train, "y_24h_lower", TREND_FEATURE_NAMES, cfg),
            "rel12": fit_model(train, "y_rel_12h_underperform", TREND_FEATURE_NAMES, cfg),
            "rel24": fit_model(train, "y_rel_24h_underperform", TREND_FEATURE_NAMES, cfg),
            "stable": fit_model(train, "y_trend_stable", TREND_FEATURE_NAMES, cfg),
            "reversal": fit_model(train, "y_reversal_after_short", REVERSAL_FEATURE_NAMES, cfg),
            "2r": fit_model(train, "y_confirmed_2r_success", ENTRY_FEATURE_NAMES, cfg),
        }
        pred = {key: predict_model(model, test) for key, model in heads.items()}
        bases = {key: _base(model) for key, model in heads.items()}

        for idx, row in enumerate(test):
            row.update({
                "oos_fold": fold_idx,
                "train_rows": len(train),
                "p_4h_lower": round(pred["4h"][idx], 6),
                "p_12h_lower": round(pred["12h"][idx], 6),
                "p_24h_lower": round(pred["24h"][idx], 6),
                "p_rel_12h_underperform": round(pred["rel12"][idx], 6),
                "p_rel_24h_underperform": round(pred["rel24"][idx], 6),
                "p_trend_stable": round(pred["stable"][idx], 6),
                "p_reversal_after_short": round(pred["reversal"][idx], 6),
                "p_confirmed_2r": round(pred["2r"][idx], 6),
            })
            direction = _geom([pred["4h"][idx], pred["12h"][idx], pred["24h"][idx]])
            context = _geom([pred["rel12"][idx], pred["rel24"][idx], pred["stable"][idx]])
            row["direction_consensus"] = round(direction, 6)
            row["context_consensus"] = round(context, 6)

        _rank_and_status(test)
        scored.extend(test)

        by = defaultdict(list)
        for row in test:
            by[str(row.get("scanner_status"))].append(row)
        folds.append({
            "fold": fold_idx,
            "test_start": str(test_start),
            "test_end": str(test_end),
            "train_rows": len(train),
            "test_rows": len(test),
            "skipped": False,
            "priority": _diag(by.get("PRIORITY_SHORT", [])),
            "wait_entry": _diag(by.get("WAIT_ENTRY_ZONE", [])),
            "wait_confirm": _diag(by.get("ZONE_TOUCHED_WAIT_CONFIRMATION", [])),
        })
        meta.append({
            "fold": fold_idx,
            "train_rows": len(train),
            "base_rates": bases,
            "confirmed_entry_train_n": heads["2r"].get("train_n"),
            "policy": "models_rank_only_no_probability_hard_gate",
        })

    scored.sort(key=lambda r: (str(r.get("signal_time")), str(r.get("symbol"))))
    return scored, folds, meta


def _summary(report):
    a = report["analysis"]
    lines = [
        "# Crypto Short V4.2.9 — Location-First Early Downtrend",
        "",
        f"- Period: {report['period_start']} → {report['period_end']}",
        f"- Symbols: {report['selected_symbol_count']}",
        f"- Integrity: {'PASS' if report['manifest_integrity']['ok'] else 'FAIL'}",
        f"- Errors: {len(report.get('errors') or [])}",
        f"- Median coins/timestamp: {a['cross_section_median']}",
        "",
        "## Core change",
        "- ML probabilities are ranking/context only; they cannot block an otherwise valid entry.",
        "- PRIORITY_SHORT is rule-gated: EARLY_DOWNTREND + fresh 4H bearish breakdown + strong zone + recent touch + no reclaim + bearish confirmation + >=2R room.",
        "- MATURE_DOWNTREND is watch-only. EXHAUSTED_DOWNTREND and RECOVERY_RECLAIM are blocked.",
        "",
        "## OOS cohorts",
        "",
        "| Cohort | N | Confirmed | TP2R | Gross Exp R | 4h ↓ | 12h ↓ | 24h ↓ |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    cohorts = [
        ("All OOS", a["overall"]),
        ("EARLY phase", a["early_phase"]),
        ("EARLY confirmed", a["early_confirmed"]),
        ("PRIORITY_SHORT", a["by_status"].get("PRIORITY_SHORT", _diag([]))),
        ("WAIT_ENTRY_ZONE", a["by_status"].get("WAIT_ENTRY_ZONE", _diag([]))),
        ("WAIT_CONFIRMATION", a["by_status"].get("ZONE_TOUCHED_WAIT_CONFIRMATION", _diag([]))),
    ]
    for name, s in cohorts:
        lines.append(
            f"| {name} | {s['count']} | {s['confirmed_trades']} | "
            f"{s['confirmed_2r_success_pct']} | {s['binary_2r_gross_expectancy_r']} | "
            f"{s['short_rate']['4h']} | {s['short_rate']['12h']} | {s['short_rate']['24h']} |"
        )

    p = a["by_status"].get("PRIORITY_SHORT", _diag([]))
    lines += [
        "",
        "## PRIORITY_SHORT follow-through",
        f"- First 0.5R move: {p['followthrough_first_0_5r']}",
        f"- Avg close R 1h/4h/12h/24h: {p['avg_close_r']}",
        f"- Avg MFE R 4h/24h: {p['avg_mfe_r']}",
        f"- Avg MAE R 4h/24h: {p['avg_mae_r']}",
        f"- Post-SL: {p['post_sl']}",
        "",
        "## OOS AUC (diagnostic only, not entry gates)",
    ]
    for key, value in a["auc"].items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines)


def merge_reports(reports):
    if not reports:
        raise RuntimeError("No V4.2.9 shard reports found")

    expected = max(int(r.get("shard_count") or 1) for r in reports)
    found = {int(r.get("shard_index")) for r in reports}
    if found != set(range(expected)):
        raise RuntimeError(f"Incomplete V4.2.9 shards: {sorted(found)}")

    ids = {str(r.get("manifest_id")) for r in reports}
    if len(ids) != 1:
        raise RuntimeError("V4.2.9 manifest mismatch")

    first = reports[0]
    frozen = set((first.get("manifest") or {}).get("symbols") or [])
    symbols, raw, errors = [], [], []
    for report in reports:
        symbols.extend(report.get("selected_symbols") or [])
        raw.extend(report.get("trades") or [])
        errors.extend(report.get("errors") or [])

    unique = set(symbols)
    integrity = {
        "ok": len(reports) == expected and len(symbols) == len(unique) and unique == frozen,
        "expected_shards": expected,
        "found_shards": len(reports),
        "frozen_symbol_count": len(frozen),
        "merged_symbol_count": len(unique),
    }
    if not integrity["ok"]:
        raise RuntimeError(f"V4.2.9 integrity failed: {integrity}")

    dedup = {}
    for row in raw:
        dedup.setdefault((row.get("symbol"), row.get("signal_time")), row)
    raw_rows = sorted(
        dedup.values(),
        key=lambda r: (str(r.get("signal_time")), str(r.get("symbol"))),
    )

    _add_cross_section_and_phase(raw_rows)
    scored, folds, meta = _walk_forward(raw_rows)

    by_status = defaultdict(list)
    by_phase = defaultdict(list)
    for row in scored:
        by_status[str(row.get("scanner_status") or "UNKNOWN")].append(row)
        by_phase[str(row.get("v428_trend_phase") or "UNKNOWN")].append(row)

    early_phase = [r for r in scored if r.get("v428_trend_phase") == "EARLY_DOWNTREND"]
    early_confirmed = [r for r in early_phase if bool(r.get("v428_entry_confirmed"))]

    counts = defaultdict(int)
    for row in scored:
        counts[str(row["signal_time"])] += 1
    median = float(np.median(list(counts.values()))) if counts else None

    auc = {
        "4h": _auc(scored, "p_4h_lower", "y_4h_lower"),
        "12h": _auc(scored, "p_12h_lower", "y_12h_lower"),
        "24h": _auc(scored, "p_24h_lower", "y_24h_lower"),
        "relative12": _auc(scored, "p_rel_12h_underperform", "y_rel_12h_underperform"),
        "relative24": _auc(scored, "p_rel_24h_underperform", "y_rel_24h_underperform"),
        "stability": _auc(scored, "p_trend_stable", "y_trend_stable"),
        "reversal": _auc(scored, "p_reversal_after_short", "y_reversal_after_short"),
        "confirmed_2r": _auc(scored, "p_confirmed_2r", "y_confirmed_2r_success"),
    }

    analysis = {
        "raw_count": len(raw_rows),
        "oos_count": len(scored),
        "cross_section_median": round(median, 2) if median is not None else None,
        "overall": _diag(scored),
        "early_phase": _diag(early_phase),
        "early_confirmed": _diag(early_confirmed),
        "by_status": {key: _diag(value) for key, value in sorted(by_status.items())},
        "by_phase": {key: _diag(value) for key, value in sorted(by_phase.items())},
        "auc": auc,
        "folds": folds,
    }

    return {
        "engine": "Crypto Short V4.2.9 Location-First Early Downtrend",
        "manifest_id": next(iter(ids)),
        "manifest": first.get("manifest"),
        "manifest_integrity": integrity,
        "period_start": first.get("period_start"),
        "period_end": first.get("period_end"),
        "days": first.get("days"),
        "selected_symbols": sorted(unique),
        "selected_symbol_count": len(unique),
        "analysis": analysis,
        "model_meta": meta,
        "trades": scored,
        "errors": errors,
    }


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "shard_outputs"
    report = merge_reports(_load(root))
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    _write_json(os.path.join(OUTPUT_DIR, "v429_backtest.json"), report)
    _write_json(os.path.join(OUTPUT_DIR, "v429_analysis.json"), report["analysis"])
    _write_json(os.path.join(OUTPUT_DIR, "v429_model_meta.json"), report["model_meta"])
    _write_json(os.path.join(OUTPUT_DIR, "v429_manifest.json"), report["manifest"])
    _write_csv(
        os.path.join(OUTPUT_DIR, "v429_scored_candidates.csv"),
        report.get("trades") or [],
        fields=SCORED_FIELDS,
    )
    with open(os.path.join(OUTPUT_DIR, "v429_summary.md"), "w", encoding="utf-8") as h:
        h.write(_summary(report))

    print(json.dumps({
        "integrity": report["manifest_integrity"],
        "median_coins_per_timestamp": report["analysis"]["cross_section_median"],
        "early_confirmed": report["analysis"]["early_confirmed"],
        "priority": report["analysis"]["by_status"].get("PRIORITY_SHORT"),
        "wait_entry": report["analysis"]["by_status"].get("WAIT_ENTRY_ZONE"),
        "wait_confirmation": report["analysis"]["by_status"].get("ZONE_TOUCHED_WAIT_CONFIRMATION"),
        "auc": report["analysis"]["auc"],
        "errors": len(report.get("errors") or []),
    }, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
