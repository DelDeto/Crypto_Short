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
)
from .indicators import return_pct
from .mexc import fetch_backtest_frames, get_all_tickers, get_contract_universe
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


def _evaluate_outcome(entry, stop, tp1, tp2, runner, future, horizon_hours):
    risk = float(stop) - float(entry)
    if risk <= 0:
        return {
            "outcome": "INVALID_RISK",
            "realized_r": 0.0,
            "mae_r": None,
            "mfe_r": None,
            "bars_to_outcome": None,
            "ambiguous_same_bar": False,
            "tp2_touched": False,
            "runner_touched": False,
        }

    future = future.head(max(1, int(horizon_hours)))
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
            # Intrabar ordering is unknowable from OHLC. Conservative rule:
            # count the setup as a loss instead of assuming TP was first.
            return {
                "outcome": "LOSS",
                "realized_r": -1.0,
                "mae_r": round(max_adverse, 4),
                "mfe_r": round(max_favorable, 4),
                "bars_to_outcome": bars,
                "ambiguous_same_bar": True,
                "tp2_touched": tp2_touched,
                "runner_touched": runner_touched,
            }
        if hit_sl:
            return {
                "outcome": "LOSS",
                "realized_r": -1.0,
                "mae_r": round(max_adverse, 4),
                "mfe_r": round(max_favorable, 4),
                "bars_to_outcome": bars,
                "ambiguous_same_bar": False,
                "tp2_touched": tp2_touched,
                "runner_touched": runner_touched,
            }
        if hit_tp1:
            return {
                "outcome": "WIN",
                "realized_r": 2.0,
                "mae_r": round(max_adverse, 4),
                "mfe_r": round(max_favorable, 4),
                "bars_to_outcome": bars,
                "ambiguous_same_bar": False,
                "tp2_touched": tp2_touched,
                "runner_touched": runner_touched,
            }

    return {
        "outcome": "UNRESOLVED",
        "realized_r": 0.0,
        "mae_r": round(max_adverse, 4),
        "mfe_r": round(max_favorable, 4),
        "bars_to_outcome": len(future),
        "ambiguous_same_bar": False,
        "tp2_touched": tp2_touched,
        "runner_touched": runner_touched,
    }


def _replay_symbol(symbol, frames, period_start, period_end):
    one = frames.get("1H")
    four = frames.get("4H")
    if one is None or four is None or one.empty or four.empty:
        return [], {"symbol": symbol, "error": "missing historical frames"}

    one = one.sort_index()
    four = four.sort_index()
    trades = []
    last_signal_by_model = {}

    start_ts = pd.Timestamp(period_start)
    end_ts = pd.Timestamp(period_end)
    if start_ts.tzinfo is None:
        start_ts = start_ts.tz_localize("UTC")
    if end_ts.tzinfo is None:
        end_ts = end_ts.tz_localize("UTC")

    eligible_positions = [
        i for i, ts in enumerate(one.index)
        if start_ts <= ts <= end_ts
    ]

    for pos in eligible_positions[::max(1, BACKTEST_STEP_HOURS)]:
        if pos < 100:
            continue

        signal_open = one.index[pos]
        signal_end = signal_open + pd.Timedelta(hours=1)

        one_slice = one.iloc[:pos + 1]
        four_closed = four.loc[(four.index + pd.Timedelta(hours=4)) <= signal_end]
        if len(four_closed) < 90:
            continue

        ticker = _historical_ticker(one_slice)
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
        if score < BACKTEST_MIN_SCORE:
            continue
        if result.get("status") not in ("WATCH", "DEVELOPING", "ENTRY_READY"):
            continue

        ret24 = return_pct(one_slice["close"], 24)
        model_info = classify_short_model(result, return_24h_pct=ret24)
        model = model_info["model"]

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

        trade = {
            "symbol": symbol,
            "signal_time": signal_end.isoformat(),
            "status": result.get("status"),
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
    equity = equity_curve_metrics(trades)

    return {
        "engine": "Crypto Short Scanner V2 Backtest",
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
        },
        "calibration": calibration,
        "equity_sequence": equity,
        "trades": trades,
        "errors": errors,
    }
