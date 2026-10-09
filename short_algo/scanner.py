import csv
import json
import os
from datetime import datetime, timezone

from .config import (
    DEEP_LIMIT,
    MAX_SPREAD_BPS,
    MIN_TURNOVER_USDT,
    OUTPUT_DIR,
    TOP_REPORT,
)
from .live_m2 import evaluate_live_symbol
from .mexc import (
    fetch_deep_frames,
    fetch_many_deep,
    fetch_many_fast,
    get_all_tickers,
    get_contract_universe,
)
from .strategy import analyze_short, score_fast_short


STATUS_RANK = {
    "ENTRY_READY": 0,
    "DEVELOPING": 1,
    "WATCH": 2,
    "IGNORE": 3,
}

TIER_RANK = {"A+": 0, "A": 1, "B": 2, "C": 3}


def _ticker_liquid_enough(ticker):
    turnover = float((ticker or {}).get("turnover_24h") or 0.0)
    spread = (ticker or {}).get("spread_bps")
    if turnover >= MIN_TURNOVER_USDT:
        return True
    if spread is not None and float(spread) <= min(20.0, MAX_SPREAD_BPS):
        return True
    return False


def _select_deep(fast_rows, tickers):
    selected = []
    seen = set()

    def add(symbol):
        if symbol and symbol not in seen and len(selected) < DEEP_LIMIT:
            selected.append(symbol)
            seen.add(symbol)

    for row in sorted(
        fast_rows,
        key=lambda x: (-float(x["fast_score"]), -float(x.get("turnover_24h") or 0.0)),
    ):
        add(row["symbol"])
        if len(selected) >= max(1, int(DEEP_LIMIT * 0.65)):
            break

    fade_pool = []
    for row in fast_rows:
        symbol = row["symbol"]
        ticker = tickers.get(symbol) or {}
        change = float(row.get("ticker_change_24h_pct") or 0.0)
        if change > 2.0 and _ticker_liquid_enough(ticker):
            fade_pool.append(row)
    for row in sorted(
        fade_pool,
        key=lambda x: (
            -float(x.get("ticker_change_24h_pct") or 0.0),
            -float(x.get("turnover_24h") or 0.0),
        ),
    ):
        add(row["symbol"])
        if len(selected) >= max(1, int(DEEP_LIMIT * 0.85)):
            break

    breakdown_pool = [
        row for row in fast_rows
        if -18.0 <= float(row.get("return_12h_pct") or 0.0) <= -0.5
    ]
    for row in sorted(
        breakdown_pool,
        key=lambda x: (-float(x["fast_score"]), -float(x.get("turnover_24h") or 0.0)),
    ):
        add(row["symbol"])
        if len(selected) >= DEEP_LIMIT:
            break
    return selected


def _live_contexts():
    contexts = {}
    errors = {}
    for symbol in ("BTC_USDT", "ETH_USDT"):
        try:
            contexts[symbol] = fetch_deep_frames(symbol)["1H"]
        except Exception as exc:
            contexts[symbol] = None
            errors[symbol] = str(exc)
    return contexts, errors


def run_scan():
    started = datetime.now(timezone.utc)
    universe = get_contract_universe()
    tickers = get_all_tickers()

    scan_symbols = [
        symbol
        for symbol in universe
        if symbol in tickers and (tickers[symbol].get("last_price") or 0) > 0
    ]

    fast_frames, fast_errors = fetch_many_fast(scan_symbols)
    fast_rows = []
    for symbol, frame in fast_frames.items():
        try:
            fast_rows.append(score_fast_short(symbol, frame, tickers.get(symbol) or {}))
        except Exception as exc:
            fast_errors[symbol] = f"fast score: {exc}"

    deep_symbols = _select_deep(fast_rows, tickers)
    deep_frames, deep_errors = fetch_many_deep(deep_symbols)
    fast_by_symbol = {row["symbol"]: row for row in fast_rows}

    # Keep legacy V1 output as an audit/reference stream.
    results = []
    for symbol, frames in deep_frames.items():
        try:
            results.append(
                analyze_short(
                    symbol,
                    frames,
                    tickers.get(symbol) or {},
                    fast_by_symbol.get(symbol),
                )
            )
        except Exception as exc:
            deep_errors[symbol] = f"deep score: {exc}"

    results.sort(
        key=lambda x: (
            STATUS_RANK.get(x.get("status"), 9),
            -float(x.get("score") or 0.0),
            -float(x.get("turnover_24h") or 0.0),
        )
    )

    contexts, context_errors = _live_contexts()
    m2_live_signals = []
    if contexts.get("BTC_USDT") is not None and contexts.get("ETH_USDT") is not None:
        for symbol, frames in deep_frames.items():
            try:
                m2_live_signals.extend(
                    evaluate_live_symbol(
                        symbol,
                        frames,
                        contexts["BTC_USDT"],
                        contexts["ETH_USDT"],
                    )
                )
            except Exception as exc:
                deep_errors[symbol] = f"{deep_errors.get(symbol, '')} live-m2: {exc}".strip()

    m2_live_signals.sort(
        key=lambda x: (
            TIER_RANK.get(x.get("tier"), 9),
            x.get("entry_time") or "",
        )
    )

    finished = datetime.now(timezone.utc)
    report = {
        "scanner": "Crypto Short Scanner M2 V4.4.18 Live",
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_seconds": round((finished - started).total_seconds(), 2),
        "universe_count": len(universe),
        "ticker_count": len(tickers),
        "fast_requested": len(scan_symbols),
        "fast_success": len(fast_frames),
        "fast_error_count": len(fast_errors),
        "deep_requested": len(deep_symbols),
        "deep_success": len(deep_frames),
        "deep_error_count": len(deep_errors),
        "status_counts": {
            status: sum(1 for row in results if row.get("status") == status)
            for status in STATUS_RANK
        },
        "m2_live_counts": {
            tier: sum(1 for row in m2_live_signals if row.get("tier") == tier)
            for tier in ("A+", "A", "B", "C")
        },
        "m2_live_signal_count": len(m2_live_signals),
        "deep_symbols": deep_symbols,
        "results": results,
        "m2_live_signals": m2_live_signals,
        "errors": {
            "fast": fast_errors,
            "deep": deep_errors,
            "context": context_errors,
        },
    }
    return report


