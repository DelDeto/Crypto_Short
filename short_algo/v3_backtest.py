"""Historical replay for V3 multi-strategy Short research."""

import math
from datetime import datetime, timedelta, timezone

import pandas as pd

from .backtest import _evaluate_outcome, _historical_ticker
from .config import (
    BACKTEST_COOLDOWN_HOURS,
    BACKTEST_DAYS,
    BACKTEST_HORIZON_HOURS,
    BACKTEST_SHARD_COUNT,
    BACKTEST_SHARD_INDEX,
    BACKTEST_STEP_HOURS,
    BACKTEST_SYMBOL_LIMIT,
    BACKTEST_WARMUP_DAYS,
    BACKTEST_FEE_BPS_ROUND_TRIP,
    BACKTEST_SLIPPAGE_BPS_ROUND_TRIP,
    V3_MAX_COST_R,
    V3_MAX_STOP_PCT,
    V3_MIN_SUPPORT_ROOM_R,
)
from .mexc import fetch_backtest_frames, get_all_tickers, get_contract_universe, get_klines_window
from .strategy import analyze_short
from .v3 import evaluate_v3_engines
from .v3_calibration import build_v3_calibration, equity_curve_metrics


def _apply_shard(selected, meta):
    count = max(1, int(BACKTEST_SHARD_COUNT))
    index = int(BACKTEST_SHARD_INDEX)
    if index < 0 or index >= count:
        raise ValueError(f"BACKTEST_SHARD_INDEX={index} outside 0..{count - 1}")
    full_count = len(selected)
    selected = selected[index::count]
    return selected, {
        **meta,
        "pre_shard_symbol_count": full_count,
        "shard_index": index,
        "shard_count": count,
        "shard_symbol_count": len(selected),
    }


def _select_symbols(symbols=None):
    universe, audit = get_contract_universe(return_audit=True)
    if symbols:
        wanted = {str(x).strip().upper() for x in symbols if str(x).strip()}
        selected = [s for s in universe if s.upper() in wanted]
        return _apply_shard(selected, {
            "selection": "explicit_crypto_only",
            "universe_count": len(universe),
            "universe_audit": audit,
        })

    tickers = get_all_tickers()
    ranked = sorted(
        [s for s in universe if s in tickers],
        key=lambda s: -float((tickers.get(s) or {}).get("turnover_24h") or 0.0),
    )
    if BACKTEST_SYMBOL_LIMIT > 0:
        ranked = ranked[:BACKTEST_SYMBOL_LIMIT]

    return _apply_shard(ranked, {
        "selection": "current_turnover_rank_crypto_only",
        "universe_count": len(universe),
        "universe_audit": audit,
        "symbol_limit": BACKTEST_SYMBOL_LIMIT,
        "bias_note": (
            "Current tradability and current turnover are used only for cohort selection. "
            "Historical signal construction does not use today's turnover/funding/spread."
        ),
    })


def _closed_context(frame, signal_end, minutes):
    if frame is None or frame.empty:
        return None
    delta = pd.Timedelta(minutes=minutes)
    return frame.loc[(frame.index + delta) <= signal_end]


