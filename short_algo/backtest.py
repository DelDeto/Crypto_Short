import math
from datetime import datetime, timedelta, timezone

import pandas as pd

from .calibration_v2 import build_calibration, equity_curve_metrics
from .config import (
    BACKTEST_COOLDOWN_HOURS,
    BACKTEST_DAYS,
    BACKTEST_HORIZON_HOURS,
    BACKTEST_MIN_SCORE,
    BACKTEST_STEP_HOURS,
    BACKTEST_SYMBOL_LIMIT,
    BACKTEST_WARMUP_DAYS,
    BACKTEST_SHARD_INDEX,
    BACKTEST_SHARD_COUNT,
    BACKTEST_FEE_BPS_ROUND_TRIP,
    BACKTEST_SLIPPAGE_BPS_ROUND_TRIP,
)
from .indicators import return_pct
from .baselines import bollinger_reversal_short
from .v21 import classify_v21_status
from .v22 import score_v22
from .mexc import (
    fetch_backtest_frames,
    get_all_tickers,
    get_contract_universe,
    get_klines_window,
)
from .models import classify_short_model
from .strategy import analyze_short


def _historical_ticker(one_hour_frame):
    close = one_hour_frame["close"].astype(float)
    change = 0.0
    if len(close) > 24:
        start = float(close.iloc[-25])
        end = float(close.iloc[-1])
        if start:
            change = end / start - 1.0

    # Historical funding/spread/turnover snapshots are intentionally not
    # injected from today's ticker. Doing so would create look-ahead bias.
    return {
        "last_price": float(close.iloc[-1]),
        "change_rate_24h": change,
        "turnover_24h": 0.0,
        "spread_bps": None,
        "funding_rate": None,
        "hold_vol": None,
    }


def _apply_shard(selected, meta):
    shard_count = max(1, int(BACKTEST_SHARD_COUNT))
    shard_index = int(BACKTEST_SHARD_INDEX)
    if shard_index < 0 or shard_index >= shard_count:
        raise ValueError(
            f"BACKTEST_SHARD_INDEX={shard_index} outside 0..{shard_count - 1}"
        )

    full_count = len(selected)
    sharded = selected[shard_index::shard_count]
    meta = {
        **meta,
        "pre_shard_symbol_count": full_count,
        "shard_index": shard_index,
        "shard_count": shard_count,
        "shard_symbol_count": len(sharded),
    }
    return sharded, meta


def _select_symbols(symbols=None):
    universe = get_contract_universe()
    if symbols:
        wanted = {str(s).strip().upper() for s in symbols if str(s).strip()}
        selected = [s for s in universe if s.upper() in wanted]
        return _apply_shard(selected, {
            "selection": "explicit",
            "universe_count": len(universe),
        })

    tickers = get_all_tickers()
    ranked = sorted(
        [s for s in universe if s in tickers],
        key=lambda s: -float((tickers.get(s) or {}).get("turnover_24h") or 0.0),
    )

    if BACKTEST_SYMBOL_LIMIT > 0:
        ranked = ranked[:BACKTEST_SYMBOL_LIMIT]

    return _apply_shard(ranked, {
        "selection": "current_turnover_rank",
        "universe_count": len(universe),
        "symbol_limit": BACKTEST_SYMBOL_LIMIT,
        "bias_note": (
            "Universe uses currently tradable contracts and current turnover only "
            "for sample selection. Historical signal scoring does not use today's "
            "turnover/funding/spread."
        ),
    })


