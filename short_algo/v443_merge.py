"""V4.4.3 60d merge: corrected M1 comparator, episode-first M1, M2 funnel."""
import json
import os
import sys
from collections import Counter
from glob import glob

import numpy as np
import pandas as pd

from .config import OUTPUT_DIR
from .v428_merge import _add_cross_section_and_phase
from .v441_execution import TERMINAL_STATES
from .v441_main import CSV_FIELDS, _write_csv, _write_json
from .v443_config import (
    V443_COOLDOWN_HOURS,
    V443_M1B_MAX_COST_R,
    V443_M1B_MIN_ROOM_R,
    V443_M1B_MIN_SCORE,
    V443_M1BPLUS_MAX_COST_R,
    V443_M1BPLUS_MIN_ROOM_R,
    V443_M1BPLUS_MIN_SCORE,
    V443_M2_MAX_BREAK_BODY_ATR,
    V443_M2_MAX_COST_R,
    V443_M2_MAX_ENTRY_BELOW_SUPPORT_ATR,
    V443_M2_MIN_ACCEPTANCE_BARS,
    V443_M2_MIN_ROOM_R,
    V443_M2_MIN_SCORE,
)


def _load(root):
    reports = []
    for path in sorted(glob(os.path.join(root, "**", "v443_backtest.json"), recursive=True)):
        with open(path, "r", encoding="utf-8") as f:
            reports.append(json.load(f))
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


def _pf(values):
    vals = [x for x in (_num(v) for v in values) if x is not None]
    gains = sum(x for x in vals if x > 0)
    losses = -sum(x for x in vals if x < 0)
    if losses <= 0:
        return 999.0 if gains > 0 else None
    return round(gains / losses, 4)


def _terminal(row, prefix):
    return (
        row.get(f"{prefix}_state") in TERMINAL_STATES
        and _num(row.get(f"{prefix}_net_r")) is not None
    )


def _unique(rows):
    last = {}
    out = []
    for row in sorted(rows, key=lambda x: (str(x.get("signal_time")), str(x.get("symbol")))):
        symbol = str(row.get("symbol"))
        t = pd.Timestamp(row.get("signal_time"))
        previous = last.get(symbol)
        if previous is not None and (t - previous) < pd.Timedelta(hours=int(V443_COOLDOWN_HOURS)):
            continue
        last[symbol] = t
        out.append(row)
    return out


def _phase_ok(row):
    return str(row.get("v428_trend_phase") or "") in (
        "EARLY_DOWNTREND",
        "MATURE_DOWNTREND",
    )


def _m1a(row):
    # Correct apples-to-apples comparator: strict V4.4 only inside the same
    # M1 context used by V4.4.1.
    return bool(
        int(row.get("v441_m1_context_ok") or 0) == 1
        and _terminal(row, "v440")
    )


def _m1b(row):
    score = int(row.get("v441_m1_confirm_score") or 0)
    cost = _num(row.get("v441_m1_cost_r"))
    room = _num(row.get("v441_m1_room_r"))
    return bool(
        _terminal(row, "v441_m1")
        and _phase_ok(row)
        and score >= int(V443_M1B_MIN_SCORE)
        and int(row.get("v441_m1_failed_auction") or 0) == 1
        and (
            int(row.get("v441_m1_micro_bos") or 0) == 1
            or int(row.get("v441_m1_rejection") or 0) == 1
        )
        and cost is not None
        and cost <= float(V443_M1B_MAX_COST_R)
        and room is not None
        and room >= float(V443_M1B_MIN_ROOM_R)
    )


def _m1bplus(row):
    score = int(row.get("v441_m1_confirm_score") or 0)
    cost = _num(row.get("v441_m1_cost_r"))
    room = _num(row.get("v441_m1_room_r"))
    return bool(
        _terminal(row, "v441_m1")
        and _phase_ok(row)
        and score >= int(V443_M1BPLUS_MIN_SCORE)
        and int(row.get("v441_m1_failed_auction") or 0) == 1
        and int(row.get("v441_m1_micro_bos") or 0) == 1
        and int(row.get("v441_m1_rejection") or 0) == 1
        and cost is not None
        and cost <= float(V443_M1BPLUS_MAX_COST_R)
        and room is not None
        and room >= float(V443_M1BPLUS_MIN_ROOM_R)
    )


def _m2_base(row):
    return _terminal(row, "v441_m2")


def _m2_location(row):
    entry = _num(row.get("v441_m2_entry"))
    support = _num(row.get("v441_m2_support_level"))
    atr = _num(row.get("atr_1h"))
    if None in (entry, support, atr) or atr <= 0:
        return None
    distance = max(0.0, (support - entry) / atr)
    row["v443_m2_entry_below_support_atr"] = round(distance, 4)
    return distance


