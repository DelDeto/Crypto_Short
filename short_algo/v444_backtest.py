"""V4.4.4 replay: unchanged M1 benchmarks + rebuilt support-pressure M2."""
import pandas as pd

from .backtest import _historical_ticker
from .config import BACKTEST_SHARD_COUNT, BACKTEST_SHARD_INDEX, BACKTEST_WARMUP_DAYS
from .mexc import fetch_backtest_frames, get_klines_window
from .strategy import analyze_short
from .v4_backtest import load_manifest, _closed_context
from .v428_features import build_v428_features
from .v429_backtest import _apply_manifest_shard, _future_context, _last_close
from .v429_diagnostics import future_labels_v429
from .v440_execution import evaluate_v440_entry
from .v441_execution import evaluate_v441_models
from .v444_config import V444_REQUIRED_FUTURE_HOURS, V444_SCAN_CADENCE_HOURS
from .v444_execution import evaluate_v444_m2


def _replay_symbol(symbol, frames, period_start, period_end, btc_one, eth_one, manifest_id):
    fifteen = frames.get("15M")
    one = frames.get("1H")
    four = frames.get("4H")
    if any(x is None or x.empty for x in (fifteen, one, four)):
        return [], {"symbol": symbol, "error": "missing historical frames"}

    fifteen = fifteen.sort_index()
    one = one.sort_index()
    four = four.sort_index()
    btc_one = None if btc_one is None or btc_one.empty else btc_one.sort_index()
    eth_one = None if eth_one is None or eth_one.empty else eth_one.sort_index()

    start_ts = pd.Timestamp(period_start)
    end_ts = pd.Timestamp(period_end)
    if start_ts.tzinfo is None:
        start_ts = start_ts.tz_localize("UTC")
    if end_ts.tzinfo is None:
        end_ts = end_ts.tz_localize("UTC")

    cutoff = end_ts - pd.Timedelta(hours=int(V444_REQUIRED_FUTURE_HOURS))
    positions = [i for i, ts in enumerate(one.index) if start_ts <= ts <= cutoff]
    cadence = max(1, int(V444_SCAN_CADENCE_HOURS))
    rows = []

    for pos in positions:
        if pos < 100:
            continue
        signal_end = one.index[pos] + pd.Timedelta(hours=1)
        if int(signal_end.hour) % cadence != 0:
            continue

        one_slice = one.iloc[: pos + 1]
        four_closed = _closed_context(four, signal_end, 240)
        fifteen_closed = _closed_context(fifteen, signal_end, 15)
        btc_closed = _closed_context(btc_one, signal_end, 60)
        eth_closed = _closed_context(eth_one, signal_end, 60)
        if any(x is None for x in (four_closed, fifteen_closed, btc_closed, eth_closed)):
            continue
        if len(four_closed) < 90 or len(fifteen_closed) < 40:
            continue

        try:
            base = analyze_short(
                symbol,
                {"1H": one_slice, "4H": four_closed},
                _historical_ticker(one_slice),
                fast_row=None,
            )
            features = build_v428_features(
                base,
                one_slice,
                four_closed,
                btc_closed,
                eth_closed,
            )
        except Exception:
            continue
        if features is None:
            continue

        future15 = fifteen.loc[fifteen.index >= signal_end]
        labels = future_labels_v429(
            features,
            signal_end,
            future15,
            _last_close(btc_closed),
            _last_close(eth_closed),
            _future_context(btc_one, signal_end),
            _future_context(eth_one, signal_end),
        )
        future_exec = (
            future15
            if not future15.empty and future15.index[0] == signal_end
            else future15.head(0)
        )

        strict = evaluate_v440_entry(
            features,
            fifteen_closed,
            future_exec,
            one_slice,
            four_closed,
        )
        legacy = evaluate_v441_models(
            features,
            fifteen_closed,
            future_exec,
            one_slice,
            four_closed,
        )
        rebuilt = evaluate_v444_m2(
            features,
            fifteen_closed,
            future_exec,
            one_slice,
            four_closed,
        )

        rows.append({
            "manifest_id": manifest_id,
            "symbol": symbol,
            "signal_time": signal_end.isoformat(),
            **features,
            **labels,
            **strict,
            **legacy,
            **rebuilt,
        })

    return rows, None


def run_v444_backtest(manifest_path=None):
    manifest = load_manifest(manifest_path)
    period_start = pd.Timestamp(manifest["period_start"])
    period_end = pd.Timestamp(manifest["period_end"])
    selected = _apply_manifest_shard(manifest["symbols"])
    warmup_start = period_start - pd.Timedelta(days=BACKTEST_WARMUP_DAYS)

    rows, errors, contexts = [], [], {}
    for symbol in ("BTC_USDT", "ETH_USDT"):
        try:
            contexts[symbol] = get_klines_window(
                symbol,
                "1h",
                warmup_start,
                period_end,
            )
        except Exception as exc:
            contexts[symbol] = None
            errors.append({"symbol": symbol, "error": f"market context: {exc}"})

    for index, symbol in enumerate(selected, start=1):
        try:
            frames = fetch_backtest_frames(
                symbol,
                period_start,
                period_end,
                warmup_days=BACKTEST_WARMUP_DAYS,
            )
            symbol_rows, error = _replay_symbol(
                symbol,
                frames,
                period_start,
                period_end,
                contexts.get("BTC_USDT"),
                contexts.get("ETH_USDT"),
                manifest["manifest_id"],
            )
            rows.extend(symbol_rows)
            if error:
                errors.append(error)
        except Exception as exc:
            errors.append({"symbol": symbol, "error": str(exc)})

        print(
            f"[V4.4.4 shard {BACKTEST_SHARD_INDEX+1}/{BACKTEST_SHARD_COUNT}] "
            f"[{index}/{len(selected)}] {symbol}: rows={len(rows)} errors={len(errors)}",
            flush=True,
        )

    rows.sort(key=lambda r: (str(r.get("signal_time")), str(r.get("symbol"))))
    return {
        "engine": "Crypto Short V4.4.4 Support Pressure Breakdown Research",
        "manifest_id": manifest["manifest_id"],
        "manifest": manifest,
        "period_start": manifest["period_start"],
        "period_end": manifest["period_end"],
        "days": manifest["days"],
        "shard_index": int(BACKTEST_SHARD_INDEX),
        "shard_count": int(BACKTEST_SHARD_COUNT),
        "selected_symbols": selected,
        "selected_symbol_count": len(selected),
        "trades": rows,
        "errors": errors,
    }
