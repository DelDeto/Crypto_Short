"""Live M2 V4.4.18 signal evaluator.

Reconstructs the same causal M2 chain from already-closed candles:
signal-time features -> structural support break -> persistent support flip
-> 24-48h watch gate -> 1H bearish confirmation -> next 15m entry.

Only D-or-better signals are emitted:
D  = RISK_OFF + S4_MACRO_BEAR
E1 = D + EMA20 distance >= 1.36 ATR
E2 = D + anti-bottom >= 17

Tier:
A+ = E1 + E2
A  = E2 only
B  = E1 only
C  = D only
"""
import os
from datetime import datetime, timezone

import pandas as pd

from .backtest import _historical_ticker
from .mexc import get_closed_klines
from .strategy import analyze_short
from .v428_features import build_v428_features
from .v447_execution import _closed, _find_break_event
from .v449_m2_execution import _find_1h_entry, _watch_support_flip

PERSISTENT = "PERSISTENT_NO_RECLAIM_LOWER_HIGHS"
MIN_WATCH_HOURS = 24.0
MAX_WATCH_HOURS = 48.0
STOP_ATR = 1.75
TP1_ATR = 2.0
TP2_ATR = 3.0
EMA_GATE = 1.36
ANTI_BOTTOM_GATE = 17.0
MAX_SIGNAL_AGE_MIN = int(os.getenv("M2_LIVE_MAX_SIGNAL_AGE_MIN", "90"))
ANCHOR_LOOKBACK_HOURS = int(os.getenv("M2_LIVE_ANCHOR_LOOKBACK_HOURS", "80"))


def _as_utc(value):
    t = pd.Timestamp(value)
    if t.tzinfo is None:
        return t.tz_localize("UTC")
    return t.tz_convert("UTC")


def classify_tier(features):
    d = bool(int(features.get("market_risk_off") or 0) == 1 and int(features.get("s4_macro_bear") or 0) == 1)
    ema = features.get("ema20_distance_atr")
    anti = features.get("anti_bottom_total")
    e1 = bool(d and ema is not None and float(ema) >= EMA_GATE)
    e2 = bool(d and anti is not None and float(anti) >= ANTI_BOTTOM_GATE)
    if not d:
        tier = None
    elif e1 and e2:
        tier = "A+"
    elif e2:
        tier = "A"
    elif e1:
        tier = "B"
    else:
        tier = "C"
    return {
        "d_gate": d,
        "e1_ema_gate": e1,
        "e2_anti_bottom_gate": e2,
        "tier": tier,
    }


def _anchor_times(one):
    if one is None or one.empty:
        return []
    latest_close = one.index[-1] + pd.Timedelta(hours=1)
    cutoff = latest_close - pd.Timedelta(hours=ANCHOR_LOOKBACK_HOURS)
    out = []
    for open_time in one.index:
        close_time = open_time + pd.Timedelta(hours=1)
        if close_time < cutoff or close_time > latest_close:
            continue
        if int(close_time.hour) % 4 == 0:
            out.append(close_time)
    return out


def _entry_plan_prices(entry, atr):
    risk = STOP_ATR * atr
    return {
        "entry": round(float(entry), 10),
        "stop": round(float(entry) + risk, 10),
        "tp1": round(float(entry) - TP1_ATR * atr, 10),
        "tp2": round(float(entry) - TP2_ATR * atr, 10),
        "risk_atr": STOP_ATR,
        "tp1_atr": TP1_ATR,
        "tp2_atr": TP2_ATR,
    }


