"""Offline regression of M5 V0.1: time causality, 8 families and API 510.

No network calls. Synthetic outcomes do not get used for event selection.
"""
import json
import tempfile
from pathlib import Path
import pandas as pd
import numpy as np

from .config import EVENTS
from .data import completed_window, select_universe, request_candles
from .events import features_asof, discover_events
from .run import run
from . import data

def candles(index, initial=100.0):
    c = pd.Series(initial, index=index, dtype=float)
    frame = pd.DataFrame({
        "open": c, "high": c * 1.001, "low": c * .999,
        "close": c, "volume": 200., "amount": 3000.,
    }, index=index)
    return frame

def main():
    assert len(EVENTS) == 8 and len(set(EVENTS)) == 8
    now = pd.Timestamp("2026-10-13T12:08:00Z")
    start, end = completed_window(now, lookback_days=1)
    assert end == pd.Timestamp("2026-10-13T11:45:00Z")
    assert start == end - pd.Timedelta(days=1)
    assert not set(select_universe(["A_USDT", "B_USDT", "BTC_USDT"], 2, 0)).intersection(
        select_universe(["A_USDT", "B_USDT", "BTC_USDT"], 2, 1))
    index = pd.date_range(end=end, periods=260, freq="15min", tz="UTC")
    btc = candles(index)
    coin = candles(index)
    # 100% historical closed-bar sweep, with return below the old high.
    spike_at = index[-16]
    coin.loc[spike_at, "open"] = 102.
    coin.loc[spike_at, "high"] = 114.
    coin.loc[spike_at, "low"] = 98.
    coin.loc[spike_at, "close"] = 100.
    coin.loc[spike_at, "amount"] = 15000.
    f1 = features_asof("A_USDT", coin, btc, index[130])
    assert "E03" in f1.columns and "E08" in f1.columns
    assert bool(f1.loc[spike_at, "E03"])
    assert bool(f1.loc[spike_at, "E06"])
    # Causal prefix invariance: arbitrary bars AFTER event cannot change it.
    larger = pd.concat([coin, candles(pd.date_range(
        index[-1] + pd.Timedelta(minutes=15), periods=5, freq="15min", tz="UTC"), initial=10000)])
    f2 = features_asof("A_USDT", larger, btc, index[130])
    for key in EVENTS:
        assert f1.loc[:index[-1], key].equals(f2.loc[:index[-1], key]), key
    control = features_asof("B_USDT", candles(index), btc, index[130])
    events, counts, feature_rows = discover_events([f1, control])
    e03 = [e for e in events if e["event_id"] == "E03"]
    assert len(e03) >= 1 and e03[0]["control_symbols"] == ["B_USDT"]
    assert e03[0]["observed_at_utc"] == (spike_at + pd.Timedelta(minutes=15)).isoformat()
    assert not any(k.startswith("short_") or k.startswith("future") for k in e03[0])
    assert feature_rows > 0
    # 510 payload retry with HTTP 200, and count ALL actual requests.
    tick = int(index[-2].timestamp())
    ok = {"success": True, "code": 0,
          "data": {"time": [tick], "open": [100], "high": [102],
                   "low": [99], "close": [101], "vol": [10], "amount": [20000]}}
    class Response:
        status_code = 200
        def __init__(self, payload): self.payload = payload
        def json(self): return self.payload
        def raise_for_status(self): pass
    class Session:
        calls = 0
        def get(self, url, params, timeout):
            self.calls += 1
            return Response({"success": False, "code": 510,
                             "message": "Requests are too frequent"} if self.calls == 1 else ok)
    client = Session()
    old = (data._session, data._pace, data._cooldown)
    try:
        data._session = lambda: client
        data._pace = lambda: None
        data._cooldown = lambda _: None
        df, attempts = request_candles("A_USDT", index[-2], index[-2])
    finally:
        data._session, data._pace, data._cooldown = old
    assert attempts == 2 and len(df) == 1 and float(df.iloc[0]["close"]) == 101

    # Fully offline CLI/inventory via injected catalog and candle service.
    with tempfile.TemporaryDirectory() as td:
        def offline_fetch(symbol, first, last):
            source = btc if symbol == "BTC_USDT" else coin if symbol == "A_USDT" else candles(index)
            return source.loc[(source.index >= first) & (source.index <= last)], 1
        result = run(days=1, shards=1, shard_index=0, max_symbols=3,
                     now=now, outdir=Path(td),
                     catalogue_fn=lambda: (["BTC_USDT", "A_USDT", "B_USDT"], {"synthetic": True}),
                     fetch_fn=offline_fetch)
        assert result["accepted_symbol_count"] == 3, result
        assert result["catalogue_count"] == 3
        assert result["research_only"] and not result["outcomes_computed"]
        assert result["event_counts"]["E03"] >= 1
        assert any(Path(td).rglob("event_registry.jsonl.gz"))
    print("M5 V0.1 SELFTEST PASS: causal 8-event detection, controls, bounded CLI and MEXC 510 retry")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
