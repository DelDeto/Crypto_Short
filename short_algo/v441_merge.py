"""V4.4.1 merge: validate M1 Liquidity Reversal and M2 SBC independently."""
import json
import os
import sys
from collections import Counter
from glob import glob

import numpy as np
import pandas as pd

from .config import OUTPUT_DIR
from .v428_merge import _add_cross_section_and_phase
from .v441_config import V441_COOLDOWN_HOURS, V441_COST_BPS, V441_MIN_ROOM_R
from .v441_execution import TERMINAL_STATES
from .v441_main import CSV_FIELDS, _write_csv, _write_json


def _load(root):
    reports = []
    for path in sorted(glob(os.path.join(root, "**", "v441_backtest.json"), recursive=True)):
        with open(path, "r", encoding="utf-8") as f:
            reports.append(json.load(f))
    return reports


def _num(value):
    try:
        x = float(value)
        return x if np.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _mean(values):
    vals = [x for x in (_num(v) for v in values) if x is not None]
    return round(float(np.mean(vals)), 5) if vals else None


def _pct(num, den):
    return round(100.0 * num / den, 2) if den else None


def _profit_factor(values):
    vals = [x for x in (_num(v) for v in values) if x is not None]
    gains = sum(x for x in vals if x > 0)
    losses = -sum(x for x in vals if x < 0)
    if losses <= 0:
        return None if gains <= 0 else 999.0
    return round(gains / losses, 4)


def _unique(rows, marker):
    last = {}
    selected = []
    for row in sorted(rows, key=lambda r: (str(r.get("signal_time")), str(r.get("symbol")))):
        symbol = str(row.get("symbol"))
        t = pd.Timestamp(row.get("signal_time"))
        previous = last.get(symbol)
        if previous is not None and (t - previous) < pd.Timedelta(hours=int(V441_COOLDOWN_HOURS)):
            row[marker] = 0
            continue
        row[marker] = 1
        last[symbol] = t
        selected.append(row)
    return selected


def _max_losing_streak(rows, key):
    streak = 0
    worst = 0
    for row in sorted(rows, key=lambda r: (str(r.get("signal_time")), str(r.get("symbol")))):
        value = _num(row.get(key))
        if value is None:
            continue
        if value < 0:
            streak += 1
            worst = max(worst, streak)
        else:
            streak = 0
    return worst


def _metrics(rows, prefix, context_key=None):
    opportunities = rows if context_key is None else [r for r in rows if int(r.get(context_key) or 0) == 1]
    state_key = f"{prefix}_state"
    net_key = f"{prefix}_net_r"
    gross_key = f"{prefix}_gross_r"
    fills = [
        r for r in opportunities
        if r.get(state_key) in TERMINAL_STATES and _num(r.get(net_key)) is not None
    ]
    net = [float(r[net_key]) for r in fills]
    gross = [float(r[gross_key]) for r in fills if _num(r.get(gross_key)) is not None]
    states = Counter(str(r.get(state_key) or "NONE") for r in opportunities)
    return {
        "opportunities": len(opportunities),
        "filled": len(fills),
        "fill_rate_pct": _pct(len(fills), len(opportunities)),
        "positive_net": sum(x > 0 for x in net),
        "positive_net_pct": _pct(sum(x > 0 for x in net), len(net)),
        "stops": sum(r.get(state_key) == "SL_FIRST" for r in fills),
        "stop_pct": _pct(sum(r.get(state_key) == "SL_FIRST" for r in fills), len(fills)),
        "tp1_hit": sum(int(r.get(f"{prefix}_tp1_hit") or 0) for r in fills),
        "tp1_hit_pct": _pct(sum(int(r.get(f"{prefix}_tp1_hit") or 0) for r in fills), len(fills)),
        "tp2_demand": sum(r.get(state_key) == "TP2_DEMAND" for r in fills),
        "tp2_demand_pct": _pct(sum(r.get(state_key) == "TP2_DEMAND" for r in fills), len(fills)),
        "ft_pass_pct": _pct(sum(int(r.get(f"{prefix}_ft_pass") or 0) for r in fills), len(fills)),
        "gross_expectancy_r_per_fill": _mean(gross),
        "net_expectancy_r_per_fill": _mean(net),
        "net_expectancy_r_per_opportunity": (
            round(sum(net) / len(opportunities), 5) if opportunities else None
        ),
        "profit_factor": _profit_factor(net),
        "total_net_r": round(sum(net), 5),
        "avg_room_r": _mean([r.get(f"{prefix}_room_r") for r in fills]),
        "avg_risk_atr": _mean([r.get(f"{prefix}_risk_atr") for r in fills]),
        "avg_confirm_score": _mean([r.get(f"{prefix}_confirm_score") for r in fills]),
        "max_losing_streak": _max_losing_streak(fills, net_key),
        "states": dict(sorted(states.items())),
        "ft_states": dict(sorted(Counter(
            str(r.get(f"{prefix}_ft_state"))
            for r in fills if r.get(f"{prefix}_ft_state")
        ).items())),
        "demand_sources": dict(sorted(Counter(
            str(r.get(f"{prefix}_demand_source"))
            for r in fills if r.get(f"{prefix}_demand_source")
        ).items())),
    }


