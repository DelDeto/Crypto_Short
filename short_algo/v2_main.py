import csv
import json
import os
import sys

from .backtest import run_backtest
from .config import OUTPUT_DIR


def _write_json(path, payload):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)


def _write_trades_csv(path, trades):
    fields = [
        "symbol", "signal_time", "exit_time", "strategy_family", "model",
        "top_gainer_context", "status", "v21_status", "v21_priority",
        "v22_status", "v22_priority", "v22_score", "v22_ranked",
        "v22_market_rank", "score", "return_24h_pct", "entry", "stop", "stop_pct", "tp1",
        "tp2", "runner", "support_room_r", "supply_distance_atr",
        "outcome", "gross_r", "cost_r", "realized_r", "terminal_close",
        "mae_r", "mfe_r", "bars_to_outcome", "outcome_bar_minutes",
        "ambiguous_same_bar", "tp2_touched", "runner_touched",
    ]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for trade in trades:
            writer.writerow({key: trade.get(key) for key in fields})


def _fmt(value, decimals=2):
    if value is None:
        return "-"
    return f"{float(value):.{decimals}f}"


def _summary_markdown(report):
    cal = report.get("calibration") or {}
    overall = cal.get("overall") or {}
    entry_ready = cal.get("entry_ready") or {}
    v21_entry_ready = cal.get("v21_entry_ready") or {}
    liquidity = cal.get("liquidity_reversal") or {}
    liquidity_top = cal.get("liquidity_reversal_top_gainer") or {}
    v22_entry = cal.get("v22_entry_ready") or {}
    v22_top = cal.get("v22_top_gainer_entry_ready") or {}
    v22_ranked = cal.get("v22_ranked_portfolio") or {}
    baseline = cal.get("bollinger_baseline") or {}
    equity = report.get("equity_sequence") or {}
    v21_equity = report.get("v21_equity_sequence") or {}
    v22_equity = report.get("v22_equity_sequence") or {}
    v22_ranked_equity = report.get("v22_ranked_equity_sequence") or {}
    portfolio = report.get("v22_portfolio") or {}
    walk_forward = report.get("v22_walk_forward") or {}
    baseline_equity = report.get("baseline_equity_sequence") or {}
    universe_audit = ((report.get("selection_meta") or {}).get("universe_audit") or {})
    excluded_non_crypto = universe_audit.get("excluded_non_crypto_symbols") or []

    lines = [
        "# Crypto Short Scanner V2.2.1 — Crypto-only Validation",
        "",
        f"- Period: {report.get('period_start')} → {report.get('period_end')}",
        f"- Days: {report.get('days')}",
        f"- Symbols: {report.get('selected_symbol_count')}",
        f"- Crypto contracts available: {universe_audit.get('crypto_contracts', '-')}",
        f"- Non-crypto contracts excluded: {universe_audit.get('excluded_non_crypto_count', 0)}",
        f"- Excluded non-crypto symbols: {', '.join(excluded_non_crypto) if excluded_non_crypto else '-'}",
        "### Research candidates (WATCH+)",
        f"- Candidate signals: {overall.get('signals', 0)}",
        f"- Resolved candidates: {overall.get('resolved', 0)}",
        f"- Candidate win rate @ +2R before -1R: {_fmt(overall.get('win_rate_pct'))}%",
        f"- Candidate expectancy: {_fmt(overall.get('expectancy_r'), 3)}R / resolved signal",
        f"- Candidate profit factor: {_fmt(overall.get('profit_factor'), 3)}",
        "",
        "### V1 execution gate (comparison only)",
        f"- V1 ENTRY_READY signals: {entry_ready.get('signals', 0)}",
        f"- V1 ENTRY_READY win rate: {_fmt(entry_ready.get('win_rate_pct'))}%",
        f"- V1 ENTRY_READY expectancy: {_fmt(entry_ready.get('expectancy_r'), 3)}R",
        f"- V1 ENTRY_READY PF: {_fmt(entry_ready.get('profit_factor'), 3)}",
        "",
        "### V2.1 model-specific execution gate",
        f"- V2.1 ENTRY_READY signals: {v21_entry_ready.get('signals', 0)}",
        f"- V2.1 ENTRY_READY win rate: {_fmt(v21_entry_ready.get('win_rate_pct'))}%",
        f"- V2.1 ENTRY_READY expectancy: {_fmt(v21_entry_ready.get('expectancy_r'), 3)}R",
        f"- V2.1 ENTRY_READY PF: {_fmt(v21_entry_ready.get('profit_factor'), 3)}",
        f"- V2.1 net sequence: {_fmt(v21_equity.get('net_r'), 2)}R",
        f"- V2.1 max drawdown: {_fmt(v21_equity.get('max_drawdown_r'), 2)}R",
        "",
        "### Liquidity Reversal focus",
        f"- All Liquidity Reversal expectancy: {_fmt(liquidity.get('expectancy_r'), 3)}R | PF {_fmt(liquidity.get('profit_factor'), 3)}",
        f"- Top-gainer Liquidity Reversal expectancy: {_fmt(liquidity_top.get('expectancy_r'), 3)}R | PF {_fmt(liquidity_top.get('profit_factor'), 3)}",
        "",
        "### V2.2 reversal gate",
        f"- V2.2 ENTRY_READY signals: {v22_entry.get('signals', 0)}",
        f"- V2.2 ENTRY_READY win rate: {_fmt(v22_entry.get('win_rate_pct'))}%",
        f"- V2.2 ENTRY_READY expectancy: {_fmt(v22_entry.get('expectancy_r'), 3)}R",
        f"- V2.2 ENTRY_READY PF: {_fmt(v22_entry.get('profit_factor'), 3)}",
        f"- V2.2 raw net sequence: {_fmt(v22_equity.get('net_r'), 2)}R",
        f"- V2.2 top-gainer expectancy: {_fmt(v22_top.get('expectancy_r'), 3)}R | PF {_fmt(v22_top.get('profit_factor'), 3)}",
        "",
        "### V2.2 ranked portfolio",
        f"- Ranked trades: {v22_ranked.get('signals', 0)}",
        f"- Ranked win rate: {_fmt(v22_ranked.get('win_rate_pct'))}%",
        f"- Ranked expectancy: {_fmt(v22_ranked.get('expectancy_r'), 3)}R",
        f"- Ranked PF: {_fmt(v22_ranked.get('profit_factor'), 3)}",
        f"- Ranked net R: {_fmt(v22_ranked_equity.get('net_r'), 2)}R",
        f"- Ranked max drawdown: {_fmt(v22_ranked_equity.get('max_drawdown_r'), 2)}R",
        f"- Portfolio start: {_fmt(portfolio.get('starting_equity'), 2)}",
        f"- Portfolio end: {_fmt(portfolio.get('ending_equity'), 2)}",
        f"- Portfolio return: {_fmt(portfolio.get('return_pct'), 2)}%",
        f"- Portfolio max DD: {_fmt(portfolio.get('max_drawdown_pct'), 2)}%",
        f"- Walk-forward test signals: {walk_forward.get('aggregate_test_signals', 0)}",
        f"- Walk-forward test expectancy: {_fmt(walk_forward.get('aggregate_test_expectancy_r'), 3)}R",
        "",
        "### Bollinger baseline",
        f"- Baseline signals: {baseline.get('signals', 0)}",
        f"- Baseline expectancy: {_fmt(baseline.get('expectancy_r'), 3)}R",
        f"- Baseline PF: {_fmt(baseline.get('profit_factor'), 3)}",
        f"- Baseline net sequence: {_fmt(baseline_equity.get('net_r'), 2)}R",
        "",
        f"- Core candidate net sequence: {_fmt(equity.get('net_r'), 2)}R",
        f"- Core candidate max drawdown: {_fmt(equity.get('max_drawdown_r'), 2)}R",
        "",
        "## Model comparison",
        "",
        "| Model | Signals | Resolved | Win % | Expectancy R | PF | Avg MAE R | Avg MFE R | Recommendation |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]

    for model, stats in (cal.get("by_model") or {}).items():
        rec = (stats.get("recommendation") or {}).get("action", "-")
        lines.append(
            "| " + " | ".join([
                str(model),
                str(stats.get("signals", 0)),
                str(stats.get("resolved", 0)),
                _fmt(stats.get("win_rate_pct")),
                _fmt(stats.get("expectancy_r"), 3),
                _fmt(stats.get("profit_factor"), 3),
                _fmt(stats.get("avg_mae_r"), 3),
                _fmt(stats.get("avg_mfe_r"), 3),
                rec,
            ]) + " |"
        )

    lines += [
        "",
        "## Score calibration",
        "",
        "| Score bin | Signals | Resolved | Win % | Expectancy R | PF |",
        "|---|---:|---:|---:|---:|---:|",
    ]

    for score_bin, stats in (cal.get("by_score_bin") or {}).items():
        lines.append(
            "| " + " | ".join([
                str(score_bin),
                str(stats.get("signals", 0)),
                str(stats.get("resolved", 0)),
                _fmt(stats.get("win_rate_pct")),
                _fmt(stats.get("expectancy_r"), 3),
                _fmt(stats.get("profit_factor"), 3),
            ]) + " |"
        )

    lines += [
        "",
        "## V2.2 score calibration",
        "",
        "| V2.2 score | Signals | Win % | Expectancy R | PF |",
        "|---|---:|---:|---:|---:|",
    ]

    for score_bin, stats in (cal.get("by_v22_score_bin") or {}).items():
        lines.append(
            "| " + " | ".join([
                str(score_bin),
                str(stats.get("signals", 0)),
                _fmt(stats.get("win_rate_pct")),
                _fmt(stats.get("expectancy_r"), 3),
                _fmt(stats.get("profit_factor"), 3),
            ]) + " |"
        )

    lines += [
        "",
        "## Method notes",
        "",
        "- No future candle is used to build a signal.",
        "- V2.2.1 keeps V2.2 strategy logic unchanged and validates it on a crypto-only contract cohort.",
        "- V2.2 uses 4H/1H for context and fully closed 15m candles for entry confirmation.",
        "- V2.2 adds ATR/Bollinger/VWAP overextension and a timestamp-aligned BTC risk-on filter.",
        "- Walk-forward varies only the V2.2 score threshold; 15m confirmation, location, risk and BTC-regime hard gates remain fixed.",
        "- Whole-market ranking is applied only after all shards merge; max concurrent positions are enforced in portfolio simulation.",
        "- 4H candles must be fully closed before the 1H signal timestamp.",
        "- Primary bracket outcome remains +2R before -1R.",
        "- If neither TP1 nor SL hits within the configured horizon, the trade exits at the final horizon close.",
        "- Fee and slippage assumptions are deducted from every realized R result.",
        "- Signals too close to the end of the historical window are excluded so each signal has a complete forward horizon.",
        "- If SL and TP1 both touch inside the same 1H candle, the trade is counted as a loss.",
        "- Historical funding/spread/turnover are not substituted with today's values.",
        "- Current-contract/current-turnover symbol selection can introduce survivorship/selection bias; use explicit symbol sets for stricter research.",
        "- Calibration recommendations do not automatically change live scanner weights.",
        "",
    ]
    return "\n".join(lines)


def main():
    report = run_backtest()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    report_path = os.path.join(OUTPUT_DIR, "v2_backtest.json")
    trades_path = os.path.join(OUTPUT_DIR, "v2_trades.csv")
    calibration_path = os.path.join(OUTPUT_DIR, "v2_calibration.json")
    summary_path = os.path.join(OUTPUT_DIR, "v2_summary.md")

    _write_json(report_path, report)
    _write_trades_csv(trades_path, report.get("trades") or [])
    _write_json(calibration_path, report.get("calibration") or {})
    with open(summary_path, "w", encoding="utf-8") as handle:
        handle.write(_summary_markdown(report))

    calibration = report.get("calibration") or {}
    overall = calibration.get("overall") or {}
    v21_entry_ready = calibration.get("v21_entry_ready") or {}
    v22_entry_ready = calibration.get("v22_entry_ready") or {}
    v22_ranked = calibration.get("v22_ranked_portfolio") or {}
    baseline = calibration.get("bollinger_baseline") or {}
    print(json.dumps({
        "period_start": report.get("period_start"),
        "period_end": report.get("period_end"),
        "symbols": report.get("selected_symbol_count"),
        "signals": overall.get("signals"),
        "resolved": overall.get("resolved"),
        "win_rate_pct": overall.get("win_rate_pct"),
        "expectancy_r": overall.get("expectancy_r"),
        "profit_factor": overall.get("profit_factor"),
        "v21_entry_ready": v21_entry_ready,
        "v22_entry_ready": v22_entry_ready,
        "v22_ranked_portfolio": v22_ranked,
        "v22_portfolio": report.get("v22_portfolio"),
        "v22_walk_forward": report.get("v22_walk_forward"),
        "bollinger_baseline": baseline,
        "equity_sequence": report.get("equity_sequence"),
        "v21_equity_sequence": report.get("v21_equity_sequence"),
        "v22_equity_sequence": report.get("v22_equity_sequence"),
        "v22_ranked_equity_sequence": report.get("v22_ranked_equity_sequence"),
        "baseline_equity_sequence": report.get("baseline_equity_sequence"),
        "by_model": calibration.get("by_model"),
        "errors": len(report.get("errors") or []),
    }, ensure_ascii=False, indent=2, default=str))

    if report.get("selected_symbol_count", 0) == 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