def _replay_symbol(symbol, frames, period_start, period_end, btc_one, eth_one):
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
            result = analyze_short(
                symbol,
                {"1H": one_slice, "4H": four_closed},
                _historical_ticker(one_slice),
                fast_row=None,
            )
            candidates = evaluate_v3_engines(
                result,
                one_slice,
                four_closed,
                fifteen_view,
                btc_view,
                eth_view,
            )
        except Exception:
            continue

        entries = [c for c in candidates if c.get("v3_status") == "ENTRY_READY"]
        if not entries:
            continue

        executable = []
        for candidate in entries:
            engine = candidate["v3_engine"]
            last_signal = last_by_engine.get(engine)
            if last_signal is None or signal_end - last_signal >= pd.Timedelta(hours=BACKTEST_COOLDOWN_HOURS):
                executable.append(candidate)
        if not executable:
            continue

        primary_engine = max(
            executable,
            key=lambda x: (float(x.get("v3_score") or 0.0), -float(x.get("v3_projected_cost_r") or 0.0)),
        )["v3_engine"]

        for candidate in executable:
            engine = candidate["v3_engine"]
            candidate["v3_primary"] = engine == primary_engine

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
            features = candidate.get("v3_features") or {}

            trades.append({
                "symbol": symbol,
                "signal_time": signal_end.isoformat(),
                "exit_time": None if exit_time is None else exit_time.isoformat(),
                "strategy_family": "V3_CORE",
                "v3_engine": engine,
                "v3_status": candidate.get("v3_status"),
                "v3_score": candidate.get("v3_score"),
                "v3_threshold": candidate.get("v3_threshold"),
                "v3_primary": candidate.get("v3_primary"),
                "v3_regime": candidate.get("v3_regime"),
                "v3_relative_4h_pct": candidate.get("v3_relative_4h_pct"),
                "v3_relative_24h_pct": candidate.get("v3_relative_24h_pct"),
                "v3_projected_cost_r": candidate.get("v3_projected_cost_r"),
                "v3_components": candidate.get("v3_components"),
                "v3_gate": candidate.get("v3_gate"),
                "v3_reasons": candidate.get("v3_reasons"),
                "v3_micro": candidate.get("v3_micro"),
                "v3_features": features,
                "entry": entry,
                "stop": stop,
                "stop_pct": candidate.get("stop_pct"),
                "tp1": tp1,
                "tp2": tp2,
                "runner": runner,
                "support_room_r": candidate.get("support_room_r"),
                "return_4h_pct": features.get("return_4h_pct"),
                "return_12h_pct": features.get("return_12h_pct"),
                "return_24h_pct": features.get("return_24h_pct"),
                "volume_ratio_1h": features.get("volume_ratio_1h"),
                "outcome_bar_minutes": 15,
                **outcome,
            })
            last_by_engine[engine] = signal_end

    return trades, None


def run_v3_backtest(symbols=None, days=None):
    days = int(days or BACKTEST_DAYS)
    finished_at = datetime.now(timezone.utc)
    period_end = finished_at.replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
    period_start = period_end - timedelta(days=days)

    selected, selection_meta = _select_symbols(symbols)
    trades = []
    errors = []

    warmup_start = period_start - timedelta(days=BACKTEST_WARMUP_DAYS)
    contexts = {}
    for symbol in ("BTC_USDT", "ETH_USDT"):
        try:
            contexts[symbol] = get_klines_window(symbol, "1h", warmup_start, period_end)
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
            )
            trades.extend(symbol_trades)
            if error:
                errors.append(error)
        except Exception as exc:
            errors.append({"symbol": symbol, "error": str(exc)})

        print(
            f"[V3 shard {BACKTEST_SHARD_INDEX + 1}/{BACKTEST_SHARD_COUNT}] "
            f"[{index}/{len(selected)}] {symbol}: trades={len(trades)} errors={len(errors)}",
            flush=True,
        )

    trades.sort(key=lambda x: (str(x.get("signal_time")), str(x.get("symbol")), str(x.get("v3_engine"))))
    calibration = build_v3_calibration(trades)
    primary_entries = [
        t for t in trades
        if t.get("v3_primary") is True and t.get("v3_status") == "ENTRY_READY"
    ]

    return {
        "engine": "Crypto Short V3 Multi-Strategy Backtest",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "days": days,
        "shard_index": BACKTEST_SHARD_INDEX,
        "shard_count": BACKTEST_SHARD_COUNT,
        "selected_symbols": selected,
        "selected_symbol_count": len(selected),
        "selection_meta": selection_meta,
        "settings": {
            "cooldown_hours": BACKTEST_COOLDOWN_HOURS,
            "horizon_hours": BACKTEST_HORIZON_HOURS,
            "step_hours": BACKTEST_STEP_HOURS,
            "fee_bps_round_trip": BACKTEST_FEE_BPS_ROUND_TRIP,
            "slippage_bps_round_trip": BACKTEST_SLIPPAGE_BPS_ROUND_TRIP,
            "v3_max_cost_r": V3_MAX_COST_R,
            "v3_max_stop_pct": V3_MAX_STOP_PCT,
            "v3_min_support_room_r": V3_MIN_SUPPORT_ROOM_R,
            "context_timeframes": "4H/1H + BTC/ETH 1H",
            "trigger_timeframe": "15M",
            "tp1_rule": "+2R before -1R",
            "same_bar_rule": "conservative_loss",
            "terminal_exit": f"close at {BACKTEST_HORIZON_HOURS}h if neither TP1 nor SL hits",
            "historical_oi_funding": "disabled until timestamp-correct history is available",
        },
        "calibration": calibration,
        "entry_equity_sequence": equity_curve_metrics(primary_entries),
        "trades": trades,
        "errors": errors,
    }
