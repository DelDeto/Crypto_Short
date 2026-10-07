"""V4.4 rule-only merge and fixed 360d validation.

V4.4 deliberately avoids using the context ML score to decide whether the new
entry logic passes. The rule is evaluated on the same frozen opportunities,
with an older ~300d validation slice and the already-seen recent 60d slice.
"""
import json
import os
import sys
from collections import Counter
from glob import glob

import numpy as np
import pandas as pd

from .config import OUTPUT_DIR
from .v429_merge import _rule_fields
from .v440_config import V440_COOLDOWN_HOURS, V440_COST_BPS, V440_MIN_ROOM_R
from .v440_execution import TERMINAL_STATES
from .v440_main import CSV_FIELDS, _write_csv, _write_json


def _load(root):
    reports = []
    for path in sorted(
        glob(os.path.join(root, "**", "v440_backtest.json"), recursive=True)
    ):
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


def _unique(rows, marker):
    last = {}
    selected = []
    for row in sorted(
        rows, key=lambda r: (str(r.get("signal_time")), str(r.get("symbol")))
    ):
        symbol = str(row.get("symbol"))
        t = pd.Timestamp(row.get("signal_time"))
        previous = last.get(symbol)
        if (
            previous is not None
            and (t - previous) < pd.Timedelta(hours=int(V440_COOLDOWN_HOURS))
        ):
            row[marker] = 0
            continue
        row[marker] = 1
        last[symbol] = t
        selected.append(row)
    return selected


def _max_losing_streak(rows, key):
    streak = 0
    worst = 0
    observed = 0
    for row in sorted(
        rows, key=lambda r: (str(r.get("signal_time")), str(r.get("symbol")))
    ):
        v = _num(row.get(key))
        if v is None:
            continue
        observed += 1
        if v < 0:
            streak += 1
            worst = max(worst, streak)
        else:
            streak = 0
    return {"observed": observed, "max_losing_streak": worst}


def _profit_factor(values):
    vals = [x for x in (_num(v) for v in values) if x is not None]
    gains = sum(x for x in vals if x > 0)
    losses = -sum(x for x in vals if x < 0)
    if losses <= 0:
        return None if gains <= 0 else 999.0
    return round(gains / losses, 4)


def _v440_metrics(rows):
    states = Counter(str(r.get("v440_state") or "NONE") for r in rows)
    fills = [
        r for r in rows
        if r.get("v440_state") in TERMINAL_STATES
        and _num(r.get("v440_net_r")) is not None
    ]
    net = [float(r["v440_net_r"]) for r in fills]
    gross = [float(r["v440_gross_r"]) for r in fills]
    streak = _max_losing_streak(fills, "v440_net_r")
    return {
        "opportunities": len(rows),
        "filled": len(fills),
        "fill_rate_pct": _pct(len(fills), len(rows)),
        "positive_net": sum(x > 0 for x in net),
        "positive_net_pct": _pct(sum(x > 0 for x in net), len(net)),
        "stops": sum(r.get("v440_state") == "SL_FIRST" for r in fills),
        "stop_pct": _pct(
            sum(r.get("v440_state") == "SL_FIRST" for r in fills), len(fills)
        ),
        "tp1_hit": sum(int(r.get("v440_tp1_hit") or 0) for r in fills),
        "tp1_hit_pct": _pct(
            sum(int(r.get("v440_tp1_hit") or 0) for r in fills), len(fills)
        ),
        "tp2_demand": sum(r.get("v440_state") == "TP2_DEMAND" for r in fills),
        "tp2_demand_pct": _pct(
            sum(r.get("v440_state") == "TP2_DEMAND" for r in fills), len(fills)
        ),
        "ft_pass": sum(int(r.get("v440_ft_pass") or 0) for r in fills),
        "ft_pass_pct": _pct(
            sum(int(r.get("v440_ft_pass") or 0) for r in fills), len(fills)
        ),
        "ft_early_exit": sum(
            r.get("v440_state") in ("FT_EXIT", "FT_RECLAIM_EXIT")
            for r in fills
        ),
        "gross_expectancy_r_per_fill": _mean(gross),
        "net_expectancy_r_per_fill": _mean(net),
        "net_expectancy_r_per_opportunity": (
            round(sum(net) / len(rows), 5) if rows else None
        ),
        "total_net_r": round(sum(net), 5),
        "profit_factor": _profit_factor(net),
        "avg_room_r": _mean([r.get("v440_room_r") for r in fills]),
        "avg_risk_atr": _mean([r.get("v440_risk_atr") for r in fills]),
        "avg_break_body_atr": _mean(
            [r.get("v440_break_body_atr") for r in fills]
        ),
        "avg_liquidity_touches": _mean(
            [r.get("v440_liquidity_touches") for r in fills]
        ),
        "avg_cost_r": _mean([r.get("v440_cost_r") for r in fills]),
        "max_losing_streak": streak["max_losing_streak"],
        "states": dict(sorted(states.items())),
        "demand_sources": dict(sorted(Counter(
            str(r.get("v440_demand_source"))
            for r in fills if r.get("v440_demand_source")
        ).items())),
        "ft_states": dict(sorted(Counter(
            str(r.get("v440_ft_state"))
            for r in fills if r.get("v440_ft_state")
        ).items())),
    }


