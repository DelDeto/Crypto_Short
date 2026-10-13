"""Entirely offline M5 V0.3 discovery/holdout firewall regression.

No external API requests. Fake 7d cohort archived via exactly the V0.2
checkpoint pipeline; discovery labels must never touch reserved holdout.
"""
import gzip
import json
import tempfile
from pathlib import Path

import pandas as pd

from .data import STEP
from .v02 import create_plan, collect_chunk, shard_status, merge_study, _files
from .v03_discovery import analyze, series_short_returns, HORIZONS_HOURS

NOW = pd.Timestamp("2026-10-13T12:06:00Z")
END = NOW.floor("15min") - STEP
TIMES = pd.date_range(end=END, periods=860, freq="15min", tz="UTC")
SHOCK = END - pd.Timedelta(hours=60)

def candles(symbol, begin, end):
    idx = TIMES[(TIMES >= begin) & (TIMES <= end)]
    close = pd.Series(100.0, index=idx)
    if symbol == "A_USDT":
        for j in range(1, 34):
            point = SHOCK + j * STEP
            if point in close.index:
                close.loc[point] = 100 - .06 * j
    f = pd.DataFrame({
        "open": close,
        "high": close * 1.001,
        "low": close * .999,
        "close": close,
        "volume": 500.0,
        "amount": 9000.0,
    })
    if symbol == "A_USDT" and SHOCK in f.index:
        f.loc[SHOCK, ["open", "high", "low", "close", "amount"]] =             [103.0, 114.0, 98.0, 100.0, 40000.0]
    return f, 1

def main():
    symbols = ["BTC_USDT", "A_USDT", "B_USDT", "C_USDT", "D_USDT", "E_USDT"]
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp) / "studies"
        p = create_plan(symbols, {"fake": True}, now=NOW, days=7, shards=3,
                        study_id="m5-v03-offline-study", root=root)
        holdout = pd.Timestamp(p["holdout_reserved_start_utc"])
        assert SHOCK + pd.Timedelta(hours=8) < holdout
        for shard in range(3):
            while not shard_status(p["study_id"], shard, root)["complete"]:
                r = collect_chunk(p["study_id"], shard, max_new=2, root=root,
                                  fetch_fn=candles)
                assert not r["transient_failures"], r
        archive = merge_study(p["study_id"], root)
        assert archive["status"] == "FULL_FROZEN_COHORT_MERGED"
        report = analyze(p["study_id"], root)
        assert report["holdout_outcome_rows_read"] == 0
        assert report["holdout_performance_disclosed"] is False
        assert report["source_symbol_count"] == len(symbols)
        assert report["no_live_promotion"] is True
        assert report["eligible_complete_case_and_control_pairs"] > 0
        e03 = report["families"]["E03"]
        assert e03["paired_event_observations"] >= 1, report["families"]
        assert e03["horizon_metrics"]["4h"]["mean_paired_edge_pp"] > 0
        assert report["cannot_compute_true_mfe_mae_without_ohlc_high_low"]
        assert all(h in HORIZONS_HOURS for h in (1, 2, 4, 8))
        # Explicit embargo test: fabricated future prices past the cutoff are
        # NOT allowed to mature events at the discovery/holdout border.
        reference = holdout - pd.Timedelta(hours=3)
        key = {reference.value: 100.}
        for n in range(1, 33):
            key[(reference + n * STEP).value] = 90.
        assert series_short_returns("A_USDT", reference, {"A_USDT": key}, holdout) is None
        # Verify a frozen feature modification is detected (no retrospective
        # cherry-picking from a re-written archive).
        from .data import select_universe
        target = select_universe(p["symbols"], 3, 0)[0]
        original, _ = _files(root / p["study_id"], 0, target)
        if original.exists():
            f = pd.read_csv(original)
            f.loc[0, "close"] = 999999.0
            f.to_csv(original, index=False, compression="gzip")
            try:
                analyze(p["study_id"], root)
                raise AssertionError("Outcome study did not reject tampered source")
            except RuntimeError as exc:
                assert "changed since immutable merge" in str(exc), str(exc)
    print("M5 V0.3 SELFTEST PASS: discovery price outcomes, 8h holdout purge, frozen file hashes, no MFE/MAE claims")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
