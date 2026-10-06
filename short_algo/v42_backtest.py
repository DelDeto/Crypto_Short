"""V4.2 frozen replay for structural Short validation."""

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
from .indicators import atr
from .mexc import fetch_backtest_frames, get_klines_window
from .strategy import analyze_short
from .v4_backtest import load_manifest, _closed_context
from .v42_config import V42_ENTRY_WAIT_HOURS
from .v42_diagnostics import entry_followthrough, post_stop_reversal
from .v42_entry import build_v42_zone, simulate_v42_entry
from .v42_setup import route_v42_setup


def _apply_manifest_shard(symbols):
    count = max(1, int(BACKTEST_SHARD_COUNT))
    index = int(BACKTEST_SHARD_INDEX)
    if index < 0 or index >= count:
        raise ValueError(f"BACKTEST_SHARD_INDEX={index} outside 0..{count - 1}")
    return list(symbols)[index::count]


def _prefix(prefix, payload):
    return {f"{prefix}{k}": v for k, v in (payload or {}).items()}


def _signal_baseline_plan(fifteen_history):
    if fifteen_history is None or len(fifteen_history) < 20:
        return None
    entry = float(fifteen_history["close"].iloc[-1])
    a15 = float(atr(fifteen_history).iloc[-1])
    if not math.isfinite(a15) or a15 <= 0:
        return None
    recent_high = float(fifteen_history["high"].tail(12).max())
    risk = max(
        recent_high + 0.30 * a15 - entry,
        1.0 * a15,
    )
    if risk <= 0:
        return None
    return {
        "entry": entry,
        "stop": entry + risk,
        "risk": risk,
        "tp1": entry - 2.0 * risk,
        "tp2": entry - 3.0 * risk,
        "runner": entry - 5.0 * risk,
    }


