"""V4.2.1 replay focused on discretionary Short filtering quality."""

import pandas as pd

from .backtest import _historical_ticker
from .config import (
    BACKTEST_COOLDOWN_HOURS,
    BACKTEST_SHARD_COUNT,
    BACKTEST_SHARD_INDEX,
    BACKTEST_STEP_HOURS,
    BACKTEST_WARMUP_DAYS,
)
from .mexc import fetch_backtest_frames, get_klines_window
from .strategy import analyze_short
from .v4_backtest import load_manifest, _closed_context
from .v421_diagnostics import directional_followthrough
from .v421_filter import build_v421_candidate


def _apply_manifest_shard(symbols):
    count = max(1, int(BACKTEST_SHARD_COUNT))
    index = int(BACKTEST_SHARD_INDEX)
    if index < 0 or index >= count:
        raise ValueError(
            f"BACKTEST_SHARD_INDEX={index} outside 0..{count - 1}"
        )
    return list(symbols)[index::count]


def _replay_symbol(
    symbol,
    frames,
    period_start,
    period_end,
    btc_one,
    eth_one,
    manifest_id,
):
    fifteen = frames.get("15M")
    one = frames.get("1H")
    four = frames.get("4H")
    if (
        fifteen is None or fifteen.empty
        or one is None or one.empty
        or four is None or four.empty
    ):
        return [], {"symbol": symbol, "error": "missing historical frames"}

    fifteen = fifteen.sort_index()
    one = one.sort_index()
    four = four.sort_index()
    btc_one = (
        None
        if btc_one is None or btc_one.empty
        else btc_one.sort_index()
    )
    eth_one = (
        None
        if eth_one is None or eth_one.empty
        else eth_one.sort_index()
    )

    start_ts = pd.Timestamp(period_start)
    end_ts = pd.Timestamp(period_end)
    if start_ts.tzinfo is None:
        start_ts = start_ts.tz_localize("UTC")
    if end_ts.tzinfo is None:
        end_ts = end_ts.tz_localize("UTC")

    # Need a complete 12h directional observation window.
    cutoff = end_ts - pd.Timedelta(hours=12)
    positions = [
        i for i, ts in enumerate(one.index)
        if start_ts <= ts <= cutoff
    ]

    rows = []
    last_emit = None

    for pos in positions[::max(1, BACKTEST_STEP_HOURS)]:
        if pos < 100:
            continue

        signal_open = one.index[pos]
        signal_end = signal_open + pd.Timedelta(hours=1)

        if (
            last_emit is not None
            and signal_end - last_emit
            < pd.Timedelta(hours=BACKTEST_COOLDOWN_HOURS)
        ):
            continue

        one_slice = one.iloc[:pos + 1]
        four_closed = _closed_context(four, signal_end, 240)
        fifteen_closed = _closed_context(fifteen, signal_end, 15)
        btc_closed = _closed_context(btc_one, signal_end, 60)
        eth_closed = _closed_context(eth_one, signal_end, 60)

        if four_closed is None or len(four_closed) < 90:
            continue
        if fifteen_closed is None or len(fifteen_closed) < 40:
            continue

        try:
            base = analyze_short(
                symbol,
                {"1H": one_slice, "4H": four_closed},
                _historical_ticker(one_slice),
                fast_row=None,
            )
            candidate = build_v421_candidate(
                base,
                one_slice,
                four_closed,
                btc_closed,
                eth_closed,
            )
        except Exception:
            continue

        if candidate is None:
            continue

        future15 = fifteen.loc[fifteen.index >= signal_end]
        directional = directional_followthrough(
            candidate["current_price"],
            candidate["atr_1h"],
            future15,
        )

        row = {
            "manifest_id": manifest_id,
            "symbol": symbol,
            "signal_time": signal_end.isoformat(),
            **candidate,
            **directional,
        }
        rows.append(row)
        last_emit = signal_end

    return rows, None


def run_v421_backtest(manifest_path=None):
    manifest = load_manifest(manifest_path)
    period_start = pd.Timestamp(manifest["period_start"])
    period_end = pd.Timestamp(manifest["period_end"])
    all_symbols = list(manifest["symbols"])
    selected = _apply_manifest_shard(all_symbols)

    rows = []
    errors = []
    warmup_start = (
        period_start - pd.Timedelta(days=BACKTEST_WARMUP_DAYS)
    )

    contexts = {}
    for symbol in ("BTC_USDT", "ETH_USDT"):
        try:
            contexts[symbol] = get_klines_window(
                symbol, "1h", warmup_start, period_end
            )
        except Exception as exc:
            contexts[symbol] = None
            errors.append({
                "symbol": symbol,
                "error": f"market context: {exc}",
            })

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
            errors.append({
                "symbol": symbol,
                "error": str(exc),
            })

        print(
            f"[V4.2.1 shard "
            f"{BACKTEST_SHARD_INDEX + 1}/{BACKTEST_SHARD_COUNT}] "
            f"[{index}/{len(selected)}] {symbol}: "
            f"candidates={len(rows)} errors={len(errors)}",
            flush=True,
        )

    rows.sort(key=lambda x: (
        str(x.get("signal_time")),
        str(x.get("symbol")),
    ))

    return {
        "engine": "Crypto Short V4.2.1 Discretionary Filter",
        "manifest_id": manifest["manifest_id"],
        "manifest": manifest,
        "period_start": manifest["period_start"],
        "period_end": manifest["period_end"],
        "days": manifest["days"],
        "shard_index": int(BACKTEST_SHARD_INDEX),
        "shard_count": int(BACKTEST_SHARD_COUNT),
        "selected_symbols": selected,
        "selected_symbol_count": len(selected),
        "manifest_symbol_count": len(all_symbols),
        "settings": {
            "primary_objective": (
                "directional follow-through after recommendation"
            ),
            "ranking": (
                "directional + location + trigger "
                "- bottom risk - chase risk"
            ),
            "slippage_policy": (
                "advisory only; never a candidate hard gate"
            ),
            "entry_output": (
                "preferred entry zone + reference SL/TP; "
                "user decides actual execution"
            ),
        },
        "trades": rows,
        "errors": errors,
    }
