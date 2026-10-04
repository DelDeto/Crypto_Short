import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests

from .config import (
    BASE_URL,
    DEEP_HISTORY_1H,
    DEEP_HISTORY_4H,
    DEEP_MIN_HISTORY,
    DEEP_WORKERS,
    FAST_HISTORY,
    FAST_MIN_HISTORY,
    FAST_WORKERS,
    QUOTE_COIN,
)

INTERVAL_MAP = {"1h": "Min60", "4h": "Hour4"}
INTERVAL_SECONDS = {"1h": 3600, "4h": 14400}

_REQUEST_LOCK = threading.Lock()
_LAST_REQUEST_AT = 0.0
_MIN_REQUEST_INTERVAL = 0.25


def _throttle():
    global _LAST_REQUEST_AT
    with _REQUEST_LOCK:
        now = time.monotonic()
        wait = _MIN_REQUEST_INTERVAL - (now - _LAST_REQUEST_AT)
        if wait > 0:
            time.sleep(wait)
        _LAST_REQUEST_AT = time.monotonic()


def _get_json(path, params=None, timeout=15, retries=4):
    last_error = None
    for attempt in range(retries + 1):
        _throttle()
        try:
            response = requests.get(BASE_URL + path, params=params, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict) and payload.get("success") is False:
                code = payload.get("code")
                message = str(payload.get("message") or "")
                if (code == 510 or "too frequent" in message.lower()) and attempt < retries:
                    time.sleep(1.0 * (2 ** attempt))
                    continue
                raise RuntimeError(f"MEXC API error {path}: {payload}")
            return payload
        except requests.RequestException as exc:
            last_error = exc
            if attempt >= retries:
                raise
            time.sleep(1.0 * (2 ** attempt))
    raise RuntimeError(f"MEXC request failed {path}: {last_error}")


def get_contract_universe():
    payload = _get_json("/api/v1/contract/detail")
    rows = payload.get("data", []) if isinstance(payload, dict) else []
    symbols = []
    for row in rows:
        symbol = row.get("symbol")
        quote = row.get("quoteCoin") or row.get("settleCoin") or ""
        state = row.get("state")
        if not symbol or str(quote).upper() != QUOTE_COIN:
            continue
        if state in (2, 3, 4, "2", "3", "4"):
            continue
        symbols.append(symbol)
    return sorted(set(symbols))


def _float(row, *keys):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            try:
                return float(value)
            except (TypeError, ValueError):
                pass
    return None


def get_all_tickers():
    payload = _get_json("/api/v1/contract/ticker")
    rows = payload.get("data", []) if isinstance(payload, dict) else []
    if isinstance(rows, dict):
        rows = [rows]

    result = {}
    for row in rows:
        symbol = row.get("symbol")
        if not symbol:
            continue
        bid = _float(row, "bid1", "bid1Price", "bidPrice")
        ask = _float(row, "ask1", "ask1Price", "askPrice")
        last = _float(row, "lastPrice", "last_price")
        spread_bps = None
        if bid and ask and ask >= bid:
            mid = (bid + ask) / 2.0
            if mid > 0:
                spread_bps = (ask - bid) / mid * 10000.0
        result[symbol] = {
            "symbol": symbol,
            "last_price": last,
            "bid": bid,
            "ask": ask,
            "spread_bps": spread_bps,
            "high_24h": _float(row, "high24Price", "high24h"),
            "low_24h": _float(row, "lower24Price", "low24h"),
            "change_rate_24h": _float(row, "riseFallRate", "changeRate"),
            "turnover_24h": _float(row, "amount24", "turnover24", "turnover24h", "amount24h"),
            "volume_24h": _float(row, "volume24", "volume24h", "volume"),
            "funding_rate": _float(row, "fundingRate", "funding_rate"),
            "hold_vol": _float(row, "holdVol", "hold_volume"),
        }
    return result


