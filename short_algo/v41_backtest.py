"""V4.1 frozen replay focused on entry quality and stop diagnostics."""

import math

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
from .v4_backtest import load_manifest, _closed_context
from .v41_config import V41_ENTRY_WAIT_HOURS
from .v41_diagnostics import entry_followthrough, post_stop_reversal
from .v41_entry import build_short_entry_zone, simulate_confirmed_retest


def _apply_manifest_shard(symbols):
    count = max(1, int(BACKTEST_SHARD_COUNT))
    index = int(BACKTEST_SHARD_INDEX)
    if index < 0 or index >= count:
        raise ValueError(f"BACKTEST_SHARD_INDEX={index} outside 0..{count - 1}")
    return list(symbols)[index::count]


def _prefix(prefix, payload):
    return {f"{prefix}{key}": value for key, value in (payload or {}).items()}


def _eligible_candidate(candidate):
    gate = candidate.get("v3_gate") or {}
    # V4.1 intentionally re-evaluates location, stop and support room after
    # the optimized entry is found. Do not let the old signal-price risk gate
    # reject an otherwise valid location-first setup.
    return bool(
        gate.get("engine_hard_gate")
        and gate.get("cost_ok")
    )


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

    # Preserve a complete outcome window even for entries that wait for a retest.
    cutoff = end_ts - pd.Timedelta(
        hours=BACKTEST_HORIZON_HOURS + V41_ENTRY_WAIT_HOURS
    )
    positions = [i for i, ts in enumerate(one.index) if start_ts <= ts <= cutoff]

    rows = []
    last_setup_by_engine = {}

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

        candidates = [c for c in candidates if _eligible_candidate(c)]
        if not candidates:
            continue

        future15_from_signal = fifteen.loc[fifteen.index >= signal_end]

        for candidate in candidates:
            engine = str(candidate.get("v3_engine") or "UNKNOWN")
            last_setup = last_setup_by_engine.get(engine)
            if (
                last_setup is not None
                and signal_end - last_setup < pd.Timedelta(hours=BACKTEST_COOLDOWN_HOURS)
            ):
                continue
            last_setup_by_engine[engine] = signal_end

            base_entry = float(candidate["entry"])
            base_stop = float(candidate["stop"])
            base_tp1 = float(candidate["tp1"])
            base_tp2 = float(candidate["tp2"])
            base_runner = float(candidate["runner"])
            if (
                base_stop <= base_entry
                or not all(math.isfinite(v) for v in (
                    base_entry, base_stop, base_tp1, base_tp2, base_runner
                ))
            ):
                continue

            baseline_outcome = _evaluate_outcome(
                base_entry,
                base_stop,
                base_tp1,
                base_tp2,
                base_runner,
                future15_from_signal,
                BACKTEST_HORIZON_HOURS,
                bars_per_hour=4,
            )
            baseline_risk = base_stop - base_entry
            baseline_ft = entry_followthrough(
                base_entry, baseline_risk, future15_from_signal
            )
            baseline_post = {}
            if baseline_outcome.get("outcome") == "LOSS":
                baseline_post = post_stop_reversal(
                    base_entry,
                    base_stop,
                    base_tp1,
                    future15_from_signal,
                    baseline_outcome.get("bars_to_outcome"),
                )

            zone = build_short_entry_zone(candidate, base, one_slice)
            optimized = simulate_confirmed_retest(
                zone,
                future15_from_signal,
                nearest_support=base.get("nearest_support"),
                fifteen_history=fifteen_view,
            )
            optimized_filled = bool(optimized and optimized.get("filled"))

            record = {
                "manifest_id": manifest_id,
                "symbol": symbol,
                "signal_time": signal_end.isoformat(),
                "v3_engine": engine,
                "v3_score": candidate.get("v3_score"),
                "v3_status": candidate.get("v3_status"),
                "v3_projected_cost_r": candidate.get("v3_projected_cost_r"),
                "setup_hard_gate": True,
                "signal_entry": base_entry,
                "signal_stop": base_stop,
                "signal_tp1": base_tp1,
                "signal_stop_pct": candidate.get("stop_pct"),
                "nearest_support": base.get("nearest_support"),
                "optimized_entry_filled": optimized_filled,
                "entry_status": (
                    "CONFIRMED_RETEST_ENTRY"
                    if optimized_filled
                    else str((optimized or {}).get("reject_reason") or "NO_VALID_ZONE")
                ),
                "entry_reject_reason": None if optimized_filled else (optimized or {}).get("reject_reason"),
                "entry_state_at_reject": None if optimized_filled else (optimized or {}).get("state"),
                "zone_source": None if zone is None else zone.get("source"),
                "zone_lower": None if zone is None else zone.get("lower"),
                "zone_upper": None if zone is None else zone.get("upper"),
                "zone_mid": None if zone is None else zone.get("mid"),
                "zone_prior_touch_count": None if zone is None else zone.get("prior_touch_count"),
                "zone_age_1h_bars": None if zone is None else zone.get("age_1h_bars"),
                "zone_location_quality": None if zone is None else zone.get("location_quality"),
                "zone_freshness_reason": None if zone is None else zone.get("freshness_reason"),
                "ideal_entry": None if zone is None else zone.get("ideal_entry"),
                "baseline_outcome": baseline_outcome.get("outcome"),
                "baseline_realized_r": baseline_outcome.get("realized_r"),
                "baseline_cost_r": baseline_outcome.get("cost_r"),
                "baseline_mae_r": baseline_outcome.get("mae_r"),
                "baseline_mfe_r": baseline_outcome.get("mfe_r"),
                **_prefix("baseline_", baseline_ft),
                **_prefix("baseline_", baseline_post),
            }

            if not optimized_filled:
                rows.append(record)
                continue

            entry_ts = pd.Timestamp(optimized["entry_time"])
            future15_from_entry = fifteen.loc[fifteen.index >= entry_ts]
            outcome = _evaluate_outcome(
                optimized["entry"],
                optimized["stop"],
                optimized["tp1"],
                optimized["tp2"],
                optimized["runner"],
                future15_from_entry,
                BACKTEST_HORIZON_HOURS,
                bars_per_hour=4,
            )
            bars = int(outcome.get("bars_to_outcome") or 0)
            exit_time = (
                entry_ts + pd.Timedelta(minutes=15 * bars)
                if bars > 0 else None
            )

            ft = entry_followthrough(
                optimized["entry"],
                optimized["risk"],
                future15_from_entry,
            )
            post = {}
            if outcome.get("outcome") == "LOSS":
                post = post_stop_reversal(
                    optimized["entry"],
                    optimized["stop"],
                    optimized["tp1"],
                    future15_from_entry,
                    outcome.get("bars_to_outcome"),
                )

            record.update({
                "entry_time": optimized["entry_time"],
                "exit_time": None if exit_time is None else exit_time.isoformat(),
                "entry": optimized["entry"],
                "stop": optimized["stop"],
                "risk": optimized["risk"],
                "stop_pct": optimized["stop_pct"],
                "tp1": optimized["tp1"],
                "tp2": optimized["tp2"],
                "runner": optimized["runner"],
                "support_room_r": optimized["support_room_r"],
                "entry_improvement_atr": optimized["entry_improvement_atr"],
                "confirmation_score": optimized["confirmation_score"],
                "wait_bars_15m": optimized["wait_bars_15m"],
                "bos_level": optimized.get("bos_level"),
                "bos_bar": optimized.get("bos_bar"),
                "touch_bar": optimized.get("touch_bar"),
                "structure_sequence": optimized.get("structure_sequence"),
                "zone_prior_touch_count": optimized.get("zone_prior_touch_count"),
                "zone_age_1h_bars": optimized.get("zone_age_1h_bars"),
                "zone_location_quality": optimized.get("zone_location_quality"),
                "zone_freshness_reason": optimized.get("zone_freshness_reason"),
                "outcome_bar_minutes": 15,
                **outcome,
                **ft,
                **post,
            })
            rows.append(record)

    return rows, None