def _outcome_bundle(plan, future15):
    if plan is None:
        return {}, {}, {}
    outcome = _evaluate_outcome(
        plan["entry"],
        plan["stop"],
        plan["tp1"],
        plan["tp2"],
        plan["runner"],
        future15,
        BACKTEST_HORIZON_HOURS,
        bars_per_hour=4,
    )
    ft = entry_followthrough(plan["entry"], plan["risk"], future15)
    post = {}
    if outcome.get("outcome") == "LOSS":
        post = post_stop_reversal(
            plan["entry"],
            plan["stop"],
            plan["tp1"],
            future15,
            outcome.get("bars_to_outcome"),
        )
    return outcome, ft, post


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

    cutoff = end_ts - pd.Timedelta(
        hours=BACKTEST_HORIZON_HOURS + V42_ENTRY_WAIT_HOURS
    )
    positions = [i for i, ts in enumerate(one.index) if start_ts <= ts <= cutoff]

    rows = []
    last_setup_time = None

    for pos in positions[::max(1, BACKTEST_STEP_HOURS)]:
        if pos < 100:
            continue

        signal_open = one.index[pos]
        signal_end = signal_open + pd.Timedelta(hours=1)
        if (
            last_setup_time is not None
            and signal_end - last_setup_time
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
        if fifteen_closed is None or len(fifteen_closed) < 60:
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
            setup = route_v42_setup(
                base,
                one_slice,
                four_closed,
                btc_view,
                eth_view,
            )
        except Exception:
            continue

        if setup is None:
            continue

        zone = build_v42_zone(setup, base, one_slice)
        if zone is None:
            # Still persist location failures; they are part of the funnel.
            rows.append({
                "manifest_id": manifest_id,
                "symbol": symbol,
                "signal_time": signal_end.isoformat(),
                "v42_setup": setup.get("v42_setup"),
                "v42_subtype": setup.get("v42_subtype"),
                "v42_setup_quality": setup.get("v42_setup_quality"),
                "entry_status": "NO_VALID_HTF_ZONE",
                "entry_reject_reason": "NO_VALID_HTF_ZONE",
                "optimized_entry_filled": False,
                "shadow_execution_candidate": False,
                "v42_context": setup.get("v42_context"),
                "v42_regime": setup.get("v42_regime"),
            })
            last_setup_time = signal_end
            continue

        future15_signal = fifteen.loc[fifteen.index >= signal_end]

        baseline = _signal_baseline_plan(fifteen_view)
        baseline_outcome, baseline_ft, baseline_post = _outcome_bundle(
            baseline, future15_signal
        )

        optimized = simulate_v42_entry(
            setup,
            zone,
            future15_signal,
            fifteen_view,
            nearest_support=base.get("nearest_support"),
        )
        execution_candidate = bool(optimized.get("execution_candidate"))
        filled = bool(optimized.get("filled"))

        record = {
            "manifest_id": manifest_id,
            "symbol": symbol,
            "signal_time": signal_end.isoformat(),
            "v42_setup": setup.get("v42_setup"),
            "v42_subtype": setup.get("v42_subtype"),
            "v42_setup_quality": setup.get("v42_setup_quality"),
            "v42_context": setup.get("v42_context"),
            "v42_regime": setup.get("v42_regime"),
            "zone_source": zone.get("source"),
            "zone_lower": zone.get("lower"),
            "zone_upper": zone.get("upper"),
            "zone_location_quality": zone.get("location_quality"),
            "zone_prior_touch_count": zone.get("prior_touch_count"),
            "entry_status": (
                "ENTRY_READY"
                if filled
                else str(optimized.get("reject_reason") or "REJECTED")
            ),
            "entry_reject_reason": None if filled else optimized.get("reject_reason"),
            "optimized_entry_filled": filled,
            "shadow_execution_candidate": execution_candidate,
            "audit_zone_touched": bool(optimized.get("zone_touched")),
            "audit_meaningful_pivot_found": bool(optimized.get("meaningful_pivot_found")),
            "audit_displacement_bos": bool(optimized.get("displacement_bos")),
            "audit_retest_seen": bool(optimized.get("retest_seen")),
            "audit_failed_retest_confirmed": bool(optimized.get("failed_retest_confirmed")),
            "baseline_entry": None if baseline is None else baseline.get("entry"),
            "baseline_stop": None if baseline is None else baseline.get("stop"),
            "baseline_outcome": baseline_outcome.get("outcome"),
            "baseline_realized_r": baseline_outcome.get("realized_r"),
            "baseline_cost_r": baseline_outcome.get("cost_r"),
            **_prefix("baseline_", baseline_ft),
            **_prefix("baseline_", baseline_post),
        }

        if execution_candidate:
            shadow_plan = {
                "entry": optimized["entry"],
                "stop": optimized["stop"],
                "risk": optimized["risk"],
                "tp1": optimized["tp1"],
                "tp2": optimized["tp2"],
                "runner": optimized["runner"],
            }
            entry_ts = pd.Timestamp(optimized["entry_time"])
            shadow_future = fifteen.loc[fifteen.index >= entry_ts]
            shadow_outcome, shadow_ft, shadow_post = _outcome_bundle(
                shadow_plan, shadow_future
            )
            record.update({
                "shadow_entry_time": optimized.get("entry_time"),
                "shadow_entry": optimized.get("entry"),
                "shadow_stop": optimized.get("stop"),
                "shadow_stop_pct": optimized.get("stop_pct"),
                "shadow_support_room_r": optimized.get("support_room_r"),
                "shadow_projected_cost_r": optimized.get("projected_cost_r"),
                "shadow_bos_level": optimized.get("bos_level"),
                "shadow_pivot_age_bars": optimized.get("pivot_age_bars"),
                "shadow_pivot_prominence_atr15": optimized.get("pivot_prominence_atr15"),
                "shadow_displacement": optimized.get("displacement"),
                **_prefix("shadow_", shadow_outcome),
                **_prefix("shadow_", shadow_ft),
                **_prefix("shadow_", shadow_post),
            })

        if filled:
            actual_plan = {
                "entry": optimized["entry"],
                "stop": optimized["stop"],
                "risk": optimized["risk"],
                "tp1": optimized["tp1"],
                "tp2": optimized["tp2"],
                "runner": optimized["runner"],
            }
            entry_ts = pd.Timestamp(optimized["entry_time"])
            future15_entry = fifteen.loc[fifteen.index >= entry_ts]
            outcome, ft, post = _outcome_bundle(actual_plan, future15_entry)
            record.update({
                "entry_time": optimized.get("entry_time"),
                "entry": optimized.get("entry"),
                "stop": optimized.get("stop"),
                "risk": optimized.get("risk"),
                "stop_pct": optimized.get("stop_pct"),
                "support_room_r": optimized.get("support_room_r"),
                "projected_cost_r": optimized.get("projected_cost_r"),
                "tp1": optimized.get("tp1"),
                "tp2": optimized.get("tp2"),
                "runner": optimized.get("runner"),
                "bos_level": optimized.get("bos_level"),
                "pivot_age_bars": optimized.get("pivot_age_bars"),
                "pivot_prominence_atr15": optimized.get("pivot_prominence_atr15"),
                "displacement": optimized.get("displacement"),
                "wait_bars_15m": optimized.get("wait_bars_15m"),
                **outcome,
                **ft,
                **post,
            })

        rows.append(record)
        last_setup_time = signal_end

    return rows, None


def run_v42_backtest(manifest_path=None):
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
            f"[V4.2 shard {BACKTEST_SHARD_INDEX + 1}/{BACKTEST_SHARD_COUNT}] "
            f"[{index}/{len(selected)}] {symbol}: setups={len(rows)} errors={len(errors)}",
            flush=True,
        )

    rows.sort(key=lambda x: (
        str(x.get("signal_time")),
        str(x.get("symbol")),
        str(x.get("v42_setup")),
    ))
    return {
        "engine": "Crypto Short V4.2 Structural Validation",
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
            "setup_architecture": "one primary setup per symbol/timestamp: reversal or continuation",
            "context_only": "relative weakness, exhaustion, extreme pump",
            "entry_sequence": "HTF location -> meaningful pivot -> quality bearish displacement BOS -> failed retest -> Short",
            "entry_wait_hours": V42_ENTRY_WAIT_HOURS,
            "outcome_horizon_hours": BACKTEST_HORIZON_HOURS,
        },
        "trades": rows,
        "errors": errors,
    }
