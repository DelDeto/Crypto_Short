"""Offline 14-day M5 stability smoke test; no exchange requests or future peeking."""
from pathlib import Path
import tempfile
import pandas as pd
from .data import STEP
from .v02 import create_plan,collect_chunk,shard_status,merge_study
from .v03_discovery import analyze
from .v031 import run

NOW=pd.Timestamp("2026-10-13T16:06:00Z")
END=NOW.floor("15min")-STEP
TIMES=pd.date_range(end=END,periods=1600,freq="15min",tz="UTC")
EVENT_AT=END-pd.Timedelta(days=10)

def fake_fetch(symbol, first, last):
    index=TIMES[(TIMES>=first)&(TIMES<=last)]
    close=pd.Series(100.0,index=index)
    if symbol=="A_USDT":
        for j in range(1,34):
            t=EVENT_AT+j*STEP
            if t in close.index:
                close.loc[t]=100.0-.08*j
    frame=pd.DataFrame({
        "open":close.copy(),"high":close*1.001,"low":close*.999,
        "close":close.copy(),"amount":9000.0,"volume":500.0},index=index)
    if symbol=="A_USDT" and EVENT_AT in frame.index:
        frame.loc[EVENT_AT,["open","high","low","close","amount"]]=[103,114,98,100,40000]
    return frame,1

def main():
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp)/"studies"
        universe=["BTC_USDT","A_USDT","B_USDT","C_USDT","D_USDT","E_USDT"]
        plan=create_plan(universe,{"offline":True},now=NOW,days=14,shards=3,
                         study_id="m5-v031-offline-14d",root=root)
        cutoff=pd.Timestamp(plan["holdout_reserved_start_utc"])
        assert EVENT_AT+pd.Timedelta(hours=8)<cutoff
        for shard in range(3):
            while not shard_status(plan["study_id"],shard,root)["complete"]:
                result=collect_chunk(plan["study_id"],shard,max_new=3,
                                    root=root,fetch_fn=fake_fetch)
                assert not result["transient_failures"],result
        merged=merge_study(plan["study_id"],root)
        assert merged["accepted_symbols"]==6,merged
        report=analyze(plan["study_id"],root,include_daily=True)
        assert report["holdout_outcome_rows_read"]==0
        assert report["total_discovery_events_before_purge"]>0
        assert report["families"]["E03"]["paired_event_observations"]>=1
        d=report["daily_event_stability"]["E03"]
        assert d["calendar_days_with_events"]>=1
        assert d["descriptive_stability"]["4h"]["positive_day_count"]>=1
        assert d["by_day"]
        finished=run(plan["study_id"],root)
        assert finished["status"]=="EXPANDED_DISCOVERY_ONLY_UNCONFIRMED"
        assert finished["valid_untouched_confirmation"] is False
        assert finished["holdout_performance_disclosed"] is False
        assert (root/plan["study_id"]/"discovery"/"v031_daily_stability.json").exists()
        try:
            run(plan["study_id"],root)
            raise AssertionError("Report overwrite was not blocked")
        except RuntimeError as exc:
            assert "already archived" in str(exc),exc
    print("M5 V0.3.1 SELFTEST PASS: 14d checkpoints, daily stability, holdout embargo, immutable report")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