def _evaluate_outcome(
    entry, stop, tp1, tp2, runner, future, horizon_hours, bars_per_hour=1
):
    risk = float(stop) - float(entry)
    if risk <= 0:
        return {
            "outcome": "INVALID_RISK",
            "realized_r": None,
            "gross_r": None,
            "cost_r": None,
            "mae_r": None,
            "mfe_r": None,
            "bars_to_outcome": None,
            "ambiguous_same_bar": False,
            "tp2_touched": False,
            "runner_touched": False,
        }

    horizon = max(1, int(horizon_hours))
    bars_per_hour = max(1, int(bars_per_hour))
    future = future.head(horizon * bars_per_hour)
    total_cost_bps = (
        float(BACKTEST_FEE_BPS_ROUND_TRIP)
        + float(BACKTEST_SLIPPAGE_BPS_ROUND_TRIP)
    )
    cost_r = (float(entry) * total_cost_bps / 10000.0) / risk

    max_adverse = 0.0
    max_favorable = 0.0
    tp2_touched = False
    runner_touched = False

    for bars, (_, row) in enumerate(future.iterrows(), start=1):
        high = float(row["high"])
        low = float(row["low"])

        max_adverse = max(max_adverse, max(0.0, high - entry) / risk)
        max_favorable = max(max_favorable, max(0.0, entry - low) / risk)
        tp2_touched = tp2_touched or low <= float(tp2)
        runner_touched = runner_touched or low <= float(runner)

        hit_sl = high >= float(stop)
        hit_tp1 = low <= float(tp1)

        if hit_sl and hit_tp1:
            gross_r = -1.0
            return {
                "outcome": "LOSS",
                "realized_r": round(gross_r - cost_r, 4),
                "gross_r": gross_r,
                "cost_r": round(cost_r, 4),
                "mae_r": round(max_adverse, 4),
                "mfe_r": round(max_favorable, 4),
                "bars_to_outcome": bars,
                "ambiguous_same_bar": True,
                "tp2_touched": tp2_touched,
                "runner_touched": runner_touched,
            }
        if hit_sl:
            gross_r = -1.0
            return {
                "outcome": "LOSS",
                "realized_r": round(gross_r - cost_r, 4),
                "gross_r": gross_r,
                "cost_r": round(cost_r, 4),
                "mae_r": round(max_adverse, 4),
                "mfe_r": round(max_favorable, 4),
                "bars_to_outcome": bars,
                "ambiguous_same_bar": False,
                "tp2_touched": tp2_touched,
                "runner_touched": runner_touched,
            }
        if hit_tp1:
            gross_r = 2.0
            return {
                "outcome": "WIN",
                "realized_r": round(gross_r - cost_r, 4),
                "gross_r": gross_r,
                "cost_r": round(cost_r, 4),
                "mae_r": round(max_adverse, 4),
                "mfe_r": round(max_favorable, 4),
                "bars_to_outcome": bars,
                "ambiguous_same_bar": False,
                "tp2_touched": tp2_touched,
                "runner_touched": runner_touched,
            }

    if future.empty:
        return {
            "outcome": "UNRESOLVED",
            "realized_r": None,
            "gross_r": None,
            "cost_r": round(cost_r, 4),
            "mae_r": None,
            "mfe_r": None,
            "bars_to_outcome": 0,
            "ambiguous_same_bar": False,
            "tp2_touched": False,
            "runner_touched": False,
        }

    terminal_close = float(future["close"].iloc[-1])
    gross_r = (float(entry) - terminal_close) / risk
    net_r = gross_r - cost_r
    return {
        "outcome": "TIME_EXIT_WIN" if net_r > 0 else "TIME_EXIT_LOSS",
        "realized_r": round(net_r, 4),
        "gross_r": round(gross_r, 4),
        "cost_r": round(cost_r, 4),
        "terminal_close": terminal_close,
        "mae_r": round(max_adverse, 4),
        "mfe_r": round(max_favorable, 4),
        "bars_to_outcome": len(future),
        "ambiguous_same_bar": False,
        "tp2_touched": tp2_touched,
        "runner_touched": runner_touched,
    }

