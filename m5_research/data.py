"""Bounded, paced, read-only MEXC 15m historical OHLCV transport.

No credentials, no orders, no writing to other models' data directories.
"""
import hashlib
import random
import threading
import time
from pathlib import Path

import pandas as pd
import requests

from m4_research.config import API_BASE
from m4_research.market import _candle_frame, snapshot_universe
from .config import (BARS_PER_REQUEST, MAX_API_ATTEMPTS,
                     MIN_REQUEST_SPACING_SECONDS)

_lock = threading.Lock()
_next_at = 0.0
_local = threading.local()
STEP = pd.Timedelta(minutes=15)

class TemporaryMexcError(Exception):
    pass

def _utc(value):
    timestamp = pd.Timestamp(value)
    return timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")

def _session():
    if not hasattr(_local, "session"):
        _local.session = requests.Session()
    return _local.session

def _pace():
    global _next_at
    with _lock:
        now = time.monotonic()
        delay = max(0.0, _next_at - now)
        _next_at = max(now, _next_at) + MIN_REQUEST_SPACING_SECONDS
    if delay:
        time.sleep(delay)

def _cooldown(seconds):
    global _next_at
    with _lock:
        _next_at = max(_next_at, time.monotonic() + seconds)

def request_candles(symbol, start, end):
    """Return (15-minute candles, actual HTTP attempt count)."""
    start, end = _utc(start), _utc(end)
    if end < start:
        raise ValueError("Invalid historical time range")
    if start != start.floor("15min") or end != end.floor("15min"):
        raise ValueError("15m timestamps must be aligned candle open times")
    frames, attempts = [], 0
    point = start
    while point <= end:
        last = min(end, point + (BARS_PER_REQUEST - 1) * STEP)
        query = {
            "interval": "Min15",
            "start": int(point.timestamp()),
            "end": int(last.timestamp()),
        }
        data = None
        for k in range(MAX_API_ATTEMPTS):
            _pace()
            attempts += 1
            try:
                response = _session().get(
                    API_BASE + "/api/v1/contract/kline/" + symbol,
                    params=query, timeout=25,
                )
                if response.status_code in (418, 429, 500, 502, 503, 504):
                    raise TemporaryMexcError("HTTP " + str(response.status_code))
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Unexpected payload")
                code = payload.get("code")
                message = str(payload.get("message") or payload.get("msg") or "")
                if str(code) == "510" or "too frequent" in message.lower():
                    raise TemporaryMexcError("MEXC rate limit 510: " + message[:100])
                if payload.get("success") is False or code not in (None, 0, "0"):
                    raise ValueError("MEXC API error " + str(code) + ": " + message[:100])
                data = _candle_frame(payload.get("data"))
                break
            except (TemporaryMexcError, requests.Timeout, requests.ConnectionError) as exc:
                if k == MAX_API_ATTEMPTS - 1:
                    raise RuntimeError("MEXC exhausted retries " + symbol + ": " + str(exc)) from exc
                _cooldown(min(3 * 2 ** k, 40) + random.uniform(0, .25))
        if data is None:
            raise RuntimeError("No valid candle result for " + symbol)
        if not data.empty:
            frames.append(data)
        point = last + STEP
    if not frames:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "amount"]), attempts
    frame = pd.concat(frames).sort_index()
    frame = frame.loc[~frame.index.duplicated(keep="last")]
    # Discard unexpected candles beyond requested time; do not see the future.
    return frame.loc[(frame.index >= start) & (frame.index <= end)], attempts

def select_universe(symbols, total_shards=16, shard_index=0, limit=0):
    if total_shards < 1 or not 0 <= shard_index < total_shards:
        raise ValueError("Invalid shard specification")
    all_symbols = sorted(set(symbols))
    selected = [s for s in all_symbols
                if int(hashlib.sha256(s.encode()).hexdigest()[:12], 16) % total_shards == shard_index]
    return selected[:limit] if limit > 0 else selected

def completed_window(now=None, lookback_days=14):
    if not 1 <= lookback_days <= 240:
        raise ValueError("Choose 1..240 historical days")
    now = _utc(now or pd.Timestamp.now(tz="UTC"))
    # A candle opening at now.floor(15min) has NOT closed yet.
    last_closed_open = now.floor("15min") - STEP
    first = last_closed_open - pd.Timedelta(days=lookback_days)
    return first, last_closed_open

def coverage(frame, start, end):
    expected = int((_utc(end) - _utc(start)) / STEP) + 1
    if expected <= 0:
        return 0.0
    actual = 0 if frame.empty else len(frame.loc[(frame.index >= start) & (frame.index <= end)])
    return round(min(actual / expected, 1.0), 6)

def record_catalogue():
    symbols, audit = snapshot_universe()
    if "BTC_USDT" not in symbols:
        raise RuntimeError("BTC_USDT missing from MEXC futures catalogue")
    if len(symbols) < 50:
        raise RuntimeError("Unexpectedly small MEXC futures catalogue")
    return symbols, audit
