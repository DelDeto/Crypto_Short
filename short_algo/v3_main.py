import csv
import json
import os
import sys

from .config import OUTPUT_DIR
from .v3_backtest import run_v3_backtest


def _write_json(path, payload):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)


def _write_trades_csv(path, trades):
    fields = [
        "symbol", "signal_time", "exit_time", "v3_engine", "v3_status",
        "v3_score", "v3_threshold", "v3_primary", "v3_regime",
        "v3_relative_4h_pct", "v3_relative_24h_pct",
        "v3_projected_cost_r", "v3_cluster", "v3_quality",
        "v3_market_rank", "v3_ranked", "entry", "stop", "stop_pct",
        "tp1", "tp2", "runner", "support_room_r", "return_4h_pct",
        "return_12h_pct", "return_24h_pct", "volume_ratio_1h",
        "outcome", "gross_r", "cost_r", "realized_r", "terminal_close",
        "mae_r", "mfe_r", "bars_to_outcome", "outcome_bar_minutes",
        "ambiguous_same_bar", "tp2_touched", "runner_touched",
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
    cal = report.get("calibration") or {}
    entry = cal.get("entry_ready") or {}
    ranked = cal.get("ranked_portfolio") or {}
    equity = report.get("entry_equity_sequence") or {}
    ranked_equity = report.get("ranked_equity_sequence") or {}
    portfolio = report.get("v3_portfolio") or {}
    robustness = report.get("v3_temporal_robustness") or {}
    audit = ((report.get("selection_meta") or {}).get("universe_audit") or {})

    lines = [
        "# Crypto Short V3 — Multi-Strategy Backtest",
        "",
        f"- Period: {report.get('period_start')} → {report.get('period_end')}",
        f"- Days: {report.get('days')}",
        f"- Symbols: {report.get('selected_symbol_count')}",
        f"- Crypto contracts available: {audit.get('crypto_contracts', '-')}",
        f"- Non-crypto excluded: {audit.get('excluded_non_crypto_count', 0)}",
        f"- Errors: {len(report.get('errors') or [])}",
        "",
        "## Primary executable setups",
        f"- Signals: {entry.get('signals', 0)}",
        f"- Net profitable rate: {_fmt(entry.get('net_profitable_rate_pct'), 2)}%",
        f"- TP-before-SL rate: {_fmt(entry.get('tp_before_sl_rate_pct'), 2)}%",
        f"- Expectancy: {_fmt(entry.get('expectancy_r'))}R",
        f"- Profit factor: {_fmt(entry.get('profit_factor'))}",
        f"- Avg execution cost: {_fmt(entry.get('avg_cost_r'))}R",
        f"- Net sequence: {_fmt(equity.get('net_r'), 2)}R",
        f"- Max drawdown: {_fmt(equity.get('max_drawdown_r'), 2)}R",
        "",
        "## Ranked portfolio",
        f"- Ranked trades: {ranked.get('signals', 0)}",
        f"- Expectancy: {_fmt(ranked.get('expectancy_r'))}R",
        f"- Profit factor: {_fmt(ranked.get('profit_factor'))}",
        f"- Net R: {_fmt(ranked_equity.get('net_r'), 2)}R",
        f"- Max DD: {_fmt(ranked_equity.get('max_drawdown_r'), 2)}R",
        f"- Portfolio start: {_fmt(portfolio.get('starting_equity'), 2)}",
        f"- Portfolio end: {_fmt(portfolio.get('ending_equity'), 2)}",
        f"- Portfolio return: {_fmt(portfolio.get('return_pct'), 2)}%",
        f"- Portfolio max DD: {_fmt(portfolio.get('max_drawdown_pct'), 2)}%",
        "",
        "## Engine comparison",
        "",
        "| Engine | Signals | Net profitable % | TP-before-SL % | Expectancy R | PF | Avg cost R | Avg MAE R | Avg MFE R |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for engine, stats in (cal.get("by_engine") or {}).items():
        lines.append(
            "| " + " | ".join([
                str(engine),
                str(stats.get("signals", 0)),
                _fmt(stats.get("net_profitable_rate_pct"), 2),
                _fmt(stats.get("tp_before_sl_rate_pct"), 2),
                _fmt(stats.get("expectancy_r")),
                _fmt(stats.get("profit_factor")),
                _fmt(stats.get("avg_cost_r")),
                _fmt(stats.get("avg_mae_r")),
                _fmt(stats.get("avg_mfe_r")),
            ]) + " |"
        )

    lines += [
        "",
        "## Regime comparison",
        "",
        "| Regime | Signals | Net profitable % | Expectancy R | PF |",
        "|---|---:|---:|---:|---:|",
    ]
    for regime, stats in (cal.get("by_regime") or {}).items():
        lines.append(
            "| " + " | ".join([
                str(regime),
                str(stats.get("signals", 0)),
                _fmt(stats.get("net_profitable_rate_pct"), 2),
                _fmt(stats.get("expectancy_r")),
                _fmt(stats.get("profit_factor")),
            ]) + " |"
        )

    older = robustness.get("older_half") or {}
    recent = robustness.get("recent_half") or {}
    lines += [
        "",
        "## Temporal robustness",
        f"- Older half: {older.get('signals', 0)} trades | expectancy {_fmt(older.get('expectancy_r'))}R | PF {_fmt(older.get('profit_factor'))}",
        f"- Recent half: {recent.get('signals', 0)} trades | expectancy {_fmt(recent.get('expectancy_r'))}R | PF {_fmt(recent.get('profit_factor'))}",
        "",
        "| Quarter | Signals | Expectancy R | PF |",
        "|---|---:|---:|---:|",
    ]
    for row in robustness.get("quarters") or []:
        stats = row.get("metrics") or {}
        lines.append(
            f"| {row.get('quarter')} | {stats.get('signals', 0)} | {_fmt(stats.get('expectancy_r'))} | {_fmt(stats.get('profit_factor'))} |"
        )

    lines += [
        "",
        "## V3 methodology",
        "- Five independent Short engines: Extreme Pump Reversal, Exhaustion Reversal, Breakdown Retest, Relative Weakness, Failed Breakout/Supply Fade.",
        "- BTC + ETH timestamp-aligned 1H context routes RISK_ON / NEUTRAL / RISK_OFF.",
        "- 4H/1H provide context; only fully closed 15m candles provide execution confirmation.",
        "- Execution-cost gate rejects setups whose projected fee + slippage exceeds the configured R budget.",
        "- Support-room and stop-percent hard gates are applied before ENTRY_READY.",
        "- Portfolio ranking occurs only after all shards merge.",
        "- Known correlated sectors are cluster-limited; unknown assets receive their own cluster.",
        "- TP1 is fixed at +2R and SL at -1R for first V3 validation; same-bar TP/SL is a conservative loss.",
        "- No current funding/OI snapshot is injected historically. Crowded-long OI/funding engine remains disabled until timestamp-correct history is available.",
        "- Current turnover is only a cohort-selection aid and can introduce survivorship/selection bias.",
        "- Older-half validation is retrospective holdout, not future live out-of-sample evidence.",
        "",
    ]
    return "\n".join(lines)


def main():
    report = run_v3_backtest()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    _write_json(os.path.join(OUTPUT_DIR, "v3_backtest.json"), report)
    _write_trades_csv(os.path.join(OUTPUT_DIR, "v3_trades.csv"), report.get("trades") or [])
    _write_json(os.path.join(OUTPUT_DIR, "v3_calibration.json"), report.get("calibration") or {})
    with open(os.path.join(OUTPUT_DIR, "v3_summary.md"), "w", encoding="utf-8") as handle:
        handle.write(_summary_markdown(report))

    entry = (report.get("calibration") or {}).get("entry_ready") or {}
    print(json.dumps({
        "period_start": report.get("period_start"),
        "period_end": report.get("period_end"),
        "symbols": report.get("selected_symbol_count"),
        "entry_ready": entry,
        "entry_equity_sequence": report.get("entry_equity_sequence"),
        "by_engine": (report.get("calibration") or {}).get("by_engine"),
        "errors": len(report.get("errors") or []),
    }, ensure_ascii=False, indent=2, default=str))

    return 0 if report.get("selected_symbol_count", 0) > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
