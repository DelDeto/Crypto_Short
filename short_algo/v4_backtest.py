"""Historical candidate replay for V4.

Each shard consumes one frozen manifest. It generates timestamp-safe rule
candidates and outcomes only. Meta-model fitting happens after all shards merge.
"""

import json
import math
import os
from datetime import timedelta

import pandas as pd

from .backtest import _evaluate_outcome, _historical_ticker
from .config import (
    BACKTEST_COOLDOWN_HOURS,
    BACKTEST_HORIZON_HOURS,
    BACKTEST_SHARD_COUNT,
    BACKTEST_SHARD_INDEX,
    BACKTEST_STEP_HOURS,
    BACKTEST_WARMUP_DAYS,
)
from .mexc import fetch_backtest_frames, get_klines_window
from .strategy import analyze_short
from .v3 import evaluate_v3_engines
from .v4_features import build_v4_features
from .v4_regime import route_v4_regime


def load_manifest(path=None):
    path = path or os.getenv("V4_MANIFEST_PATH", "output/v4_manifest.json")
    with open(path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not manifest.get("manifest_id"):
        raise RuntimeError("V4 manifest missing manifest_id")
    if not manifest.get("symbols"):
        raise RuntimeError("V4 manifest contains no symbols")
    return manifest


def _closed_context(frame, signal_end, minutes):
    if frame is None or frame.empty:
        return None
    delta = pd.Timedelta(minutes=minutes)
    return frame.loc[(frame.index + delta) <= signal_end]


def _apply_manifest_shard(symbols):
    count = max(1, int(BACKTEST_SHARD_COUNT))
    index = int(BACKTEST_SHARD_INDEX)
    if index < 0 or index >= count:
        raise ValueError(f"BACKTEST_SHARD_INDEX={index} outside 0..{count - 1}")
    return list(symbols)[index::count]


def _replay_symbol(symbol, frames, period_start, period_end, btc_one, eth_one, manifest_id):
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
    btc_one = None if btc_one is None or btc_one.empty else btc_one.sort_index()
    eth_one = None if eth_one is None or eth_one.empty else eth_one.sort_index()

    start_ts = pd.Timestamp(period_start)
    end_ts = pd.Timestamp(period_end)
    if start_ts.tzinfo is None:
        start_ts = start_ts.tz_localize("UTC")
    if end_ts.tzinfo is None:
        end_ts = end_ts.tz_localize("UTC")

    cutoff = end_ts - pd.Timedelta(hours=BACKTEST_HORIZON_HOURS)
    positions = [i for i, ts in enumerate(one.index) if start_ts <= ts <= cutoff]

    trades = []
    last_by_engine = {}

    for pos in positions[::max(1, BACKTEST_STEP_HOURS)]:
        if pos < 100:
            continue

        signal_open = one.index[pos]
        signal_end = signal_open + pd.Timedelta(hours=1)
        one_slice = one.iloc[:pos + 1]
        four_closed = _closed_context(four, signal_end, 240)
        fifteen_closed = _closed_context(fifteen, signal_end, 15)
        btc_closed = _closed_context(btc_one, signal_end, 60)
        eth_closed = _closed_context(eth_one, signal_end, 60)

        if four_closed is None or len(four_closed) < 90:
            continue
        if fifteen_closed is None or len(fifteen_closed) < 40:
            continue

        fifteen_view = fifteen_closed.tail(180)
        btc_view = None if btc_closed is None else btc_closed.tail(180)
        eth_view = None if eth_closed is None else eth_closed.tail(180)

        try:
            base = analyze_short(
                symbol,
                {"1H": one_slice, "4H": four_closed},
                _historical_ticker(one_slice),
                fast_row=None,
            )
            candidates = evaluate_v3_engines(
                base,
                one_slice,
                four_closed,
                fifteen_view,
                btc_view,
                eth_view,
            )
        except Exception:
            continue

        # V4 meta-labels only candidates that pass the rule engine's structural
        # and execution hard gates. Rule score no longer decides final entry.
        candidates = [
            c for c in candidates
            if c.get("v3_status") == "ENTRY_READY"
        ]
        if not candidates:
            continue

        regime = route_v4_regime(btc_view, eth_view, one_slice)

        for candidate in candidates:
            engine = candidate.get("v3_engine")
            last_signal = last_by_engine.get(engine)
            if (
                last_signal is not None
                and signal_end - last_signal < pd.Timedelta(hours=BACKTEST_COOLDOWN_HOURS)
            ):
                continue

            entry = float(candidate["entry"])
            stop = float(candidate["stop"])
            tp1 = float(candidate["tp1"])
            tp2 = float(candidate["tp2"])
            runner = float(candidate["runner"])
            if not all(math.isfinite(x) for x in (entry, stop, tp1, tp2, runner)):
                continue
            if stop <= entry:
                continue

            future15 = fifteen.loc[fifteen.index >= signal_end]
            outcome = _evaluate_outcome(
                entry,
                stop,
                tp1,
                tp2,
                runner,
                future15,
                BACKTEST_HORIZON_HOURS,
                bars_per_hour=4,
            )
            bars = int(outcome.get("bars_to_outcome") or 0)
            exit_time = (
                signal_end + pd.Timedelta(minutes=15 * bars)
                if bars > 0 else None
            )

            features = build_v4_features(candidate, one_slice, regime)
            trades.append({
                "manifest_id": manifest_id,
                "symbol": symbol,
                "signal_time": signal_end.isoformat(),
                "exit_time": None if exit_time is None else exit_time.isoformat(),
                "strategy_family": "V4_RAW_CANDIDATE",
                "v3_engine": engine,
                "v3_score": candidate.get("v3_score"),
                "v3_threshold": candidate.get("v3_threshold"),
                "v3_projected_cost_r": candidate.get("v3_projected_cost_r"),
                "v3_relative_4h_pct": candidate.get("v3_relative_4h_pct"),
                "v3_relative_24h_pct": candidate.get("v3_relative_24h_pct"),
                "v3_micro": candidate.get("v3_micro"),
                "v4_regime_key": regime.get("regime_key"),
                "v4_risk_state": regime.get("risk_state"),
                "v4_trend_state": regime.get("trend_state"),
                "v4_vol_state": regime.get("vol_state"),
                "v4_local_vol_state": regime.get("local_vol_state"),
                "v4_features": features,
                "entry": entry,
                "stop": stop,
                "stop_pct": candidate.get("stop_pct"),
                "tp1": tp1,
                "tp2": tp2,
                "runner": runner,
                "support_room_r": candidate.get("support_room_r"),
                "outcome_bar_minutes": 15,
                **outcome,
            })
            last_by_engine[engine] = signal_end

    return trades, None


def run_v4_backtest(manifest_path=None):
    manifest = load_manifest(manifest_path)
    period_start = pd.Timestamp(manifest["period_start"])
    period_end = pd.Timestamp(manifest["period_end"])
    all_symbols = list(manifest["symbols"])
    selected = _apply_manifest_shard(all_symbols)

    trades = []
    errors = []
    warmup_start = period_start - pd.Timedelta(days=BACKTEST_WARMUP_DAYS)

    contexts = {}
    for symbol in ("BTC_USDT", "ETH_USDT"):
        try:
            contexts[symbol] = get_klines_window(
                symbol, "1h", warmup_start, period_end
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
            symbol_trades, error = _replay_symbol(
                symbol,
                frames,
                period_start,
                period_end,
                contexts.get("BTC_USDT"),
                contexts.get("ETH_USDT"),
                manifest["manifest_id"],
            )
            trades.extend(symbol_trades)
            if error:
                errors.append(error)
        except Exception as exc:
            errors.append({"symbol": symbol, "error": str(exc)})

        print(
            f"[V4 shard {BACKTEST_SHARD_INDEX + 1}/{BACKTEST_SHARD_COUNT}] "
            f"[{index}/{len(selected)}] {symbol}: "
            f"candidates={len(trades)} errors={len(errors)}",
            flush=True,
        )

    trades.sort(key=lambda x: (
        str(x.get("signal_time")),
        str(x.get("symbol")),
        str(x.get("v3_engine")),
    ))

    return {
        "engine": "Crypto Short V4 Raw Candidate Replay",
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
            "cooldown_hours": BACKTEST_COOLDOWN_HOURS,
            "horizon_hours": BACKTEST_HORIZON_HOURS,
            "step_hours": BACKTEST_STEP_HOURS,
            "candidate_source": "V3 independent rule engines; ENTRY_READY hard-gate candidates only",
            "meta_model": "fit only after all shards merge",
            "trigger_timeframe": "15M",
            "context_timeframes": "4H/1H + BTC/ETH 1H",
        },
        "trades": trades,
        "errors": errors,
    }