def _strict_metrics(rows):
    eligible = [r for r in rows if int(r.get("v441_m1_context_ok") or 0) == 1]
    fills = [
        r for r in eligible
        if r.get("v440_state") in TERMINAL_STATES and _num(r.get("v440_net_r")) is not None
    ]
    net = [float(r["v440_net_r"]) for r in fills]
    return {
        "opportunities": len(eligible),
        "filled": len(fills),
        "fill_rate_pct": _pct(len(fills), len(eligible)),
        "positive_net_pct": _pct(sum(x > 0 for x in net), len(net)),
        "net_expectancy_r_per_fill": _mean(net),
        "net_expectancy_r_per_opportunity": round(sum(net) / len(eligible), 5) if eligible else None,
        "profit_factor": _profit_factor(net),
        "total_net_r": round(sum(net), 5),
        "states": dict(sorted(Counter(str(r.get("v440_state") or "NONE") for r in eligible).items())),
    }


def _gate(metrics):
    checks = {
        "sample_fills_ge_30": int(metrics.get("filled") or 0) >= 30,
        "net_expectancy_per_fill_gt_0": (
            metrics.get("net_expectancy_r_per_fill") is not None
            and float(metrics["net_expectancy_r_per_fill"]) > 0
        ),
        "net_expectancy_per_opportunity_gt_0": (
            metrics.get("net_expectancy_r_per_opportunity") is not None
            and float(metrics["net_expectancy_r_per_opportunity"]) > 0
        ),
        "profit_factor_gt_1_05": (
            metrics.get("profit_factor") is not None
            and float(metrics["profit_factor"]) > 1.05
        ),
    }
    return {"checks": checks, "pass": all(checks.values())}


def _slice(rows):
    return {
        "strict_V4.4_on_M1_context": _strict_metrics(rows),
        "M1_liquidity_reversal": _metrics(rows, "v441_m1", "v441_m1_context_ok"),
        "M2_support_breakdown": _metrics(rows, "v441_m2", "v441_m2_context_ok"),
    }


def _phase_counts(rows, context_key):
    c = Counter(
        str(r.get("v428_trend_phase") or "UNKNOWN")
        for r in rows if int(r.get(context_key) or 0) == 1
    )
    return dict(sorted(c.items()))