def _a2_metrics(rows):
    fills = [
        r for r in rows
        if r.get("v431_A2_state") in ("TP2R_FIRST", "SL_FIRST", "SL_SAME_BAR", "TIME_EXIT")
        and _num(r.get("v431_A2_net_r")) is not None
    ]
    net = [float(r["v431_A2_net_r"]) for r in fills]
    return {
        "opportunities": len(rows),
        "filled": len(fills),
        "fill_rate_pct": _pct(len(fills), len(rows)),
        "tp2r_first_pct": _pct(
            sum(r.get("v431_A2_state") == "TP2R_FIRST" for r in fills),
            len(fills),
        ),
        "stop_pct": _pct(
            sum(r.get("v431_A2_state") in ("SL_FIRST", "SL_SAME_BAR") for r in fills),
            len(fills),
        ),
        "net_expectancy_r_per_fill": _mean(net),
        "net_expectancy_r_per_opportunity": (
            round(sum(net) / len(rows), 5) if rows else None
        ),
        "profit_factor": _profit_factor(net),
        "total_net_r": round(sum(net), 5),
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
    return {
        "candidate": "V4.4_FIXED_STRUCTURAL_CONFIRMATION",
        "checks": checks,
        "pass": all(checks.values()),
    }


def _summary(report):
    a = report["analysis"]
    older = a["validation_split"]["older_300d"]
    recent = a["validation_split"]["recent_60d_seen"]
    unique = a["validation_split"]["older_300d_unique"]
    lines = [
        "# Crypto Short V4.4 — Structural Confirmation + Demand-Aware TP",
        "",
        f"- Period: {report['period_start']} -> {report['period_end']}",
        f"- Symbols: {report['selected_symbol_count']}",
        f"- Integrity: {'PASS' if report['manifest_integrity']['ok'] else 'FAIL'}",
        f"- Errors: {len(report['errors'])}",
        f"- Fee + slippage assumption: {V440_COST_BPS} bps round trip.",
        "- RESEARCH_ONLY: live V1 is unchanged until V4.4 passes long validation.",
        "",
        "## V4.4 logic",
        "1. Require strong upstream supply context.",
        "2. Require a repeated 15m buy-side liquidity pool known before the trigger.",
        "3. Require sweep + failed auction back below the pool.",
        "4. Require subsequent controlled bearish micro-BOS with body 0.70-1.00 ATR.",
        "5. Enter only at the next 15m open; no future best-price selection.",
        f"6. Freeze nearest meaningful 1h/4h demand and require >= {V440_MIN_ROOM_R}R room.",
        "7. TP1 = 2R on half size; TP2 = just before demand; BE on remainder after TP1.",
        "8. If immediate follow-through is absent/reclaimed in the first hour, exit causally.",
        "9. No C re-entry.",
        "",
        "## Same core opportunities: V4.3.1 A2 vs V4.4",
        "",
        "| Slice | Engine | Fill | Positive% | Stop% | Net R/fill | Net R/opp | PF |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for label, block in (
        ("Older ~300d VALIDATION", older),
        ("Recent 60d SEEN", recent),
        ("Older ~300d UNIQUE", unique),
    ):
        old = block["A2_baseline"]
        new = block["V4.4"]
        lines.append(
            f"| {label} | V4.3.1 A2 | {old['filled']}/{old['opportunities']} | - | "
            f"{old['stop_pct']} | {old['net_expectancy_r_per_fill']} | "
            f"{old['net_expectancy_r_per_opportunity']} | {old['profit_factor']} |"
        )
        lines.append(
            f"| {label} | V4.4 | {new['filled']}/{new['opportunities']} | "
            f"{new['positive_net_pct']} | {new['stop_pct']} | "
            f"{new['net_expectancy_r_per_fill']} | "
            f"{new['net_expectancy_r_per_opportunity']} | {new['profit_factor']} |"
        )

    lines += [
        "",
        "## V4.4 diagnostics",
        f"- Older validation TP1 hit%: {older['V4.4']['tp1_hit_pct']}",
        f"- Older validation demand TP2%: {older['V4.4']['tp2_demand_pct']}",
        f"- Older validation immediate follow-through pass%: {older['V4.4']['ft_pass_pct']}",
        f"- Older validation average room: {older['V4.4']['avg_room_r']}R",
        f"- Older validation max losing streak: {older['V4.4']['max_losing_streak']}",
        f"- Older validation demand sources: {older['V4.4']['demand_sources']}",
        f"- Older validation state funnel: {older['V4.4']['states']}",
        "",
        f"- Older raw gate: {a['validation_split']['older_gate']}",
        f"- Older unique gate: {a['validation_split']['older_unique_gate']}",
        f"- Research status: {a['research_status']}",
        "",
        "## Integrity controls",
        "- Liquidity pool uses only highs from candles closed before the sweep.",
        "- Sweep and BOS decisions use closed 15m candles; fill is next-bar open.",
        "- Demand is frozen from signal-time closed 1h/4h candles.",
        "- Room-to-demand is a hard gate before entry, not a post-trade label.",
        "- Immediate follow-through is implemented as a causal early-exit rule.",
        "- Same-bar initial SL/target collision is counted against the strategy.",
        "- No re-entry, martingale, stop widening, or future best-price optimisation.",
    ]
    return "\n".join(lines)


def _slice(rows):
    return {
        "V4.4": _v440_metrics(rows),
        "A2_baseline": _a2_metrics(rows),
    }


def merge_reports(reports):
    if not reports:
        raise RuntimeError("No V4.4 shard reports found")
    expected = max(int(r.get("shard_count") or 1) for r in reports)
    found = {int(r.get("shard_index")) for r in reports}
    if found != set(range(expected)):
        raise RuntimeError(f"Incomplete V4.4 shards: {sorted(found)}")

    ids = {str(r.get("manifest_id")) for r in reports}
    if len(ids) != 1:
        raise RuntimeError("V4.4 manifest mismatch")
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
        raise RuntimeError(f"V4.4 integrity failure: {integrity}")

    dedup = {}
    for row in raw:
        dedup.setdefault((row.get("symbol"), row.get("signal_time")), row)
    rows = sorted(
        dedup.values(),
        key=lambda r: (str(r.get("signal_time")), str(r.get("symbol"))),
    )

    core = []
    for row in rows:
        fields = _rule_fields(row)
        core_preconfirm = bool(fields[9])
        row["v440_core_preconfirm"] = int(core_preconfirm)
        if core_preconfirm:
            core.append(row)

    period_end_ts = pd.Timestamp(first.get("period_end"))
    if period_end_ts.tzinfo is None:
        period_end_ts = period_end_ts.tz_localize("UTC")
    split_cutoff = period_end_ts - pd.Timedelta(days=60)
    older = [
        r for r in core if pd.Timestamp(r.get("signal_time")) < split_cutoff
    ]
    recent = [
        r for r in core if pd.Timestamp(r.get("signal_time")) >= split_cutoff
    ]

    unique_core = _unique(list(core), "v440_unique_episode")
    older_unique = [
        r for r in unique_core
        if pd.Timestamp(r.get("signal_time")) < split_cutoff
    ]
    recent_unique = [
        r for r in unique_core
        if pd.Timestamp(r.get("signal_time")) >= split_cutoff
    ]

    older_block = _slice(older)
    recent_block = _slice(recent)
    older_unique_block = _slice(older_unique)
    recent_unique_block = _slice(recent_unique)
    older_gate = _gate(older_block["V4.4"])
    older_unique_gate = _gate(older_unique_block["V4.4"])
    research_status = (
        "VALIDATION_CANDIDATE"
        if older_gate["pass"] and older_unique_gate["pass"]
        else "RESEARCH_ONLY"
    )

    analysis = {
        "counts": {
            "raw": len(rows),
            "core_preconfirm": len(core),
            "unique_core": len(unique_core),
        },
        "validation_split": {
            "cutoff": split_cutoff.isoformat(),
            "older_300d": older_block,
            "recent_60d_seen": recent_block,
            "older_300d_unique": older_unique_block,
            "recent_60d_unique_seen": recent_unique_block,
            "older_gate": older_gate,
            "older_unique_gate": older_unique_gate,
        },
        "research_status": research_status,
        "fixed_parameter_run": True,
        "parameter_grid_searched": False,
    }

    return {
        "engine": "Crypto Short V4.4 Structural Confirmation Research",
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
    _write_json(os.path.join(OUTPUT_DIR, "v440_backtest.json"), report)
    _write_json(os.path.join(OUTPUT_DIR, "v440_analysis.json"), report["analysis"])
    _write_json(os.path.join(OUTPUT_DIR, "v440_manifest.json"), report["manifest"])
    _write_csv(
        os.path.join(OUTPUT_DIR, "v440_scored_candidates.csv"),
        report["trades"],
        fields=CSV_FIELDS + ["v440_core_preconfirm", "v440_unique_episode"],
    )
    with open(
        os.path.join(OUTPUT_DIR, "v440_summary.md"), "w", encoding="utf-8"
    ) as f:
        f.write(_summary(report))

    print(json.dumps({
        "integrity": report["manifest_integrity"],
        "errors": len(report["errors"]),
        "analysis": report["analysis"],
    }, ensure_ascii=False, indent=2))
    return 0 if not report["errors"] else 2


if __name__ == "__main__":
    sys.exit(main())
