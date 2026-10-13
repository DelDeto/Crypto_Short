"""M5 V0.2 completely offline test of plan integrity, checkpoints and global control matching."""
from pathlib import Path
import gzip
import json
import tempfile

import pandas as pd

from .data import STEP
from .v02 import (create_plan, validate_plan, collect_chunk, shard_status,
                  merge_study, _files, load, dump)


def fake_bars(times, symbol):
    close = pd.Series(100.0, index=times)
    frame = pd.DataFrame({
        "open": close.copy(),
        "high": close * 1.001,
        "low": close * .999,
        "close": close.copy(),
        "volume": 100.0,
        "amount": 6000.0,
    })
    if symbol == "A_USDT":
        event_time = times[-17]
        frame.loc[event_time, "open"] = 103.0
        frame.loc[event_time, "high"] = 114.0
        frame.loc[event_time, "close"] = 100.0
        frame.loc[event_time, "amount"] = 25000.0
    return frame


def main():
    now = pd.Timestamp("2026-10-13T12:06:00Z")
    end = now.floor("15min") - STEP
    times = pd.date_range(end=end, periods=300, freq="15min", tz="UTC")
    symbols = ["BTC_USDT", "A_USDT", "B_USDT", "C_USDT", "D_USDT", "E_USDT"]

    def feed(symbol, start, finish):
        f = fake_bars(times, symbol)
        return f.loc[(f.index >= start) & (f.index <= finish)], 1

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "studies"
        p = create_plan(symbols, {"offline": True}, now=now, days=1, shards=3,
                        study_id="m5-offline-20261013-1d", root=root)
        assert validate_plan(p)["pilot"] is False
        assert p["holdout_reserved_start_utc"] > p["first_bar_open_utc"]
        try:
            merge_study(p["study_id"], root)
            raise AssertionError("Incomplete shards must never be merged")
        except RuntimeError as exc:
            assert "incomplete" in str(exc)
        # All 3 hash partitions contribute, with strict resumability.
        for i in range(3):
            for _ in range(5):
                if shard_status(p["study_id"], i, root)["complete"]:
                    break
                collect_chunk(p["study_id"], i, max_new=1,
                              root=root, fetch_fn=feed)
            s = shard_status(p["study_id"], i, root)
            assert s["complete"] and s["pending"] == 0
            count = len(list((root/p["study_id"]/"shards"/f"shard-{i:02d}"/"features").glob("*.csv.gz")))
            # Repeated run MUST not alter any archived feature.
            again = collect_chunk(p["study_id"], i, max_new=1,
                                  root=root, fetch_fn=feed)
            assert again["attempted_new"] == 0
            assert count == len(list((root/p["study_id"]/"shards"/f"shard-{i:02d}"/"features").glob("*.csv.gz")))
        result = merge_study(p["study_id"], root)
        assert result["status"] == "FULL_FROZEN_COHORT_MERGED"
        assert result["frozen_symbol_count"] == 6
        assert result["accepted_symbols"] == 6, result
        assert result["event_counts"]["E03"] >= 1, result
        assert result["event_observations_with_control"] >= 1
        with gzip.open(root/p["study_id"]/"merged"/"market_events.jsonl.gz", "rt") as fd:
            events = [json.loads(line) for line in fd]
        sweeps = [row for row in events if row["symbol"] == "A_USDT" and row["event_id"] == "E03"]
        assert sweeps and sweeps[0]["control_symbols"]
        assert sweeps[0]["control_scope"] == "FROZEN_WHOLE_STUDY_UNIVERSE_SAME_UTC"
        assert all(not row["outcome_labels_present"] for row in events)
        try:
            merge_study(p["study_id"], root)
            raise AssertionError("Merged archive should be immutable")
        except RuntimeError as exc:
            assert "already exists" in str(exc)
        bad = dict(p)
        bad["symbols"] = list(reversed(bad["symbols"]))
        try:
            validate_plan(bad)
            raise AssertionError("Tampered plan checksum was accepted")
        except RuntimeError as exc:
            assert "hash conflict" in str(exc)
        try:
            create_plan(symbols, {}, now=now, days=180, shards=3,
                        root=root, study_id="m5-bad-too-large")
            raise AssertionError("180-day Git archive request should be rejected")
        except ValueError:
            pass
        # A small pilot can never masquerade as whole-market confirmation.
        q = create_plan(symbols, {"offline": True}, now=now, days=1,
                        shards=1, study_id="m5-offline-pilot-check", root=root,
                        pilot=True, symbols_limit=3)
        for _ in range(3):
            collect_chunk(q["study_id"], 0, max_new=1, root=root, fetch_fn=feed)
        try:
            merge_study(q["study_id"], root)
            raise AssertionError("Pilot incorrectly passed full-market gate")
        except RuntimeError as exc:
            assert "Pilot" in str(exc)
        pilot = merge_study(q["study_id"], root, allow_pilot=True)
        assert pilot["status"] == "PILOT_SUBSET_COMPLETE_NOT_FULL_MARKET"
    print("M5 V0.2 SELFTEST PASS: frozen cohort, 3-shard checkpoint/restart, market-wide controls, no outcomes")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
