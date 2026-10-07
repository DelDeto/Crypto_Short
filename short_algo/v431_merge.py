"""V4.3.1 research-only merge: compare A0 vs causal 15m A1/A2/A3.

The 60d window has already been inspected in prior iterations, so this module
reports screening evidence only. It does not auto-promote any rule to live V1.
"""
import json
import os
import sys
from collections import Counter
from glob import glob

import numpy as np
import pandas as pd

from .config import OUTPUT_DIR
from .v428_merge import _add_cross_section_and_phase
from .v429_merge import _walk_forward, _auc, SCORED_FIELDS as V429_SCORED
from .v431_config import (
    V431_COOLDOWN_HOURS,
    V431_COST_BPS,
    V431_STRUCTURAL_ROOM_R,
)
from .v431_execution import PRIMARY_MODES, STOP_STATES, TERMINAL_STATES
from .v431_main import CSV_FIELDS, _write_csv, _write_json


EXTRA_SCORE_FIELDS = [
    f for f in V429_SCORED if f not in CSV_FIELDS
] + [
    "v431_core_preconfirm",
    "v431_unique_core_episode",
    "v431_unique_confirmed_episode",
    "v431_research_status",
]
SCORED_FIELDS = CSV_FIELDS + EXTRA_SCORE_FIELDS


def _load(root):
    reports = []
    for path in sorted(
        glob(os.path.join(root, "**", "v431_backtest.json"), recursive=True)
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
    nums = [x for x in (_num(v) for v in values) if x is not None]
    return round(float(np.mean(nums)), 5) if nums else None


def _pct(num, den):
    return round(100.0 * num / den, 2) if den else None


def _mode(rows, mode):
    p = f"v431_{mode}_"
    states = Counter(str(r.get(p + "state") or "NONE") for r in rows)
    filled = [
        r for r in rows
        if r.get(p + "state") in TERMINAL_STATES
        and _num(r.get(p + "net_r")) is not None
    ]
    wins = sum(r.get(p + "state") == "TP2R_FIRST" for r in filled)
    stops = sum(r.get(p + "state") in STOP_STATES for r in filled)
    net = [float(r[p + "net_r"]) for r in filled]
    gross = [float(r[p + "gross_r"]) for r in filled]
    ft = Counter(
        str(r.get(p + "ft_first_0_5r"))
        for r in filled
        if r.get(p + "ft_first_0_5r") is not None
    )
    room_pass = sum(int(r.get(p + "structural_room_pass") or 0) for r in filled)
    return {
        "opportunities": len(rows),
        "filled": len(filled),
        "fill_rate_pct": _pct(len(filled), len(rows)),
        "tp2r_first": wins,
        "tp2r_first_pct": _pct(wins, len(filled)),
        "stops": stops,
        "stop_pct": _pct(stops, len(filled)),
        "positive_net_pct": _pct(sum(x > 0 for x in net), len(net)),
        "gross_expectancy_r_per_fill": _mean(gross),
        "net_expectancy_r_per_fill": _mean(net),
        "net_expectancy_r_per_opportunity": (
            round(sum(net) / len(rows), 5) if rows else None
        ),
        "total_net_r": round(sum(net), 5),
        "avg_cost_r": _mean([r.get(p + "cost_r") for r in filled]),
        "avg_risk_pct": _mean([r.get(p + "risk_pct") for r in filled]),
        "avg_risk_atr": _mean([r.get(p + "risk_atr") for r in filled]),
        "avg_wait_15m_bars": _mean([r.get(p + "wait_bars") for r in filled]),
        "avg_entry_improvement_atr": _mean(
            [r.get(p + "entry_improvement_atr") for r in filled]
        ),
        "avg_entry_vs_reference_atr": _mean(
            [r.get(p + "entry_vs_reference_atr") for r in filled]
        ),
        "avg_structural_room_r": _mean(
            [r.get(p + "structural_room_r") for r in filled]
        ),
        "structural_room_pass_fills": room_pass,
        "structural_room_pass_pct_of_fills": _pct(room_pass, len(filled)),
        "followthrough_first_0_5r": dict(sorted(ft.items())),
        "avg_mfe_r": {
            "1h": _mean([r.get(p + "mfe_r_1h") for r in filled]),
            "4h": _mean([r.get(p + "mfe_r_4h") for r in filled]),
        },
        "avg_mae_r": {
            "1h": _mean([r.get(p + "mae_r_1h") for r in filled]),
            "4h": _mean([r.get(p + "mae_r_4h") for r in filled]),
        },
        "states": dict(sorted(states.items())),
    }


def _sequence(rows, primary):
    c_mode = primary + "C"
    p = f"v431_{primary}_"
    c = f"v431_{c_mode}_"
    seq_key = f"v431_{primary}_plus_C_net_r"
    primary_filled = [
        r for r in rows
        if r.get(p + "state") in TERMINAL_STATES
        and _num(r.get(p + "net_r")) is not None
    ]
    seq = [
        float(r[seq_key])
        for r in rows
        if _num(r.get(seq_key)) is not None
    ]
    stopped = [r for r in primary_filled if r.get(p + "state") in STOP_STATES]
    reentries = [
        r for r in stopped
        if r.get(c + "state") in TERMINAL_STATES
        and _num(r.get(c + "net_r")) is not None
    ]
    re_net = [float(r[c + "net_r"]) for r in reentries]
    return {
        "opportunities": len(rows),
        "primary_filled": len(primary_filled),
        "primary_stops": len(stopped),
        "reentry_filled": len(reentries),
        "reentry_rate_per_stop_pct": _pct(len(reentries), len(stopped)),
        "reentry_tp2r_pct": _pct(
            sum(r.get(c + "state") == "TP2R_FIRST" for r in reentries),
            len(reentries),
        ),
        "reentry_net_expectancy_r": _mean(re_net),
        "sequence_net_expectancy_r_per_primary_fill": _mean(seq),
        "sequence_net_expectancy_r_per_opportunity": (
            round(sum(seq) / len(rows), 5) if rows else None
        ),
        "sequence_total_net_r": round(sum(seq), 5),
        "sequence_positive_pct": _pct(sum(x > 0 for x in seq), len(seq)),
        "reentry_states": dict(sorted(Counter(
            str(r.get(c + "state") or "NONE") for r in stopped
        ).items())),
    }


def _bundle(rows):
    return {
        "opportunities": len(rows),
        "modes": {mode: _mode(rows, mode) for mode in PRIMARY_MODES},
        "sequences": {mode: _sequence(rows, mode) for mode in PRIMARY_MODES},
    }


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
            and (t - previous) < pd.Timedelta(hours=int(V431_COOLDOWN_HOURS))
        ):
            row[marker] = 0
            continue
        row[marker] = 1
        last[symbol] = t
        selected.append(row)
    return selected