def _m2_balanced(row):
    if not _m2_base(row):
        return False
    score = int(row.get("v441_m2_confirm_score") or 0)
    cost = _num(row.get("v441_m2_cost_r"))
    room = _num(row.get("v441_m2_room_r"))
    body = _num(row.get("v441_m2_break_body_atr"))
    distance = _m2_location(row)
    acceptance = int(row.get("v441_m2_acceptance_bars") or 0)
    reclaim_quality = bool(
        int(row.get("v441_m2_retest_rejection") or 0) == 1
        or acceptance >= int(V443_M2_MIN_ACCEPTANCE_BARS)
    )
    return bool(
        _phase_ok(row)
        and score >= int(V443_M2_MIN_SCORE)
        and int(row.get("v441_m2_controlled_break") or 0) == 1
        and reclaim_quality
        and distance is not None
        and distance <= float(V443_M2_MAX_ENTRY_BELOW_SUPPORT_ATR)
        and body is not None
        and body <= float(V443_M2_MAX_BREAK_BODY_ATR)
        and cost is not None
        and cost <= float(V443_M2_MAX_COST_R)
        and room is not None
        and room >= float(V443_M2_MIN_ROOM_R)
    )


def _metrics(rows, prefix):
    fills = [r for r in rows if _terminal(r, prefix)]
    net = [float(r[f"{prefix}_net_r"]) for r in fills]
    gross = [
        float(r[f"{prefix}_gross_r"])
        for r in fills
        if _num(r.get(f"{prefix}_gross_r")) is not None
    ]
    return {
        "fills": len(fills),
        "positive_net": sum(x > 0 for x in net),
        "positive_net_pct": _pct(sum(x > 0 for x in net), len(net)),
        "stop_pct": _pct(
            sum(r.get(f"{prefix}_state") == "SL_FIRST" for r in fills),
            len(fills),
        ),
        "tp1_hit_pct": (
            None
            if prefix == "v440"
            else _pct(
                sum(int(r.get(f"{prefix}_tp1_hit") or 0) for r in fills),
                len(fills),
            )
        ),
        "tp2_demand_pct": _pct(
            sum(r.get(f"{prefix}_state") == "TP2_DEMAND" for r in fills),
            len(fills),
        ),
        "ft_pass_pct": (
            None
            if prefix == "v440"
            else _pct(
                sum(int(r.get(f"{prefix}_ft_pass") or 0) for r in fills),
                len(fills),
            )
        ),
        "gross_expectancy_r": _mean(gross),
        "net_expectancy_r": _mean(net),
        "profit_factor": _pf(net),
        "total_net_r": round(sum(net), 5),
        "avg_cost_r": _mean([r.get(f"{prefix}_cost_r") for r in fills]),
        "avg_room_r": _mean([r.get(f"{prefix}_room_r") for r in fills]),
        "avg_risk_atr": _mean([r.get(f"{prefix}_risk_atr") for r in fills]),
        "states": dict(sorted(Counter(
            str(r.get(f"{prefix}_state") or "NONE") for r in fills
        ).items())),
    }


def _m2_strict_funnel(rows):
    # Exact V4.4.2 M2 OPT gates, applied sequentially.
    stages = []
    pool = [r for r in rows if _m2_base(r)]
    stages.append(("terminal_m2", len(pool)))
    tests = [
        ("phase_early_or_mature", lambda r: _phase_ok(r)),
        ("score_ge_4", lambda r: int(r.get("v441_m2_confirm_score") or 0) >= 4),
        ("controlled_break", lambda r: int(r.get("v441_m2_controlled_break") or 0) == 1),
        ("retest_touched", lambda r: int(r.get("v441_m2_retest_touched") or 0) == 1),
        ("retest_rejection", lambda r: int(r.get("v441_m2_retest_rejection") or 0) == 1),
        ("entry_within_0_65_atr", lambda r: (
            _m2_location(r) is not None and _m2_location(r) <= 0.65
        )),
        ("break_body_le_1_10_atr", lambda r: (
            _num(r.get("v441_m2_break_body_atr")) is not None
            and _num(r.get("v441_m2_break_body_atr")) <= 1.10
        )),
        ("cost_le_0_20r", lambda r: (
            _num(r.get("v441_m2_cost_r")) is not None
            and _num(r.get("v441_m2_cost_r")) <= 0.20
        )),
        ("room_ge_2_50r", lambda r: (
            _num(r.get("v441_m2_room_r")) is not None
            and _num(r.get("v441_m2_room_r")) >= 2.50
        )),
    ]
    for name, fn in tests:
        pool = [r for r in pool if fn(r)]
        stages.append((name, len(pool)))
    return [{"stage": k, "count": v} for k, v in stages]