def evaluate_live_symbol(symbol, frames, btc_one, eth_one, now=None):
    one = (frames or {}).get("1H")
    four = (frames or {}).get("4H")
    if one is None or four is None or one.empty or four.empty:
        return []

    one = one.sort_index()
    four = four.sort_index()
    btc_one = None if btc_one is None else btc_one.sort_index()
    eth_one = None if eth_one is None else eth_one.sort_index()
    now_ts = _as_utc(now or datetime.now(timezone.utc))

    fifteen = None
    event_seen = set()
    candidates = []

    for signal_time in _anchor_times(one):
        one_ctx = _closed(one, signal_time, 1)
        four_ctx = _closed(four, signal_time, 4)
        btc_ctx = _closed(btc_one, signal_time, 1)
        eth_ctx = _closed(eth_one, signal_time, 1)
        if any(x is None for x in (one_ctx, four_ctx, btc_ctx, eth_ctx)):
            continue
        if len(one_ctx) < 60 or len(four_ctx) < 90:
            continue

        try:
            base = analyze_short(
                symbol,
                {"1H": one_ctx, "4H": four_ctx},
                _historical_ticker(one_ctx),
                fast_row=None,
            )
            features = build_v428_features(base, one_ctx, four_ctx, btc_ctx, eth_ctx)
        except Exception:
            continue
        if features is None:
            continue

        tier = classify_tier(features)
        if not tier["d_gate"]:
            continue

        event = _find_break_event(features, four_ctx, four, signal_time)
        if event is None:
            continue
        event_key = (
            pd.Timestamp(event["break_time"]).isoformat(),
            round(float(event["level"]), 10),
        )
        if event_key in event_seen:
            continue
        event_seen.add(event_key)

        watch = _watch_support_flip(event, four)
        if watch.get("state") != "CONFIRMED_SUPPORT_FLIP":
            continue
        if watch.get("ready_reason") != PERSISTENT:
            continue
        watch_hours = watch.get("watch_hours")
        if watch_hours is None or not (MIN_WATCH_HOURS <= float(watch_hours) <= MAX_WATCH_HOURS):
            continue

        if fifteen is None:
            try:
                fifteen = get_closed_klines(symbol, "15m", 160, 40)
            except Exception:
                return candidates

        entry_plan = _find_1h_entry(watch, event, one, fifteen)
        if entry_plan.get("state") != "ENTRY":
            continue

        entry_idx = int(entry_plan["entry_idx"])
        entry_time = fifteen.index[entry_idx]
        age_min = (now_ts - _as_utc(entry_time)).total_seconds() / 60.0
        if age_min < -5 or age_min > MAX_SIGNAL_AGE_MIN:
            continue

        entry = float(entry_plan["entry"])
        atr = float(event["atr"])
        prices = _entry_plan_prices(entry, atr)
        signal_id = f"{symbol}|{entry_time.isoformat()}|{event['break_time'].isoformat()}"

        candidates.append({
            "signal_id": signal_id,
            "symbol": symbol,
            "model": "M2_V4418_LIVE",
            "tier": tier["tier"],
            "d_gate": tier["d_gate"],
            "e1_ema_gate": tier["e1_ema_gate"],
            "e2_anti_bottom_gate": tier["e2_anti_bottom_gate"],
            "signal_anchor_time": signal_time.isoformat(),
            "break_time": pd.Timestamp(event["break_time"]).isoformat(),
            "ready_time": pd.Timestamp(watch["ready_time"]).isoformat(),
            "entry_time": pd.Timestamp(entry_time).isoformat(),
            "signal_age_minutes": round(age_min, 1),
            "watch_hours": float(watch_hours),
            "support_level": round(float(event["level"]), 10),
            "support_lower": round(float(event["lower"]), 10),
            "support_upper": round(float(event["upper"]), 10),
            "atr_at_entry": round(atr, 10),
            "ema20_distance_atr": features.get("ema20_distance_atr"),
            "anti_bottom_total": features.get("anti_bottom_total"),
            "candidate_context_points": features.get("candidate_context_points"),
            "market_r4_pct": features.get("market_r4_pct"),
            "market_r24_pct": features.get("market_r24_pct"),
            "relative_4h_pct": features.get("relative_4h_pct"),
            "relative_24h_pct": features.get("relative_24h_pct"),
            "market_risk_off": int(features.get("market_risk_off") or 0),
            "s4_macro_bear": int(features.get("s4_macro_bear") or 0),
            "failed_reclaim_attempts": watch.get("failed_reclaim_attempts"),
            "retest_attempts": watch.get("retest_attempts"),
            "pivot_high_count": watch.get("pivot_high_count"),
            "bars_below": watch.get("bars_below"),
            "entry_below_support_atr": round(float(entry_plan["entry_below_support_atr"]), 5),
            **prices,
        })

    # A symbol can be reconstructed from more than one historical anchor.
    # Keep only the freshest distinct entry for live delivery.
    candidates.sort(key=lambda r: r["entry_time"], reverse=True)
    return candidates[:1]