def _screening_leader(bundle):
    eligible = []
    for mode in PRIMARY_MODES:
        primary = bundle["modes"][mode]
        seq = bundle["sequences"][mode]
        score = seq.get("sequence_net_expectancy_r_per_opportunity")
        if (
            primary.get("filled", 0) >= 5
            and score is not None
        ):
            eligible.append((float(score), mode))
    if not eligible:
        return None
    eligible.sort(reverse=True)
    return {
        "mode": eligible[0][1],
        "sequence_net_expectancy_r_per_opportunity": round(eligible[0][0], 5),
        "note": "screening only; same 60d slice has been inspected before",
    }


def _summary(report):
    a = report["analysis"]
    lines = [
        "# Crypto Short V4.3.1 — 15m Micro Entry Timing",
        "",
        f"- Period: {report['period_start']} → {report['period_end']}",
        f"- Symbols: {report['selected_symbol_count']}",
        f"- Integrity: {'PASS' if report['manifest_integrity']['ok'] else 'FAIL'}",
        f"- Errors: {len(report['errors'])}",
        f"- Assumed round-trip fee + slippage: {V431_COST_BPS} bps.",
        "- Fixed thresholds only; no grid search in this run.",
        "- RESEARCH_ONLY. Live V1 is not modified.",
        "",
        "## Opportunity funnel",
        f"- Core EARLY pre-confirm setup: {a['counts']['core_preconfirm']}",
        f"- Core + old 1H confirmation: {a['counts']['core_confirmed']}",
        f"- Core with structural support known: {a['counts']['core_structural_known']}",
        f"- Independent core episodes ({V431_COOLDOWN_HOURS}h/symbol): {a['counts']['unique_core']}",
        "",
        "## Same core opportunities — primary entry",
        "",
        "| Mode | Logic | Fill | TP2/fill | Stop/fill | Net Exp/fill | Net Exp/opportunity | Entry improvement ATR | Cost R |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    labels = {
        "A0": "Old 1H-confirm baseline",
        "A1": "15m rejection",
        "A2": "15m liquidity sweep",
        "A3": "15m rejection + micro BOS",
    }
    core = a["core"]
    for mode in PRIMARY_MODES:
        x = core["modes"][mode]
        lines.append(
            f"| {mode} | {labels[mode]} | {x['filled']}/{x['opportunities']} | "
            f"{x['tp2r_first_pct']} | {x['stop_pct']} | "
            f"{x['net_expectancy_r_per_fill']} | "
            f"{x['net_expectancy_r_per_opportunity']} | "
            f"{x['avg_entry_improvement_atr']} | {x['avg_cost_r']} |"
        )

    lines += [
        "",
        "## Primary + one conditional C re-entry",
        "",
        "| Sequence | Primary fills | Stops | Re-entry fills | Re-entry TP2 | Net Exp/opportunity | Positive sequence |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for mode in PRIMARY_MODES:
        x = core["sequences"][mode]
        lines.append(
            f"| {mode}+C | {x['primary_filled']} | {x['primary_stops']} | "
            f"{x['reentry_filled']} | {x['reentry_tp2r_pct']} | "
            f"{x['sequence_net_expectancy_r_per_opportunity']} | "
            f"{x['sequence_positive_pct']} |"
        )

    lines += [
        "",
        "## Controls",
        "- A1/A2/A3 use only closed 15m candles and fill at the next 15m open.",
        "- No-chase rejects entries more than the fixed ATR distance below the zone.",
        "- Micro stops use actual trigger swing high + buffer, then enforce a minimum risk.",
        "- Cost/R > fixed cap is rejected; a tiny stop cannot manufacture attractive RR.",
        "- Same-bar SL+TP is counted as SL.",
        "- Structural support is frozen from information available at signal time.",
        f"- Structural-room screen is {V431_STRUCTURAL_ROOM_R}R and is reported per actual entry/stop.",
        "- C is one re-entry maximum and is allowed only after the primary actually stops.",
        "- Missing 15m bars censor the trade instead of silently skipping time.",
        "- Current-turnover frozen universe has survivorship/tradability bias.",
        "- This 60d period is not an untouched holdout; results are for entry-rule screening.",
        "",
        f"Screening leader: {a.get('screening_leader')}",
    ]
    return "\n".join(lines)


def merge_reports(reports):
    if not reports:
        raise RuntimeError("No V4.3.1 shard reports found")
    expected = max(int(r.get("shard_count") or 1) for r in reports)
    found = {int(r.get("shard_index")) for r in reports}
    if found != set(range(expected)):
        raise RuntimeError(f"Incomplete V4.3.1 shards: {sorted(found)}")

    ids = {str(r.get("manifest_id")) for r in reports}
    if len(ids) != 1:
        raise RuntimeError("V4.3.1 manifest mismatch")
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
        raise RuntimeError(f"V4.3.1 integrity failure: {integrity}")

    dedup = {}
    for row in raw:
        dedup.setdefault((row.get("symbol"), row.get("signal_time")), row)
    rows = sorted(
        dedup.values(),
        key=lambda r: (str(r.get("signal_time")), str(r.get("symbol"))),
    )
    _add_cross_section_and_phase(rows)
    scored, folds, model_meta = _walk_forward(rows)

    for row in scored:
        core = int(row.get("v429_core_preconfirm") or 0)
        row["v431_core_preconfirm"] = core
        row["v431_unique_core_episode"] = 0
        row["v431_unique_confirmed_episode"] = 0
        row["v431_research_status"] = (
            "MICRO_ENTRY_RESEARCH" if core else "RESEARCH_WATCH"
        )

    core = [r for r in scored if int(r.get("v431_core_preconfirm") or 0) == 1]
    core_confirmed = [
        r for r in core if int(r.get("v428_entry_confirmed") or 0) == 1
    ]
    core_structural = [
        r for r in core if r.get("v430_support_structural") is not None
    ]
    unique_core = _unique(core, "v431_unique_core_episode")
    unique_confirmed = _unique(
        core_confirmed, "v431_unique_confirmed_episode"
    )

    counts_by_time = Counter(str(r.get("signal_time")) for r in scored)
    core_bundle = _bundle(core)
    analysis = {
        "raw_count": len(rows),
        "oos_count": len(scored),
        "median_coins_per_timestamp": (
            round(float(np.median(list(counts_by_time.values()))), 2)
            if counts_by_time else None
        ),
        "counts": {
            "core_preconfirm": len(core),
            "core_confirmed": len(core_confirmed),
            "core_structural_known": len(core_structural),
            "unique_core": len(unique_core),
            "unique_confirmed": len(unique_confirmed),
        },
        "core": core_bundle,
        "core_confirmed_same_opportunity": _bundle(core_confirmed),
        "core_structural_known": _bundle(core_structural),
        "unique_core": _bundle(unique_core),
        "unique_confirmed": _bundle(unique_confirmed),
        "screening_leader": _screening_leader(core_bundle),
        "oos_auc_context_only": {
            "4h": _auc(scored, "p_4h_lower", "y_4h_lower"),
            "12h": _auc(scored, "p_12h_lower", "y_12h_lower"),
            "24h": _auc(scored, "p_24h_lower", "y_24h_lower"),
            "reversal": _auc(
                scored, "p_reversal_after_short", "y_reversal_after_short"
            ),
            "confirmed2r": _auc(
                scored, "p_confirmed_2r", "y_confirmed_2r_success"
            ),
        },
        "folds": folds,
        "fixed_parameter_run": True,
        "parameter_grid_searched": False,
    }
    return {
        "engine": "Crypto Short V4.3.1 15m Micro Entry Research",
        "manifest_id": next(iter(ids)),
        "manifest": first.get("manifest"),
        "manifest_integrity": integrity,
        "period_start": first.get("period_start"),
        "period_end": first.get("period_end"),
        "days": first.get("days"),
        "selected_symbols": sorted(unique_symbols),
        "selected_symbol_count": len(unique_symbols),
        "analysis": analysis,
        "model_meta": model_meta,
        "trades": scored,
        "errors": errors,
    }


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "shard_outputs"
    report = merge_reports(_load(root))
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR, "v431_backtest.json"), report)
    _write_json(os.path.join(OUTPUT_DIR, "v431_analysis.json"), report["analysis"])
    _write_json(os.path.join(OUTPUT_DIR, "v431_model_meta.json"), report["model_meta"])
    _write_json(os.path.join(OUTPUT_DIR, "v431_manifest.json"), report["manifest"])
    _write_csv(
        os.path.join(OUTPUT_DIR, "v431_scored_candidates.csv"),
        report["trades"],
        fields=SCORED_FIELDS,
    )
    with open(
        os.path.join(OUTPUT_DIR, "v431_summary.md"), "w", encoding="utf-8"
    ) as f:
        f.write(_summary(report))

    a = report["analysis"]
    print(json.dumps({
        "integrity": report["manifest_integrity"],
        "errors": len(report["errors"]),
        "counts": a["counts"],
        "screening_leader": a["screening_leader"],
        "core_modes": a["core"]["modes"],
        "core_sequences": a["core"]["sequences"],
        "confirmed_same_opportunity": a["core_confirmed_same_opportunity"],
        "unique_core": a["unique_core"],
        "oos_auc_context_only": a["oos_auc_context_only"],
    }, ensure_ascii=False, indent=2))
    return 0 if not report["errors"] else 2


if __name__ == "__main__":
    sys.exit(main())
