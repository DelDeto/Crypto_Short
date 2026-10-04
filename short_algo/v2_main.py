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
        "symbol", "signal_time", "model", "top_gainer_context", "status",
        "score", "return_24h_pct", "entry", "stop", "stop_pct", "tp1",
        "tp2", "runner", "support_room_r", "supply_distance_atr",
        "outcome", "realized_r", "mae_r", "mfe_r", "bars_to_outcome",
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
    equity = report.get("equity_sequence") or {}

    lines = [
        "# Crypto Short Scanner V2 — Backtest & Calibration",
        "",
        f"- Period: {report.get('period_start')} → {report.get('period_end')}",
        f"- Days: {report.get('days')}",
        f"- Symbols: {report.get('selected_symbol_count')}",
        f"- Signals: {overall.get('signals', 0)}",
        f"- Resolved: {overall.get('resolved', 0)}",
        f"- Win rate @ +2R before -1R: {_fmt(overall.get('win_rate_pct'))}%",
        f"- Expectancy: {_fmt(overall.get('expectancy_r'), 3)}R / resolved signal",
        f"- Profit factor: {_fmt(overall.get('profit_factor'), 3)}",
        f"- Net sequence: {_fmt(equity.get('net_r'), 2)}R",
        f"- Max drawdown: {_fmt(equity.get('max_drawdown_r'), 2)}R",
        f"- Longest loss streak: {equity.get('longest_loss_streak', 0)}",
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
        "## Method notes",
        "",
        "- No future 1H candle is used to build a signal.",
        "- 4H candles must be fully closed before the 1H signal timestamp.",
        "- Primary outcome is conservative: +2R before -1R.",
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

    overall = (report.get("calibration") or {}).get("overall") or {}
    print(json.dumps({
        "period_start": report.get("period_start"),
        "period_end": report.get("period_end"),
        "symbols": report.get("selected_symbol_count"),
        "signals": overall.get("signals"),
        "resolved": overall.get("resolved"),
        "win_rate_pct": overall.get("win_rate_pct"),
        "expectancy_r": overall.get("expectancy_r"),
        "profit_factor": overall.get("profit_factor"),
        "equity_sequence": report.get("equity_sequence"),
        "by_model": (report.get("calibration") or {}).get("by_model"),
        "errors": len(report.get("errors") or []),
    }, ensure_ascii=False, indent=2, default=str))

    if report.get("selected_symbol_count", 0) == 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
