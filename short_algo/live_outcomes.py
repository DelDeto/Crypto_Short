"""Persistent signal ledger and automatic outcome tracking for live M2.

Tracks algorithm signal performance only. There is intentionally no field for
whether the user took a trade.
"""
import json
import os
from datetime import datetime, timezone

import pandas as pd

from .mexc import get_klines_window
from .v4412_m2_execution import _simulate_variant

STATE_PATH = os.getenv("M2_LIVE_LEDGER_PATH", "state/m2_live_signals.json")
SOURCE_PREFIX = "v4412_m2_s1_75"
TERMINAL_STATES = {
    "SL_FIRST",
    "TP1_THEN_BE",
    "TP2_FULL",
    "TP1_TIME_EXIT",
    "TIME_EXIT",
    "GAP_BEYOND_STOP",
}


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def load_ledger(path=STATE_PATH):
    if not os.path.exists(path):
        return {"version": 1, "signals": []}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return {"version": 1, "signals": []}
    data.setdefault("version", 1)
    data.setdefault("signals", [])
    return data


def _summary(signals):
    closed = [s for s in signals if s.get("outcome_status") == "CLOSED" and s.get("net_r") is not None]
    by_tier = {}
    for tier in ("A+", "A", "B", "C"):
        rows = [s for s in closed if s.get("tier") == tier]
        vals = [float(s["net_r"]) for s in rows]
        gain = sum(x for x in vals if x > 0)
        loss = -sum(x for x in vals if x < 0)
        by_tier[tier] = {
            "closed": len(rows),
            "positive": sum(x > 0 for x in vals),
            "positive_pct": round(100 * sum(x > 0 for x in vals) / len(vals), 2) if vals else None,
            "expectancy_r": round(sum(vals) / len(vals), 5) if vals else None,
            "profit_factor": round(gain / loss, 4) if loss > 0 else (999.0 if gain > 0 else None),
            "total_net_r": round(sum(vals), 5),
        }
    return {
        "total_signals": len(signals),
        "open_signals": sum(s.get("outcome_status") == "OPEN" for s in signals),
        "closed_signals": len(closed),
        "by_tier": by_tier,
    }


def register_signals(ledger, new_signals):
    existing = {str(s.get("signal_id")) for s in ledger.get("signals", [])}
    added = []
    for row in new_signals:
        if row["signal_id"] in existing:
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
        existing.add(row["signal_id"])
        added.append(item)
    return added


def _apply_sim(signal, sim):
    signal["last_outcome_check"] = _utcnow()
    state = sim.get(f"{SOURCE_PREFIX}_state")
    signal["outcome_state"] = state
    signal["tp1_hit"] = int(sim.get(f"{SOURCE_PREFIX}_tp1_hit") or 0)
    signal["tp2_hit"] = int(sim.get(f"{SOURCE_PREFIX}_tp2_hit") or 0)
    signal["gross_r"] = sim.get(f"{SOURCE_PREFIX}_gross_r")
    signal["net_r"] = sim.get(f"{SOURCE_PREFIX}_net_r")
    signal["exit_time"] = sim.get(f"{SOURCE_PREFIX}_exit_time")
    if state in TERMINAL_STATES:
        signal["outcome_status"] = "CLOSED"


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
            entry_time = pd.Timestamp(signal["entry_time"])
            if entry_time.tzinfo is None:
                entry_time = entry_time.tz_localize("UTC")
            end = min(now_ts, entry_time + pd.Timedelta(hours=97))
            frame = get_klines_window(
                signal["symbol"], "15m", entry_time, end
            )
            if frame is None or frame.empty:
                continue
            # Require exact entry bar so execution semantics remain identical.
            if entry_time not in frame.index:
                continue
            entry_idx = int(frame.index.get_loc(entry_time))
            sim = _simulate_variant(
                frame,
                entry_idx,
                float(signal["entry"]),
                float(signal["atr_at_entry"]),
                1.75,
            )
            _apply_sim(signal, sim)
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
