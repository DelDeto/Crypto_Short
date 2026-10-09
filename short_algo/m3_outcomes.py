"""M3 V3.2 signal ledger and 24h standardized outcome tracking.

This tracks algorithm-signal performance only. The user remains responsible for
real entry/exit decisions; no USER_TAKEN or brokerage/exchange order state is
stored.
"""
import json
import os
from datetime import datetime, timezone

import pandas as pd

from .mexc import get_klines_window

STATE_PATH = os.getenv("M3_LIVE_LEDGER_PATH", "state/m3_v32_signals.json")
MAX_HOLD_HOURS = 24
FEE_BPS = float(os.getenv("M3_OUTCOME_FEE_BPS_ROUND_TRIP", "8"))
SLIPPAGE_BPS = float(os.getenv("M3_OUTCOME_SLIPPAGE_BPS_ROUND_TRIP", "6"))


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def load_ledger(path=STATE_PATH):
    if not os.path.exists(path):
        return {"version": "M3_V3.2", "signals": []}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return {"version": "M3_V3.2", "signals": []}
    data.setdefault("version", "M3_V3.2")
    data.setdefault("signals", [])
    return data


def _summary(signals):
    closed = [
        s for s in signals
        if s.get("outcome_status") == "CLOSED" and s.get("net_r") is not None
    ]
    by_tier = {}
    for tier in ("A", "B", "C"):
        rows = [s for s in closed if s.get("tier") == tier]
        vals = [float(s["net_r"]) for s in rows]
        gains = sum(v for v in vals if v > 0)
        losses = -sum(v for v in vals if v < 0)
        by_tier[tier] = {
            "closed": len(rows),
            "positive": sum(v > 0 for v in vals),
            "positive_pct": round(100 * sum(v > 0 for v in vals) / len(vals), 2) if vals else None,
            "expectancy_r": round(sum(vals) / len(vals), 5) if vals else None,
            "profit_factor": round(gains / losses, 4) if losses > 0 else (999.0 if gains > 0 else None),
            "total_net_r": round(sum(vals), 5),
        }

    return {
        "total_signals": len(signals),
        "open_signals": sum(s.get("outcome_status") == "OPEN" for s in signals),
        "closed_signals": len(closed),
        "by_tier": by_tier,
    }


def _too_close_to_existing(signal, signals):
    symbol = signal.get("symbol")
    t = pd.Timestamp(signal.get("signal_time"))
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    cooldown = pd.Timedelta(hours=float(signal.get("cooldown_hours") or 12))
    for old in reversed(signals):
        if old.get("symbol") != symbol:
            continue
        try:
            old_t = pd.Timestamp(old.get("signal_time"))
            if old_t.tzinfo is None:
                old_t = old_t.tz_localize("UTC")
        except Exception:
            continue
        if abs(t - old_t) < cooldown:
            return True
        if t - old_t >= cooldown:
            break
    return False


def register_signals(ledger, new_signals):
    existing_ids = {str(s.get("signal_id")) for s in ledger.get("signals", [])}
    added = []
    for row in new_signals:
        if row["signal_id"] in existing_ids:
            continue
        if _too_close_to_existing(row, ledger["signals"]):
            continue
        item = dict(row)
        item.update({
            "recorded_at": _utcnow(),
            "outcome_status": "OPEN",
            "outcome_state": "OPEN",
            "tp1_hit": 0,
            "tp2_hit": 0,
            "gross_r": None,
            "net_r": None,
            "exit_time": None,
            "last_outcome_check": None,
        })
        ledger["signals"].append(item)
        existing_ids.add(row["signal_id"])
        added.append(item)
    return added


def _cost_r(entry, risk_price):
    if not entry or not risk_price or risk_price <= 0:
        return 0.0
    round_trip_bps = FEE_BPS + SLIPPAGE_BPS
    return (round_trip_bps / 10000.0) * float(entry) / float(risk_price)