def _m2_individual_pass(rows):
    base = [r for r in rows if _m2_base(r)]
    return {
        "terminal_m2": len(base),
        "phase_early_or_mature": sum(_phase_ok(r) for r in base),
        "score_ge_3": sum(int(r.get("v441_m2_confirm_score") or 0) >= 3 for r in base),
        "score_ge_4": sum(int(r.get("v441_m2_confirm_score") or 0) >= 4 for r in base),
        "controlled_break": sum(int(r.get("v441_m2_controlled_break") or 0) == 1 for r in base),
        "retest_touched": sum(int(r.get("v441_m2_retest_touched") or 0) == 1 for r in base),
        "retest_rejection": sum(int(r.get("v441_m2_retest_rejection") or 0) == 1 for r in base),
        "acceptance_ge_2": sum(int(r.get("v441_m2_acceptance_bars") or 0) >= 2 for r in base),
        "entry_within_0_65_atr": sum(
            (_m2_location(r) is not None and _m2_location(r) <= 0.65) for r in base
        ),
        "entry_within_0_90_atr": sum(
            (_m2_location(r) is not None and _m2_location(r) <= 0.90) for r in base
        ),
        "break_body_le_1_10_atr": sum(
            _num(r.get("v441_m2_break_body_atr")) is not None
            and _num(r.get("v441_m2_break_body_atr")) <= 1.10
            for r in base
        ),
        "break_body_le_1_30_atr": sum(
            _num(r.get("v441_m2_break_body_atr")) is not None
            and _num(r.get("v441_m2_break_body_atr")) <= 1.30
            for r in base
        ),
        "cost_le_0_20r": sum(
            _num(r.get("v441_m2_cost_r")) is not None
            and _num(r.get("v441_m2_cost_r")) <= 0.20
            for r in base
        ),
        "cost_le_0_22r": sum(
            _num(r.get("v441_m2_cost_r")) is not None
            and _num(r.get("v441_m2_cost_r")) <= 0.22
            for r in base
        ),
        "room_ge_2_50r": sum(
            _num(r.get("v441_m2_room_r")) is not None
            and _num(r.get("v441_m2_room_r")) >= 2.50
            for r in base
        ),
    }


def _gate(metrics):
    checks = {
        "sample_fills_ge_15": int(metrics.get("fills") or 0) >= 15,
        "net_expectancy_gt_0": (
            metrics.get("net_expectancy_r") is not None
            and float(metrics["net_expectancy_r"]) > 0
        ),
        "profit_factor_gt_1_05": (
            metrics.get("profit_factor") is not None
            and float(metrics["profit_factor"]) > 1.05
        ),
    }
    return {"checks": checks, "pass": all(checks.values())}


def _summary(report):
    a = report["analysis"]
    full = a["full_60d"]
    unique = a["unique_96h"]
    lines = [
        "# Crypto Short V4.4.3 — 60d Episode + M2 Funnel Research",
        "",
        f"- Period: {report['period_start']} -> {report['period_end']}",
        f"- Symbols: {report['selected_symbol_count']}",
        f"- Integrity: {'PASS' if report['manifest_integrity']['ok'] else 'FAIL'}",
        f"- Errors: {len(report['errors'])}",
        "- Research window: 60 days. Underlying causal execution replay is unchanged.",
        "",
        "## Cohorts",
        "- M1_A: corrected strict V4.4 comparator inside M1 context only.",
        "- M1_B: unchanged V4.4.2 scored quality baseline.",
        "- M1_B_PLUS: both micro-BOS and bearish rejection, >=3R room, <=0.18R cost.",
        "- M2_BASE: all V4.4.1 SBC fills.",
        "- M2_BAL: controlled break + rejection OR multi-bar acceptance.",
        "",
        "| Cohort | Fills | Positive% | Stop% | TP1% | Gross R | Net R | PF | Avg Cost R | Avg Room R |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key, label in (
        ("M1_A", "M1 A strict"),
        ("M1_B", "M1 B baseline"),
        ("M1_B_PLUS", "M1 B+ episode"),
        ("M2_BASE", "M2 base EDGE"),
        ("M2_BAL", "M2 balanced EDGE"),
    ):
        x = full[key]
        lines.append(
            f"| {label} | {x['fills']} | {x['positive_net_pct']} | {x['stop_pct']} | "
            f"{x['tp1_hit_pct']} | {x['gross_expectancy_r']} | {x['net_expectancy_r']} | "
            f"{x['profit_factor']} | {x['avg_cost_r']} | {x['avg_room_r']} |"
        )
    lines += ["", "## Unique 96h episodes — primary decision table"]
    for key in ("M1_A", "M1_B", "M1_B_PLUS", "M2_BASE", "M2_BAL"):
        lines.append(f"- {key}: {unique[key]}")
    lines += [
        "",
        "## M2 exact V4.4.2 strict funnel",
        f"- {a['m2_strict_funnel']}",
        "",
        "## M2 individual gate pass counts",
        f"- {a['m2_individual_pass']}",
        "",
        f"- Unique gates: {a['gates']}",
        "- RESEARCH_ONLY. A 60d pass is not sufficient for live deployment.",
    ]
    return "\n".join(lines)