def _summary(report):
    a = report["analysis"]
    v = a["validation_split"]
    older = v["older_300d"]
    recent = v["recent_60d_seen"]
    old_u = v["older_300d_unique"]
    lines = [
        "# Crypto Short V4.4.1 — Dual Model Research",
        "",
        f"- Period: {report['period_start']} -> {report['period_end']}",
        f"- Symbols: {report['selected_symbol_count']}",
        f"- Integrity: {'PASS' if report['manifest_integrity']['ok'] else 'FAIL'}",
        f"- Errors: {len(report['errors'])}",
        f"- Fee + slippage: {V441_COST_BPS} bps round trip.",
        "- RESEARCH_ONLY. M1 and M2 are evaluated independently; no auto-blending into live V1.",
        "- V4.4 merge bug is fixed here: cross-sectional trend phase is reconstructed before analysis.",
        "",
        "## Models",
        "- M1 Liquidity Reversal: strong supply + real liquidity sweep are mandatory; post-sweep confirmation is scored instead of all-or-nothing.",
        f"- M1/M2 both retain a hard demand-room gate of >= {V441_MIN_ROOM_R}R.",
        "- M2 SBC (EDGE-like): bearish pressure + repeated structural 4H support + breakdown + failed reclaim/retest.",
        "- Immediate follow-through remains causal trade management, not a hindsight entry filter.",
        "",
        "## Older ~300d validation",
        "",
        "| Engine | Opportunity | Fill | Positive% | Stop% | TP1% | Net R/fill | Net R/opp | PF | Max loss streak |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key, label in (
        ("strict_V4.4_on_M1_context", "Strict V4.4 baseline"),
        ("M1_liquidity_reversal", "M1 Liquidity Reversal"),
        ("M2_support_breakdown", "M2 SBC / EDGE"),
    ):
        x = older[key]
        lines.append(
            f"| {label} | {x['opportunities']} | {x['filled']} | {x.get('positive_net_pct')} | "
            f"{x.get('stop_pct')} | {x.get('tp1_hit_pct')} | {x['net_expectancy_r_per_fill']} | "
            f"{x['net_expectancy_r_per_opportunity']} | {x['profit_factor']} | {x.get('max_losing_streak')} |"
        )

    lines += [
        "",
        "## Recent 60d seen (diagnostic only)",
        f"- M1: {recent['M1_liquidity_reversal']}",
        f"- M2: {recent['M2_support_breakdown']}",
        "",
        "## Independent-episode older validation",
        f"- M1: {old_u['M1_liquidity_reversal']}",
        f"- M2: {old_u['M2_support_breakdown']}",
        "",
        f"- M1 gate: {v['m1_older_unique_gate']}",
        f"- M2 gate: {v['m2_older_unique_gate']}",
        f"- Model status: {a['model_status']}",
        "",
        "## Context diagnostics",
        f"- M1 phase mix: {a['m1_phase_mix']}",
        f"- M2 phase mix: {a['m2_phase_mix']}",
        f"- Context overlap: {a['context_overlap']}",
        f"- Fill overlap: {a['fill_overlap']}",
        "",
        "## Integrity controls",
        "- All trigger decisions use closed 15m candles and fill only at the next 15m open.",
        "- M1 liquidity pool and M2 structural support exist before their trigger candle.",
        "- Demand is frozen from signal-time 1h/4h history.",
        "- Same-bar initial SL/target collision is conservative: SL wins.",
        "- No re-entry, martingale, stop widening, or future best-price selection.",
        "- Recent 60d cannot rescue a failed older-validation gate.",
    ]
    return "
".join(lines)