def _parse_kline(payload):
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    if isinstance(data, list):
        rows = []
        for item in data:
            if isinstance(item, dict):
                rows.append(item)
            elif isinstance(item, (list, tuple)) and len(item) >= 6:
                rows.append({
                    "time": item[0], "open": item[1], "high": item[2],
                    "low": item[3], "close": item[4], "vol": item[5],
                })
        frame = pd.DataFrame(rows)
    else:
        frame = pd.DataFrame({
            "time": data.get("time", []),
            "open": data.get("open", []),
            "high": data.get("high", []),
            "low": data.get("low", []),
            "close": data.get("close", []),
            "volume": data.get("vol", data.get("volume", [])),
        })

    if frame.empty:
        return frame
    if "volume" not in frame.columns and "vol" in frame.columns:
        frame["volume"] = frame["vol"]

    frame["time"] = pd.to_datetime(frame["time"].astype(float), unit="s", utc=True)
    for col in ["open", "high", "low", "close", "volume"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")

    return (
        frame[["time", "open", "high", "low", "close", "volume"]]
        .dropna()
        .drop_duplicates(subset=["time"])
        .sort_values("time")
        .set_index("time")
    )


def get_closed_klines(symbol, interval, limit, min_required):
    if interval not in INTERVAL_MAP:
        raise ValueError(f"Unsupported interval: {interval}")

    now_seconds = int(time.time())
    seconds = INTERVAL_SECONDS[interval]
    request_limit = limit + 8
    payload = _get_json(
        f"/api/v1/contract/kline/{symbol}",
        params={
            "interval": INTERVAL_MAP[interval],
            "start": now_seconds - seconds * (request_limit + 5),
            "end": now_seconds,
        },
    )
    frame = _parse_kline(payload)
    if frame.empty:
        raise RuntimeError(f"No kline data for {symbol} {interval}")

    now = pd.Timestamp.now(tz="UTC")
    frame = frame.loc[(frame.index + pd.to_timedelta(seconds, unit="s")) <= now].tail(limit)
    if len(frame) < min_required:
        raise RuntimeError(
            f"{symbol} {interval}: only {len(frame)} closed candles; need {min_required}"
        )
    return frame


def fetch_fast_frame(symbol):
    return get_closed_klines(symbol, "1h", FAST_HISTORY, FAST_MIN_HISTORY)


def fetch_deep_frames(symbol):
    return {
        "1H": get_closed_klines(symbol, "1h", DEEP_HISTORY_1H, DEEP_MIN_HISTORY),
        "4H": get_closed_klines(symbol, "4h", DEEP_HISTORY_4H, DEEP_MIN_HISTORY),
    }


def _fetch_many(symbols, fn, workers):
    data, errors = {}, {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = {pool.submit(fn, symbol): symbol for symbol in symbols}
        for future in as_completed(jobs):
            symbol = jobs[future]
            try:
                data[symbol] = future.result()
            except Exception as exc:
                errors[symbol] = str(exc)
    return data, errors


def fetch_many_fast(symbols):
    return _fetch_many(symbols, fetch_fast_frame, FAST_WORKERS)


def fetch_many_deep(symbols):
    return _fetch_many(symbols, fetch_deep_frames, DEEP_WORKERS)


def get_klines_window(symbol, interval, start_time, end_time, chunk_bars=450):
    """Fetch a historical closed-candle window in forward chunks.

    start_time/end_time may be pandas Timestamp or datetime-compatible values.
    Returned timestamps are candle OPEN times. No current/live candle filtering
    is applied because the caller explicitly defines the historical window.
    """
    if interval not in INTERVAL_MAP:
        raise ValueError(f"Unsupported interval: {interval}")

    start_ts = pd.Timestamp(start_time)
    end_ts = pd.Timestamp(end_time)
    if start_ts.tzinfo is None:
        start_ts = start_ts.tz_localize("UTC")
    else:
        start_ts = start_ts.tz_convert("UTC")
    if end_ts.tzinfo is None:
        end_ts = end_ts.tz_localize("UTC")
    else:
        end_ts = end_ts.tz_convert("UTC")

    seconds = INTERVAL_SECONDS[interval]
    cursor = int(start_ts.timestamp())
    end_seconds = int(end_ts.timestamp())
    frames = []

    while cursor <= end_seconds:
        chunk_end = min(
            end_seconds,
            cursor + seconds * max(50, int(chunk_bars)),
        )
        payload = _get_json(
            f"/api/v1/contract/kline/{symbol}",
            params={
                "interval": INTERVAL_MAP[interval],
                "start": cursor,
                "end": chunk_end,
            },
        )
        frame = _parse_kline(payload)
        if not frame.empty:
            frames.append(frame)

        next_cursor = chunk_end + seconds
        if next_cursor <= cursor:
            break
        cursor = next_cursor

    if not frames:
        return pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"]
        )

    combined = (
        pd.concat(frames)
        .sort_index()
        .loc[lambda x: ~x.index.duplicated(keep="last")]
    )
    return combined.loc[
        (combined.index >= start_ts) & (combined.index <= end_ts)
    ]


def fetch_backtest_frames(symbol, start_time, end_time, warmup_days=25):
    """Fetch enough warmup candles before the requested replay period."""
    start_ts = pd.Timestamp(start_time)
    if start_ts.tzinfo is None:
        start_ts = start_ts.tz_localize("UTC")
    else:
        start_ts = start_ts.tz_convert("UTC")
    warmup_start = start_ts - pd.Timedelta(days=warmup_days)

    return {
        "1H": get_klines_window(symbol, "1h", warmup_start, end_time),
        "4H": get_klines_window(symbol, "4h", warmup_start, end_time),
    }