def _simulate(signal, frame):
    entry = float(signal["entry_reference"])
    stop = float(signal["invalidation"])
    tp1 = float(signal["tp1"])
    tp2 = float(signal["tp2"])
    risk = float(signal["risk_price"])
    if risk <= 0:
        raise ValueError("M3 invalid risk_price")

    tp1_hit = False
    tp1_time = None
    state = "OPEN"
    gross_r = None
    exit_time = None

    # Standardized hypothetical execution for signal evaluation:
    # 50% exits at TP1, remaining 50% targets TP2; after TP1, remainder stop
    # moves to entry. Same-candle stop/target ambiguity is resolved
    # conservatively in favor of the stop.
    for ts, bar in frame.iterrows():
        high = float(bar["high"])
        low = float(bar["low"])

        if not tp1_hit:
            if high >= stop:
                state = "SL_FIRST"
                gross_r = -1.0
                exit_time = ts
                break
            if low <= tp1:
                tp1_hit = True
                tp1_time = ts
                if low <= tp2:
                    state = "TP2_FULL"
                    gross_r = (
                        0.5 * ((entry - tp1) / risk)
                        + 0.5 * ((entry - tp2) / risk)
                    )
                    exit_time = ts
                    break
        else:
            if high >= entry:
                state = "TP1_THEN_BE"
                gross_r = 0.5 * ((entry - tp1) / risk)
                exit_time = ts
                break
            if low <= tp2:
                state = "TP2_FULL"
                gross_r = (
                    0.5 * ((entry - tp1) / risk)
                    + 0.5 * ((entry - tp2) / risk)
                )
                exit_time = ts
                break

    if gross_r is None:
        last = frame.iloc[-1]
        final_price = float(last["close"])
        second_leg_r = (entry - final_price) / risk
        if tp1_hit:
            gross_r = 0.5 * ((entry - tp1) / risk) + 0.5 * second_leg_r
            state = "TP1_TIME_EXIT"
        else:
            gross_r = second_leg_r
            state = "TIME_EXIT"
        exit_time = frame.index[-1]

    return {
        "state": state,
        "tp1_hit": int(tp1_hit),
        "tp2_hit": int(state == "TP2_FULL"),
        "gross_r": round(float(gross_r), 6),
        "net_r": round(float(gross_r) - _cost_r(entry, risk), 6),
        "exit_time": pd.Timestamp(exit_time).isoformat(),
        "tp1_time": pd.Timestamp(tp1_time).isoformat() if tp1_time is not None else None,
    }


def update_outcomes(ledger, now=None):
    now_ts = pd.Timestamp(now or datetime.now(timezone.utc))
    if now_ts.tzinfo is None:
        now_ts = now_ts.tz_localize("UTC")
    else:
        now_ts = now_ts.tz_convert("UTC")

    errors = []
    for signal in ledger.get("signals", []):
        if signal.get("outcome_status") != "OPEN":
            continue
        try:
            signal_time = pd.Timestamp(signal["signal_time"])
            if signal_time.tzinfo is None:
                signal_time = signal_time.tz_localize("UTC")
            start = signal_time.floor("15min")
            closed_end = now_ts.floor("15min") - pd.Timedelta(minutes=15)
            horizon_end = signal_time + pd.Timedelta(hours=MAX_HOLD_HOURS)
            end = min(closed_end, horizon_end)
            if end < start:
                continue

            frame = get_klines_window(signal["symbol"], "15m", start, end)
            if frame is None or frame.empty:
                continue

            sim = _simulate(signal, frame)
            signal["last_outcome_check"] = _utcnow()
            signal["outcome_state"] = sim["state"]
            signal["tp1_hit"] = sim["tp1_hit"]
            signal["tp2_hit"] = sim["tp2_hit"]
            signal["gross_r"] = sim["gross_r"]
            signal["net_r"] = sim["net_r"]
            signal["exit_time"] = sim["exit_time"]
            signal["tp1_time"] = sim["tp1_time"]

            terminal = sim["state"] in {"SL_FIRST", "TP1_THEN_BE", "TP2_FULL"}
            horizon_complete = closed_end >= horizon_end
            if terminal or horizon_complete:
                signal["outcome_status"] = "CLOSED"
        except Exception as exc:
            errors.append({"signal_id": signal.get("signal_id"), "error": str(exc)})
    return errors


def save_ledger(ledger, path=STATE_PATH):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    ledger["updated_at"] = _utcnow()
    ledger["summary"] = _summary(ledger.get("signals", []))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ledger, f, ensure_ascii=False, indent=2)
    return ledger["summary"]