def run_v41_backtest(manifest_path=None):
    manifest = load_manifest(manifest_path)
    period_start = pd.Timestamp(manifest["period_start"])
    period_end = pd.Timestamp(manifest["period_end"])
    all_symbols = list(manifest["symbols"])
    selected = _apply_manifest_shard(all_symbols)

    rows = []
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
            f"[V4.1 shard {BACKTEST_SHARD_INDEX + 1}/{BACKTEST_SHARD_COUNT}] "
            f"[{index}/{len(selected)}] {symbol}: setups={len(rows)} errors={len(errors)}",
            flush=True,
        )

    rows.sort(key=lambda x: (
        str(x.get("signal_time")),
        str(x.get("symbol")),
        str(x.get("v3_engine")),
    ))
    return {
        "engine": "Crypto Short V4.1 Entry Quality Replay",
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
            "candidate_gate": "V3 engine hard gate + cost gate; V4.1 re-evaluates stop/support risk after optimized entry",
            "entry_method": "fresh valid zone -> touch -> 15m bearish BOS -> failed retest -> bearish confirmation close",
            "entry_wait_hours": V41_ENTRY_WAIT_HOURS,
            "outcome_horizon_hours": BACKTEST_HORIZON_HOURS,
            "post_sl_observation_hours": 72,
        },
        "trades": rows,
        "errors": errors,
    }
