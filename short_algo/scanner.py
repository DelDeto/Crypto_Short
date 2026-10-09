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
from .m2_prefilter import score_m2_prefilter
from .indicators import return_pct, structure_snapshot
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


def _market_risk_off_proxy(fast_frames):
    btc = fast_frames.get("BTC_USDT")
    eth = fast_frames.get("ETH_USDT")
    if btc is None or eth is None:
        return False, {"state": "UNKNOWN"}

    bs = structure_snapshot(btc)
    es = structure_snapshot(eth)
    market_r4 = (return_pct(btc["close"], 4) + return_pct(eth["close"], 4)) / 2.0
    market_r24 = (return_pct(btc["close"], 24) + return_pct(eth["close"], 24)) / 2.0
    both_below = (
        float(bs["close"]) < float(bs["ema20"])
        and float(es["close"]) < float(es["ema20"])
    )
    risk_off = bool(market_r4 <= -0.8 and market_r24 <= 0.0 and both_below)
    return risk_off, {
        "state": "RISK_OFF" if risk_off else "NOT_RISK_OFF",
        "market_r4_pct": round(market_r4, 3),
        "market_r24_pct": round(market_r24, 3),
        "btc_below_ema20": float(bs["close"]) < float(bs["ema20"]),
        "eth_below_ema20": float(es["close"]) < float(es["ema20"]),
    }


def _select_deep(fast_rows, tickers):
    """Allocate deep slots for M2, not generic V1 short ranking.

    75%: highest M2 prefilter score.
    15%: explicit recent-break/persistent-pressure reserve.
    10%: legacy fast-score reserve to protect against proxy blind spots.
    """
    selected = []
    seen = set()

    def add(symbol):
        if symbol and symbol not in seen and len(selected) < DEEP_LIMIT:
            selected.append(symbol)
            seen.add(symbol)

    primary_target = max(1, int(DEEP_LIMIT * 0.75))
    pressure_target = max(primary_target, int(DEEP_LIMIT * 0.90))

    for row in sorted(
        fast_rows,
        key=lambda x: (
            -float(x.get("m2_prefilter_score") or 0.0),
            -float(x.get("m2_proxy_closes_below") or 0.0),
            float(x.get("m2_proxy_near_support_atr") or 99.0),
            -float(x.get("turnover_24h") or 0.0),
        ),
    ):
        add(row["symbol"])
        if len(selected) >= primary_target:
            break

    pressure_pool = [
        row for row in fast_rows
        if row.get("m2_proxy_breakdown")
        or float(row.get("m2_proxy_closes_below") or 0.0) >= 3
        or float(row.get("m2_proxy_near_support_atr") or 99.0) <= 0.8
    ]
    for row in sorted(
        pressure_pool,
        key=lambda x: (
            -float(x.get("m2_proxy_breakdown") or 0),
            -float(x.get("m2_proxy_closes_below") or 0.0),
            -float(x.get("m2_prefilter_score") or 0.0),
            -float(x.get("turnover_24h") or 0.0),
        ),
    ):
        add(row["symbol"])
        if len(selected) >= pressure_target:
            break

    # Small reserve for names that the new proxy may underrank. This protects
    # coverage while live evidence accumulates.
    for row in sorted(
        fast_rows,
        key=lambda x: (
            -float(x.get("fast_score") or 0.0),
            -float(x.get("turnover_24h") or 0.0),
        ),
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
    market_risk_off, market_prefilter_context = _market_risk_off_proxy(fast_frames)

    fast_rows = []
    for symbol, frame in fast_frames.items():
        try:
            row = score_fast_short(symbol, frame, tickers.get(symbol) or {})
            row.update(
                score_m2_prefilter(
                    symbol,
                    frame,
                    tickers.get(symbol) or {},
                    market_risk_off=market_risk_off,
                )
            )
            fast_rows.append(row)
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
        "m2_prefilter_context": market_prefilter_context,
        "m2_prefilter_top": sorted(
            fast_rows,
            key=lambda x: -float(x.get("m2_prefilter_score") or 0.0),
        )[:30],
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
