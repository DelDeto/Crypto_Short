"""M3 V1 60d replay."""
import json
import os

import pandas as pd

from .config import BACKTEST_SHARD_COUNT, BACKTEST_SHARD_INDEX, BACKTEST_WARMUP_DAYS
from .indicators import return_pct
from .m3_v1_config import M3_COOLDOWN_HOURS
from .m3_v1_execution import evaluate_m3_v1
from .mexc import fetch_backtest_frames, get_klines_window


def _load_manifest(path=None):
    path = path or os.getenv("M3_MANIFEST_PATH", "frozen/m3_v1_manifest.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _apply_shard(symbols):
    return [
        s for i, s in enumerate(symbols)
        if i % int(BACKTEST_SHARD_COUNT) == int(BACKTEST_SHARD_INDEX)
    ]


def _closed(frame, signal_time, hours):
    if frame is None or frame.empty:
        return None
    return frame.loc[
        (frame.index + pd.Timedelta(hours=hours)) <= pd.Timestamp(signal_time)
    ]


def _market_context(btc_one, eth_one, signal_time):
    btc = _closed(btc_one, signal_time, 1)
    eth = _closed(eth_one, signal_time, 1)
    if btc is None or eth is None or len(btc) < 30 or len(eth) < 30:
        return {
            "m3_market_state": "UNKNOWN",
            "m3_market_r4_pct": None,
            "m3_market_r24_pct": None,
        }

    r4 = (return_pct(btc["close"], 4) + return_pct(eth["close"], 4)) / 2.0
    r24 = (return_pct(btc["close"], 24) + return_pct(eth["close"], 24)) / 2.0

    if r4 >= 1.0 and r24 >= 2.0:
        state = "RISK_ON_STRONG"
    elif r4 <= -0.8 and r24 <= 0.0:
        state = "RISK_OFF"
    else:
        state = "NEUTRAL"
    return {
        "m3_market_state": state,
        "m3_market_r4_pct": round(r4, 4),
        "m3_market_r24_pct": round(r24, 4),
    }


def _replay_symbol(symbol, frames, period_start, period_end, btc_one, eth_one):
    fifteen = frames.get("15M")
    one = frames.get("1H")
    four = frames.get("4H")
    if any(x is None or x.empty for x in (fifteen, one, four)):
        return [], {"symbol": symbol, "error": "missing historical frames"}

    fifteen = fifteen.sort_index()
    one = one.sort_index()
    four = four.sort_index()

    start = pd.Timestamp(period_start)
    end = pd.Timestamp(period_end)
    if start.tzinfo is None:
        start = start.tz_localize("UTC")
    if end.tzinfo is None:
        end = end.tz_localize("UTC")

    rows = []
    last_candidate = None

    positions = [
        i for i, ts in enumerate(one.index)
        if start <= ts + pd.Timedelta(hours=1) <= end
    ]

    for pos in positions:
        if pos < 100:
            continue

        signal_time = one.index[pos] + pd.Timedelta(hours=1)
        one_closed = one.iloc[:pos + 1]
        four_closed = _closed(four, signal_time, 4)
        if four_closed is None or len(four_closed) < 60:
            continue

        future15 = fifteen.loc[fifteen.index >= signal_time]
        result = evaluate_m3_v1(
            one_closed,
            four_closed,
            future15,
            signal_time,
        )

        # Only persist actual M3 candidates / benchmark entries, not every
        # hourly rejection in the funnel.
        if result.get("m3_tier") not in ("A", "B", "C"):
            continue

        if last_candidate is not None:
            if signal_time - last_candidate < pd.Timedelta(hours=int(M3_COOLDOWN_HOURS)):
                continue
        last_candidate = signal_time

        rows.append({
            "symbol": symbol,
            "signal_time": signal_time.isoformat(),
            **_market_context(btc_one, eth_one, signal_time),
            **result,
        })

    return rows, None


def run_m3_v1_backtest(manifest_path=None):
    manifest = _load_manifest(manifest_path)
    period_start = pd.Timestamp(manifest["period_start"])
    period_end = pd.Timestamp(manifest["period_end"])
    future_end = pd.Timestamp(manifest["future_end"])
    selected = _apply_shard(manifest["symbols"])
    warmup_start = period_start - pd.Timedelta(days=int(BACKTEST_WARMUP_DAYS))

    errors = []
    contexts = {}
    for symbol in ("BTC_USDT", "ETH_USDT"):
        try:
            contexts[symbol] = get_klines_window(
                symbol, "1h", warmup_start, future_end
            )
        except Exception as exc:
            contexts[symbol] = None
            errors.append({
                "symbol": symbol,
                "error": f"market context: {exc}",
            })

    rows = []
    for index, symbol in enumerate(selected, start=1):
        try:
            frames = fetch_backtest_frames(
                symbol,
                period_start,
                future_end,
                warmup_days=BACKTEST_WARMUP_DAYS,
            )
            symbol_rows, error = _replay_symbol(
                symbol,
                frames,
                period_start,
                period_end,
                contexts.get("BTC_USDT"),
                contexts.get("ETH_USDT"),
            )
            rows.extend(symbol_rows)
            if error:
                errors.append(error)
        except Exception as exc:
            errors.append({"symbol": symbol, "error": str(exc)})

        print(
            f"[M3 V1 shard {int(BACKTEST_SHARD_INDEX)+1}/{int(BACKTEST_SHARD_COUNT)}] "
            f"[{index}/{len(selected)}] {symbol}: candidates={len(rows)} "
            f"errors={len(errors)}",
            flush=True,
        )

    rows.sort(key=lambda r: (str(r.get("signal_time")), str(r.get("symbol"))))
    return {
        "engine": "M3 V1 Intraday Bearish Pullback Continuation",
        "manifest_id": manifest["manifest_id"],
        "manifest": manifest,
        "period_start": manifest["period_start"],
        "period_end": manifest["period_end"],
        "future_end": manifest["future_end"],
        "days": manifest["days"],
        "shard_index": int(BACKTEST_SHARD_INDEX),
        "shard_count": int(BACKTEST_SHARD_COUNT),
        "selected_symbols": selected,
        "selected_symbol_count": len(selected),
        "candidates": rows,
        "errors": errors,
    }