def _replay_symbol(symbol, frames, period_start, period_end, btc_one=None):
    fifteen = frames.get("15M")
    one = frames.get("1H")
    four = frames.get("4H")
    if one is None or four is None or one.empty or four.empty:
        return [], {"symbol": symbol, "error": "missing historical frames"}

    fifteen = None if fifteen is None or fifteen.empty else fifteen.sort_index()
    one = one.sort_index()
    four = four.sort_index()
    btc_one = None if btc_one is None or btc_one.empty else btc_one.sort_index()
    trades = []
    last_signal_by_model = {}

    start_ts = pd.Timestamp(period_start)
    end_ts = pd.Timestamp(period_end)
    if start_ts.tzinfo is None:
        start_ts = start_ts.tz_localize("UTC")
    if end_ts.tzinfo is None:
        end_ts = end_ts.tz_localize("UTC")

    outcome_cutoff = end_ts - pd.Timedelta(hours=BACKTEST_HORIZON_HOURS)
    eligible_positions = [
        i for i, ts in enumerate(one.index)
        if start_ts <= ts <= outcome_cutoff
    ]

    for pos in eligible_positions[::max(1, BACKTEST_STEP_HOURS)]:
        if pos < 100:
            continue

        signal_open = one.index[pos]
        signal_end = signal_open + pd.Timedelta(hours=1)

        one_slice = one.iloc[:pos + 1]
        four_closed = four.loc[(four.index + pd.Timedelta(hours=4)) <= signal_end]
        fifteen_closed = None
        if fifteen is not None:
            fifteen_closed = fifteen.loc[
                (fifteen.index + pd.Timedelta(minutes=15)) <= signal_end
            ].tail(180)
        btc_closed = None
        if btc_one is not None:
            btc_closed = btc_one.loc[
                (btc_one.index + pd.Timedelta(hours=1)) <= signal_end
            ].tail(180)
        if len(four_closed) < 90:
            continue

        ticker = _historical_ticker(one_slice)

        # Simple benchmark, evaluated independently of the complex V2 rules.
        baseline = bollinger_reversal_short(one_slice)
        if baseline is not None:
            baseline_key = baseline["model"]
            last_baseline = last_signal_by_model.get(baseline_key)
            baseline_allowed = (
                last_baseline is None
                or signal_end - last_baseline >= pd.Timedelta(hours=BACKTEST_COOLDOWN_HOURS)
            )
            if baseline_allowed:
                baseline_future = one.iloc[pos + 1:]
                baseline_outcome = _evaluate_outcome(
                    float(baseline["entry"]),
                    float(baseline["stop"]),
                    float(baseline["tp1"]),
                    float(baseline["tp2"]),
                    float(baseline["runner"]),
                    baseline_future,
                    BACKTEST_HORIZON_HOURS,
                )
                trades.append({
                    "symbol": symbol,
                    "signal_time": signal_end.isoformat(),
                    **baseline,
                    **baseline_outcome,
                })
                last_signal_by_model[baseline_key] = signal_end

        try:
            result = analyze_short(
                symbol,
                {"1H": one_slice, "4H": four_closed},
                ticker,
                fast_row=None,
            )
        except Exception:
            continue

        score = float(result.get("score") or 0.0)
        ret24 = return_pct(one_slice["close"], 24)
        model_info = classify_short_model(result, return_24h_pct=ret24)
        result.update(model_info)
        result.update(classify_v21_status(result))
        result.update(score_v22(result, one_slice, fifteen_closed, btc_closed))
        model = model_info["model"]

        # V2.2 is evaluated independently from the legacy V1/V2.1 score gate.
        if result.get("v22_status") in ("DEVELOPING", "ENTRY_READY") and fifteen_closed is not None:
            v22_key = "V22_LIQUIDITY_REVERSAL"
            last_v22 = last_signal_by_model.get(v22_key)
            v22_allowed = (
                last_v22 is None
                or signal_end - last_v22 >= pd.Timedelta(hours=BACKTEST_COOLDOWN_HOURS)
            )
            if v22_allowed:
                v22_entry = float(result["v22_entry"])
                v22_stop = float(result["v22_stop"])
                v22_tp1 = float(result["v22_tp1"])
                v22_tp2 = float(result["v22_tp2"])
                v22_runner = float(result["v22_runner"])
                future15 = fifteen.loc[fifteen.index >= signal_end]
                v22_outcome = _evaluate_outcome(
                    v22_entry,
                    v22_stop,
                    v22_tp1,
                    v22_tp2,
                    v22_runner,
                    future15,
                    BACKTEST_HORIZON_HOURS,
                    bars_per_hour=4,
                )
                bars15 = int(v22_outcome.get("bars_to_outcome") or 0)
                v22_exit_time = (
                    signal_end + pd.Timedelta(minutes=15 * bars15)
                    if bars15 > 0 else None
                )
                trades.append({
                    "symbol": symbol,
                    "signal_time": signal_end.isoformat(),
                    "exit_time": None if v22_exit_time is None else v22_exit_time.isoformat(),
                    "strategy_family": "V22_CORE",
                    "status": result.get("status"),
                    "v21_status": result.get("v21_status"),
                    "v22_status": result.get("v22_status"),
                    "v22_priority": result.get("v22_priority"),
                    "v22_score": result.get("v22_score"),
                    "v22_components": result.get("v22_components"),
                    "v22_features": result.get("v22_features"),
                    "v22_gate": result.get("v22_gate"),
                    "score": round(score, 2),
                    "model": model,
                    "model_flags": model_info.get("model_flags"),
                    "top_gainer_context": model_info.get("top_gainer_context"),
                    "return_24h_pct": model_info.get("return_24h_pct"),
                    "entry": v22_entry,
                    "stop": v22_stop,
                    "stop_pct": result.get("v22_stop_pct"),
                    "tp1": v22_tp1,
                    "tp2": v22_tp2,
                    "runner": v22_runner,
                    "support_room_r": result.get("v22_support_room_r"),
                    "supply_distance_atr": result.get("supply_distance_atr"),
                    "atr_pct_1h": result.get("atr_pct_1h"),
                    "reasons": result.get("reasons"),
                    "filters": result.get("filters"),
                    "outcome_bar_minutes": 15,
                    **v22_outcome,
                })
                last_signal_by_model[v22_key] = signal_end

        if score < BACKTEST_MIN_SCORE:
            continue
        if result.get("status") not in ("WATCH", "DEVELOPING", "ENTRY_READY"):
            continue

        last_signal = last_signal_by_model.get(model)
        if last_signal is not None:
            elapsed = signal_end - last_signal
            if elapsed < pd.Timedelta(hours=BACKTEST_COOLDOWN_HOURS):
                continue

        entry = float(result["entry"])
        stop = float(result["stop"])
        tp1 = float(result["tp1"])
        tp2 = float(result["tp2"])
        runner = float(result["runner"])
        if not all(math.isfinite(x) for x in (entry, stop, tp1, tp2, runner)):
            continue
        if stop <= entry:
            continue

        future = one.iloc[pos + 1:]
        outcome = _evaluate_outcome(
            entry,
            stop,
            tp1,
            tp2,
            runner,
            future,
            BACKTEST_HORIZON_HOURS,
        )

        bars1h = int(outcome.get("bars_to_outcome") or 0)
        exit_time = signal_end + pd.Timedelta(hours=bars1h) if bars1h > 0 else None

        trade = {
            "symbol": symbol,
            "signal_time": signal_end.isoformat(),
            "exit_time": None if exit_time is None else exit_time.isoformat(),
            "strategy_family": "V21_CORE",
            "status": result.get("status"),
            "v21_status": result.get("v21_status"),
            "v21_priority": result.get("v21_priority"),
            "v21_gate": result.get("v21_gate"),
            "score": round(score, 2),
            "model": model,
            "model_flags": model_info.get("model_flags"),
            "top_gainer_context": model_info.get("top_gainer_context"),
            "return_24h_pct": model_info.get("return_24h_pct"),
            "entry": entry,
            "stop": stop,
            "stop_pct": result.get("stop_pct"),
            "tp1": tp1,
            "tp2": tp2,
            "runner": runner,
            "support_room_r": result.get("support_room_r"),
            "supply_distance_atr": result.get("supply_distance_atr"),
            "atr_pct_1h": result.get("atr_pct_1h"),
            "reasons": result.get("reasons"),
            "filters": result.get("filters"),
            "outcome_bar_minutes": 60,
            **outcome,
        }
        trades.append(trade)
        last_signal_by_model[model] = signal_end

    return trades, None