def merge_reports(reports):
    if not reports:
        raise RuntimeError("No V4.4.1 shard reports found")
    expected = max(int(r.get("shard_count") or 1) for r in reports)
    found = {int(r.get("shard_index")) for r in reports}
    if found != set(range(expected)):
        raise RuntimeError(f"Incomplete V4.4.1 shards: {sorted(found)}")

    ids = {str(r.get("manifest_id")) for r in reports}
    if len(ids) != 1:
        raise RuntimeError("V4.4.1 manifest mismatch")
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
        raise RuntimeError(f"V4.4.1 integrity failure: {integrity}")

    dedup = {}
    for row in raw:
        dedup.setdefault((row.get("symbol"), row.get("signal_time")), row)
    rows = sorted(dedup.values(), key=lambda r: (str(r.get("signal_time")), str(r.get("symbol"))))

    _add_cross_section_and_phase(rows)

    period_end_ts = pd.Timestamp(first.get("period_end"))
    if period_end_ts.tzinfo is None:
        period_end_ts = period_end_ts.tz_localize("UTC")
    split_cutoff = period_end_ts - pd.Timedelta(days=60)
    older = [r for r in rows if pd.Timestamp(r.get("signal_time")) < split_cutoff]
    recent = [r for r in rows if pd.Timestamp(r.get("signal_time")) >= split_cutoff]

    m1_rows = [r for r in rows if int(r.get("v441_m1_context_ok") or 0) == 1]
    m2_rows = [r for r in rows if int(r.get("v441_m2_context_ok") or 0) == 1]
    m1_unique = _unique(list(m1_rows), "v441_m1_unique_episode")
    m2_unique = _unique(list(m2_rows), "v441_m2_unique_episode")
    older_m1_unique = [r for r in m1_unique if pd.Timestamp(r.get("signal_time")) < split_cutoff]
    recent_m1_unique = [r for r in m1_unique if pd.Timestamp(r.get("signal_time")) >= split_cutoff]
    older_m2_unique = [r for r in m2_unique if pd.Timestamp(r.get("signal_time")) < split_cutoff]
    recent_m2_unique = [r for r in m2_unique if pd.Timestamp(r.get("signal_time")) >= split_cutoff]

    older_unique_union = older_m1_unique + [r for r in older_m2_unique if r not in older_m1_unique]
    recent_unique_union = recent_m1_unique + [r for r in recent_m2_unique if r not in recent_m1_unique]

    older_block = _slice(older)
    recent_block = _slice(recent)
    older_unique_block = _slice(older_unique_union)
    recent_unique_block = _slice(recent_unique_union)

    older_unique_block["M1_liquidity_reversal"] = _metrics(
        older_m1_unique, "v441_m1", "v441_m1_context_ok"
    )
    older_unique_block["M2_support_breakdown"] = _metrics(
        older_m2_unique, "v441_m2", "v441_m2_context_ok"
    )
    recent_unique_block["M1_liquidity_reversal"] = _metrics(
        recent_m1_unique, "v441_m1", "v441_m1_context_ok"
    )
    recent_unique_block["M2_support_breakdown"] = _metrics(
        recent_m2_unique, "v441_m2", "v441_m2_context_ok"
    )

    m1_gate = _gate(older_unique_block["M1_liquidity_reversal"])
    m2_gate = _gate(older_unique_block["M2_support_breakdown"])
    status = {
        "M1": "VALIDATION_CANDIDATE" if m1_gate["pass"] else "RESEARCH_ONLY",
        "M2": "VALIDATION_CANDIDATE" if m2_gate["pass"] else "RESEARCH_ONLY",
    }

    contexts_both = sum(
        int(r.get("v441_m1_context_ok") or 0) == 1 and int(r.get("v441_m2_context_ok") or 0) == 1
        for r in rows
    )
    fills_both = sum(
        _num(r.get("v441_m1_net_r")) is not None and _num(r.get("v441_m2_net_r")) is not None
        for r in rows
    )

    analysis = {
        "counts": {
            "raw": len(rows),
            "m1_contexts": len(m1_rows),
            "m2_contexts": len(m2_rows),
            "m1_unique_contexts": len(m1_unique),
            "m2_unique_contexts": len(m2_unique),
        },
        "validation_split": {
            "cutoff": split_cutoff.isoformat(),
            "older_300d": older_block,
            "recent_60d_seen": recent_block,
            "older_300d_unique": older_unique_block,
            "recent_60d_unique_seen": recent_unique_block,
            "m1_older_unique_gate": m1_gate,
            "m2_older_unique_gate": m2_gate,
        },
        "model_status": status,
        "m1_phase_mix": _phase_counts(rows, "v441_m1_context_ok"),
        "m2_phase_mix": _phase_counts(rows, "v441_m2_context_ok"),
        "context_overlap": contexts_both,
        "fill_overlap": fills_both,
        "fixed_parameter_run": True,
        "parameter_grid_searched": False,
    }

    return {
        "engine": "Crypto Short V4.4.1 Dual Model Research",
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
    _write_json(os.path.join(OUTPUT_DIR, "v441_backtest.json"), report)
    _write_json(os.path.join(OUTPUT_DIR, "v441_analysis.json"), report["analysis"])
    _write_json(os.path.join(OUTPUT_DIR, "v441_manifest.json"), report["manifest"])
    fields = CSV_FIELDS + [
        "v428_trend_phase", "v428_structure_score", "v428_exhaustion_score",
        "v428_recovery_score", "v441_m1_unique_episode", "v441_m2_unique_episode",
    ]
    _write_csv(
        os.path.join(OUTPUT_DIR, "v441_scored_candidates.csv"),
        report["trades"],
        fields=fields,
    )
    with open(os.path.join(OUTPUT_DIR, "v441_summary.md"), "w", encoding="utf-8") as f:
        f.write(_summary(report))

    print(json.dumps({
        "integrity": report["manifest_integrity"],
        "errors": len(report["errors"]),
        "analysis": report["analysis"],
    }, ensure_ascii=False, indent=2))
    return 0 if not report["errors"] else 2


if __name__ == "__main__":
    sys.exit(main())
