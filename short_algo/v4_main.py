import csv
import json
import os
import sys

from .config import OUTPUT_DIR
from .v4_backtest import run_v4_backtest


def _write_json(path, payload):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)


def _write_trades_csv(path, trades):
    fields = [
        "manifest_id", "symbol", "signal_time", "exit_time", "v3_engine",
        "v3_score", "v3_projected_cost_r", "v4_regime_key",
        "v4_risk_state", "v4_trend_state", "v4_vol_state",
        "v4_phase", "v4_fold", "v4_probability", "v4_expected_r",
        "v4_status", "v4_engine_state", "v4_regime_state",
        "v4_reject_reason", "v4_ranked", "v4_cluster", "v4_market_rank",
        "entry", "stop", "stop_pct", "tp1", "tp2", "runner",
        "support_room_r", "outcome", "gross_r", "cost_r", "realized_r",
        "terminal_close", "mae_r", "mfe_r", "bars_to_outcome",
        "outcome_bar_minutes",
    ]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for trade in trades:
            writer.writerow({key: trade.get(key) for key in fields})


def _fmt(value, decimals=3):
    if value is None:
        return "-"
    return f"{float(value):.{decimals}f}"


def _summary_markdown(report):
    if "calibration" not in report:
        return "\n".join([
            "# Crypto Short V4 — Raw Candidate Shard",
            "",
            f"- Manifest: {report.get('manifest_id')}",
            f"- Period: {report.get('period_start')} → {report.get('period_end')}",
            f"- Shard: {int(report.get('shard_index', 0)) + 1}/{report.get('shard_count')}",
            f"- Symbols in shard: {report.get('selected_symbol_count', 0)}",
            f"- Raw rule candidates: {len(report.get('trades') or [])}",
            f"- Errors: {len(report.get('errors') or [])}",
            "",
            "Meta-label fitting is intentionally deferred until all frozen shards merge.",
        ])

    cal = report.get("calibration") or {}
    entry = cal.get("entry_ready") or {}
    holdout = cal.get("final_holdout_entry_ready") or {}
    ranked = cal.get("ranked_portfolio") or {}
    portfolio = report.get("v4_portfolio") or {}
    integrity = report.get("manifest_integrity") or {}
    promotion = report.get("promotion_gate") or {}
    wf = report.get("walk_forward") or {}

    lines = [
        "# Crypto Short V4 — Probability-Driven Validation",
        "",
        f"- Manifest: {report.get('manifest_id')}",
        f"- Period: {report.get('period_start')} → {report.get('period_end')}",
        f"- Frozen symbols: {report.get('selected_symbol_count')}",
        f"- Manifest integrity: {'PASS' if integrity.get('ok') else 'FAIL'}",
        f"- Raw rule candidates: {(cal.get('all_raw_candidates') or {}).get('signals', 0)}",
        f"- Scored OOS candidates: {(cal.get('all_scored_candidates') or {}).get('signals', 0)}",
        f"- Warm-up candidates intentionally unscored: {wf.get('unscored_warmup_candidates', 0)}",
        "",
        "## V4 ENTRY_READY — walk-forward + holdout",
        f"- Signals: {entry.get('signals', 0)}",
        f"- Net profitable rate: {_fmt(entry.get('net_profitable_rate_pct'), 2)}%",
        f"- Expectancy: {_fmt(entry.get('expectancy_r'))}R",
        f"- Profit factor: {_fmt(entry.get('profit_factor'))}",
        f"- Avg predicted Expected R: {_fmt(entry.get('avg_predicted_expected_r'))}R",
        f"- Brier score: {_fmt(entry.get('brier_score'), 5)}",
        "",
        "## Final untouched holdout",
        f"- ENTRY_READY signals: {holdout.get('signals', 0)}",
        f"- Net profitable rate: {_fmt(holdout.get('net_profitable_rate_pct'), 2)}%",
        f"- Expectancy: {_fmt(holdout.get('expectancy_r'))}R",
        f"- Profit factor: {_fmt(holdout.get('profit_factor'))}",
        f"- Avg predicted Expected R: {_fmt(holdout.get('avg_predicted_expected_r'))}R",
        "",
        "## Expected-R ranked portfolio",
        f"- Trades: {ranked.get('signals', 0)}",
        f"- Expectancy: {_fmt(ranked.get('expectancy_r'))}R",
        f"- Profit factor: {_fmt(ranked.get('profit_factor'))}",
        f"- Portfolio start: {_fmt(portfolio.get('starting_equity'), 2)}",
        f"- Portfolio end: {_fmt(portfolio.get('ending_equity'), 2)}",
        f"- Portfolio return: {_fmt(portfolio.get('return_pct'), 2)}%",
        f"- Portfolio max DD: {_fmt(portfolio.get('max_drawdown_pct'), 2)}%",
        "",
        "## Engine performance after V4 meta gate",
        "",
        "| Engine | Signals | Win % | Expectancy R | PF | Avg predicted ER |",
        "|---|---:|---:|---:|---:|---:|",
    ]

    for engine, stats in (cal.get("by_engine") or {}).items():
        lines.append(
            "| " + " | ".join([
                str(engine),
                str(stats.get("signals", 0)),
                _fmt(stats.get("net_profitable_rate_pct"), 2),
                _fmt(stats.get("expectancy_r")),
                _fmt(stats.get("profit_factor")),
                _fmt(stats.get("avg_predicted_expected_r")),
            ]) + " |"
        )

    lines += [
        "",
        "## Promotion gate",
        f"- Decision: **{promotion.get('decision', 'RESEARCH_ONLY')}**",
    ]
    for check, passed in (promotion.get("checks") or {}).items():
        lines.append(f"- {check}: {'PASS' if passed else 'FAIL'}")

    lines += [
        "",
        "## V4 methodology",
        "- Rule engines generate candidates; they no longer make the final allocation decision.",
        "- A frozen manifest fixes symbols and the exact historical period before sharding.",
        "- Meta-label probability is trained only on prior data with a 72h embargo.",
        "- Expected R uses the training window's realized average winner/loss magnitude after costs.",
        "- Engines and engine×regime combinations auto-demote to SHADOW when their training edge is not positive.",
        "- Final holdout outcomes are never used to fit the model that scores that holdout.",
        "- Portfolio ranking uses out-of-sample Expected R rather than hand-built rule score.",
        "",
    ]
    return "\n".join(lines)


def main():
    report = run_v4_backtest()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR, "v4_backtest.json"), report)
    _write_trades_csv(os.path.join(OUTPUT_DIR, "v4_trades.csv"), report.get("trades") or [])
    with open(os.path.join(OUTPUT_DIR, "v4_summary.md"), "w", encoding="utf-8") as handle:
        handle.write(_summary_markdown(report))

    print(json.dumps({
        "manifest_id": report.get("manifest_id"),
        "shard_index": report.get("shard_index"),
        "shard_count": report.get("shard_count"),
        "symbols": report.get("selected_symbol_count"),
        "candidates": len(report.get("trades") or []),
        "errors": len(report.get("errors") or []),
    }, ensure_ascii=False, indent=2))
    return 0 if report.get("selected_symbol_count", 0) > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