def merge_reports(reports):
    if not reports:
        raise RuntimeError("No V4.4.3 shard reports found")
    expected = max(int(r.get("shard_count") or 1) for r in reports)
    found = {int(r.get("shard_index")) for r in reports}
    if found != set(range(expected)):
        raise RuntimeError(f"Incomplete V4.4.3 shards: {sorted(found)}")
    ids = {str(r.get("manifest_id")) for r in reports}
    if len(ids) != 1:
        raise RuntimeError("V4.4.3 manifest mismatch")

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
        raise RuntimeError(f"V4.4.3 integrity failure: {integrity}")

    dedup = {}
    for row in raw:
        dedup.setdefault((row.get("symbol"), row.get("signal_time")), row)
    rows = sorted(
        dedup.values(),
        key=lambda r: (str(r.get("signal_time")), str(r.get("symbol"))),
    )
    _add_cross_section_and_phase(rows)

    m1a = [r for r in rows if _m1a(r)]
    m1b = [r for r in rows if _m1b(r)]
    m1bp = [r for r in rows if _m1bplus(r)]
    m2base = [r for r in rows if _m2_base(r)]
    m2bal = [r for r in rows if _m2_balanced(r)]

    cohorts = {
        "M1_A": (m1a, "v440"),
        "M1_B": (m1b, "v441_m1"),
        "M1_B_PLUS": (m1bp, "v441_m1"),
        "M2_BASE": (m2base, "v441_m2"),
        "M2_BAL": (m2bal, "v441_m2"),
    }
    full = {k: _metrics(v[0], v[1]) for k, v in cohorts.items()}
    unique = {k: _metrics(_unique(v[0]), v[1]) for k, v in cohorts.items()}
    gates = {k: _gate(unique[k]) for k in unique}

    analysis = {
        "counts": {
            "raw": len(rows),
            "m1_a_fills": len(m1a),
            "m1_b_fills": len(m1b),
            "m1_b_plus_fills": len(m1bp),
            "m2_base_fills": len(m2base),
            "m2_balanced_fills": len(m2bal),
        },
        "full_60d": full,
        "unique_96h": unique,
        "m2_strict_funnel": _m2_strict_funnel(rows),
        "m2_individual_pass": _m2_individual_pass(rows),
        "gates": gates,
        "research_status": "RESEARCH_ONLY",
        "fixed_parameter_run": True,
        "parameter_grid_searched": False,
    }

    return {
        "engine": "Crypto Short V4.4.3 60d Episode + M2 Funnel Research",
        "manifest_id": next(iter(ids)),
        "manifest": first.get("manifest"),
        "manifest_integrity": integrity,
        "period_start": first.get("period_start"),
        "period_end": first.get("period_end"),
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
    _write_json(os.path.join(OUTPUT_DIR, "v443_backtest.json"), report)
    _write_json(os.path.join(OUTPUT_DIR, "v443_analysis.json"), report["analysis"])
    _write_json(os.path.join(OUTPUT_DIR, "v443_manifest.json"), report["manifest"])
    fields = CSV_FIELDS + [
        "v428_trend_phase",
        "v428_structure_score",
        "v428_exhaustion_score",
        "v428_recovery_score",
        "v443_m2_entry_below_support_atr",
    ]
    _write_csv(
        os.path.join(OUTPUT_DIR, "v443_scored_candidates.csv"),
        report["trades"],
        fields=fields,
    )
    with open(os.path.join(OUTPUT_DIR, "v443_summary.md"), "w", encoding="utf-8") as f:
        f.write(_summary(report))

    print(json.dumps({
        "integrity": report["manifest_integrity"],
        "errors": len(report["errors"]),
        "analysis": report["analysis"],
    }, ensure_ascii=False, indent=2))
    return 0 if not report["errors"] else 2


if __name__ == "__main__":
    sys.exit(main())
