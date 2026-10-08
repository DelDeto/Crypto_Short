"""V4.4.11 M2-only replay for entry + stop research."""
import pandas as pd

from .backtest import _historical_ticker
from .config import BACKTEST_SHARD_COUNT, BACKTEST_SHARD_INDEX, BACKTEST_WARMUP_DAYS
from .mexc import fetch_backtest_frames, get_klines_window
from .strategy import analyze_short
from .v4_backtest import load_manifest, _closed_context
from .v428_features import build_v428_features
from .v429_backtest import _apply_manifest_shard
from .v4411_m2_execution import evaluate_v4411_m2


def _replay_symbol(symbol, frames, period_start, period_end, btc_one, eth_one, manifest_id):
    fifteen, one, four = frames.get("15M"), frames.get("1H"), frames.get("4H")
    if any(x is None or x.empty for x in (fifteen, one, four)):
        return [], {"symbol": symbol, "error": "missing historical frames"}
    fifteen, one, four = fifteen.sort_index(), one.sort_index(), four.sort_index()
    btc_one = None if btc_one is None or btc_one.empty else btc_one.sort_index()
    eth_one = None if eth_one is None or eth_one.empty else eth_one.sort_index()

    start_ts, end_ts = pd.Timestamp(period_start), pd.Timestamp(period_end)
    if start_ts.tzinfo is None: start_ts = start_ts.tz_localize("UTC")
    if end_ts.tzinfo is None: end_ts = end_ts.tz_localize("UTC")

    positions = [i for i, ts in enumerate(one.index) if start_ts <= ts and (ts + pd.Timedelta(hours=1)) <= end_ts]
    rows = []
    for pos in positions:
        if pos < 100:
            continue
        signal_end = one.index[pos] + pd.Timedelta(hours=1)
        if int(signal_end.hour) % 4 != 0:
            continue
        one_slice = one.iloc[:pos + 1]
        four_closed = _closed_context(four, signal_end, 240)
        btc_closed = _closed_context(btc_one, signal_end, 60)
        eth_closed = _closed_context(eth_one, signal_end, 60)
        if any(x is None for x in (four_closed, btc_closed, eth_closed)) or len(four_closed) < 90:
            continue
        try:
            base = analyze_short(symbol, {"1H": one_slice, "4H": four_closed}, _historical_ticker(one_slice), fast_row=None)
            features = build_v428_features(base, one_slice, four_closed, btc_closed, eth_closed)
        except Exception:
            continue
        if features is None:
            continue
        future15 = fifteen.loc[fifteen.index >= signal_end]
        future1 = one.loc[(one.index + pd.Timedelta(hours=1)) > signal_end]
        future4 = four.loc[(four.index + pd.Timedelta(hours=4)) > signal_end]
        result = evaluate_v4411_m2(features, signal_end, four_closed, future4, future1, future15)
        rows.append({"manifest_id": manifest_id, "symbol": symbol, "signal_time": signal_end.isoformat(), **features, **result})
    return rows, None


def run_v4411_m2_backtest(manifest_path=None):
    manifest = load_manifest(manifest_path)
    period_start, period_end, future_end = map(pd.Timestamp, (manifest["period_start"], manifest["period_end"], manifest["future_end"]))
    selected = _apply_manifest_shard(manifest["symbols"])
    warmup_start = period_start - pd.Timedelta(days=BACKTEST_WARMUP_DAYS)
    rows, errors, contexts = [], [], {}
    for symbol in ("BTC_USDT", "ETH_USDT"):
        try:
            contexts[symbol] = get_klines_window(symbol, "1h", warmup_start, future_end)
        except Exception as exc:
            contexts[symbol] = None
            errors.append({"symbol": symbol, "error": f"market context: {exc}"})
    for index, symbol in enumerate(selected, start=1):
        try:
            frames = fetch_backtest_frames(symbol, period_start, future_end, warmup_days=BACKTEST_WARMUP_DAYS)
            symbol_rows, error = _replay_symbol(symbol, frames, period_start, period_end, contexts.get("BTC_USDT"), contexts.get("ETH_USDT"), manifest["manifest_id"])
            rows.extend(symbol_rows)
            if error: errors.append(error)
        except Exception as exc:
            errors.append({"symbol": symbol, "error": str(exc)})
        print(f"[V4.4.11 M2 shard {BACKTEST_SHARD_INDEX+1}/{BACKTEST_SHARD_COUNT}] [{index}/{len(selected)}] {symbol}: rows={len(rows)} errors={len(errors)}", flush=True)
    rows.sort(key=lambda r: (str(r.get("signal_time")), str(r.get("symbol"))))
    return {
        "engine": "Crypto Short V4.4.11 M2 Entry Stop Study",
        "manifest_id": manifest["manifest_id"], "manifest": manifest,
        "period_start": manifest["period_start"], "period_end": manifest["period_end"], "future_end": manifest["future_end"],
        "days": manifest["days"], "shard_index": int(BACKTEST_SHARD_INDEX), "shard_count": int(BACKTEST_SHARD_COUNT),
        "selected_symbols": selected, "selected_symbol_count": len(selected), "trades": rows, "errors": errors,
    }