def run_backtest(symbols=None, days=None):
    days = int(days or BACKTEST_DAYS)
    finished_at = datetime.now(timezone.utc)
    # Round to a shared UTC hour so all parallel shards replay the exact
    # same historical window even if their jobs start a few minutes apart.
    period_end = finished_at.replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
    period_start = period_end - timedelta(days=days)

    selected, selection_meta = _select_symbols(symbols)
    trades = []
    errors = []

    btc_one = None
    try:
        warmup_start = period_start - timedelta(days=BACKTEST_WARMUP_DAYS)
        btc_one = get_klines_window("BTC_USDT", "1h", warmup_start, period_end)
    except Exception as exc:
        errors.append({"symbol": "BTC_USDT", "error": f"market regime context: {exc}"})

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
                btc_one=btc_one,
            )
            trades.extend(symbol_trades)
            if error:
                errors.append(error)
        except Exception as exc:
            errors.append({"symbol": symbol, "error": str(exc)})

        print(
            f"[shard {BACKTEST_SHARD_INDEX + 1}/{BACKTEST_SHARD_COUNT}] "
            f"[{index}/{len(selected)}] {symbol}: "
            f"total signals={len(trades)} errors={len(errors)}",
            flush=True,
        )

    trades.sort(key=lambda x: (str(x.get("signal_time")), x.get("symbol", "")))
    calibration = build_calibration(trades)

    core_trades = [
        trade for trade in trades
        if trade.get("strategy_family") == "V21_CORE"
    ]
    v21_entry_trades = [
        trade for trade in core_trades
        if trade.get("v21_status") == "ENTRY_READY"
    ]
    baseline_trades = [
        trade for trade in trades
        if trade.get("strategy_family") == "BOLLINGER_BASELINE"
    ]

    equity = equity_curve_metrics(core_trades)
    v21_equity = equity_curve_metrics(v21_entry_trades)
    baseline_equity = equity_curve_metrics(baseline_trades)

    return {
        "engine": "Crypto Short Scanner V2.2 Backtest",
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
            "min_score": BACKTEST_MIN_SCORE,
            "cooldown_hours": BACKTEST_COOLDOWN_HOURS,
            "horizon_hours": BACKTEST_HORIZON_HOURS,
            "step_hours": BACKTEST_STEP_HOURS,
            "tp1_rule": "+2R before -1R",
            "same_bar_rule": "conservative_loss",
            "terminal_exit": f"close at {BACKTEST_HORIZON_HOURS}h if neither TP1 nor SL hits",
            "fee_bps_round_trip": BACKTEST_FEE_BPS_ROUND_TRIP,
            "slippage_bps_round_trip": BACKTEST_SLIPPAGE_BPS_ROUND_TRIP,
        },
        "calibration": calibration,
        "equity_sequence": equity,
        "v21_equity_sequence": v21_equity,
        "baseline_equity_sequence": baseline_equity,
        "trades": trades,
        "errors": errors,
    }