def _fmt_price(value):
    if value is None:
        return "-"
    value = float(value)
    if abs(value) >= 100:
        return f"{value:.3f}"
    if abs(value) >= 1:
        return f"{value:.5f}"
    return f"{value:.8f}"


def save_report(report):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    json_path = os.path.join(OUTPUT_DIR, "short_scan.json")
    csv_path = os.path.join(OUTPUT_DIR, "short_scan.csv")
    md_path = os.path.join(OUTPUT_DIR, "short_scan.md")
    m2_csv_path = os.path.join(OUTPUT_DIR, "m2_live_signals.csv")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    fields = [
        "symbol", "status", "score", "current_price", "entry", "stop",
        "stop_pct", "tp1", "tp2", "runner", "support_room_r",
        "atr_pct_1h", "supply_distance_atr", "ticker_change_24h_pct",
        "turnover_24h", "spread_bps", "funding_rate", "fast_score", "reasons",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in report["results"]:
            out = {key: row.get(key) for key in fields}
            out["reasons"] = " | ".join(row.get("reasons") or [])
            writer.writerow(out)

    m2_fields = [
        "signal_id","symbol","tier","d_gate","e1_ema_gate","e2_anti_bottom_gate",
        "signal_anchor_time","break_time","ready_time","entry_time","signal_age_minutes",
        "watch_hours","entry","stop","tp1","tp2","atr_at_entry",
        "ema20_distance_atr","anti_bottom_total","candidate_context_points",
        "market_r4_pct","market_r24_pct","relative_4h_pct","relative_24h_pct",
        "failed_reclaim_attempts","retest_attempts","pivot_high_count","bars_below",
    ]
    with open(m2_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=m2_fields)
        writer.writeheader()
        for row in report.get("m2_live_signals", []):
            writer.writerow({k: row.get(k) for k in m2_fields})

    lines = [
        "# Crypto Short Scanner — M2 V4.4.18 Live",
        "",
        f"- Scan finished: {report['finished_at']}",
        f"- Universe: {report['universe_count']} contracts",
        f"- Fast scan: {report['fast_success']}/{report['fast_requested']}",
        f"- Deep scan: {report['deep_success']}/{report['deep_requested']}",
        f"- Fresh M2 D+ signals: {report['m2_live_signal_count']}",
        f"- Tiers: {report['m2_live_counts']}",
        "",
        "> Signal-performance research/live observation only. No auto-order.",
        "",
    ]
    for i, row in enumerate(report.get("m2_live_signals", [])[:TOP_REPORT], 1):
        lines.extend([
            f"## {i}. {row['symbol']} — Tier {row['tier']}",
            "",
            f"- Entry: {_fmt_price(row['entry'])}",
            f"- Stop: {_fmt_price(row['stop'])} (1.75 ATR)",
            f"- TP1: {_fmt_price(row['tp1'])} (2 ATR)",
            f"- TP2: {_fmt_price(row['tp2'])} (3 ATR)",
            f"- Watch: {row['watch_hours']}h",
            f"- Risk-Off: Y | S4 Macro Bear: Y",
            f"- E1 EMA gate: {'Y' if row['e1_ema_gate'] else 'N'} ({row.get('ema20_distance_atr')})",
            f"- E2 Anti-bottom gate: {'Y' if row['e2_anti_bottom_gate'] else 'N'} ({row.get('anti_bottom_total')})",
            "",
        ])

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return {
        "json": json_path,
        "csv": csv_path,
        "m2_csv": m2_csv_path,
        "markdown": md_path,
    }
