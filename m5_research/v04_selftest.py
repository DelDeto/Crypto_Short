"""Offline end-to-end regression for M5 V0.4 OHLC execution-risk pilot."""
from pathlib import Path
import gzip
import json
import tempfile

import pandas as pd

from .data import STEP
from .v02 import create_plan, dump
from .v04_path import research_path
from . import v04_plan as planner
from . import v04_run as runner

NOW=pd.Timestamp("2026-10-13T16:06:00Z")
ALL_SYMBOLS=["BTC_USDT","A_USDT","B_USDT","C_USDT","D_USDT"]

def mock_ohlc(symbol, start, end):
    ix=pd.date_range(start=start,end=end,freq="15min",tz="UTC")
    d=pd.DataFrame({"open":100.0,"high":100.10,"low":99.90,
                    "close":100.0},index=ix)
    return d,1

def check_path():
    t=pd.Timestamp("2026-10-10T00:00:00Z")
    bars,_=mock_ohlc("A_USDT",t,t+32*STEP)
    both=t+STEP
    bars.loc[both,["open","high","low","close"]]=[100.,103.,97.,100.]
    row,error=research_path("A_USDT",t,bars,anchor_close=100.)
    assert error is None,error
    hour=row["hours"]["1h"]
    assert round(hour["mfe_pct"],4)==3.0
    assert round(hour["mae_pct"],4)==3.0
    assert hour["path_sl_tp"]["sl1_tp2"]["exit_reason"]=="SL_FIRST_SAME_BAR"
    assert hour["path_sl_tp"]["sl1_tp2"]["stress_20bps_pct"]==-1.2
    # The event bar itself can have a wild low, but it cannot be counted
    # as a new short's favorable move before entry.
    bars.loc[t,["open","high","low","close"]]=[100.,140.,60.,100.]
    no_lookahead,err=research_path("A_USDT",t,bars,anchor_close=100.)
    assert not err
    assert no_lookahead["hours"]["1h"]["mfe_pct"]==3.0
    # Next bar OPEN, not already-observed event CLOSE, defines the entry.
    bars.loc[both,["open","high","low","close"]]=[101.,103.,97.,101.]
    changed,err=research_path("A_USDT",t,bars,anchor_close=100.)
    assert not err
    assert changed["entry_proxy_next_bar_open"]==101.
    assert changed["hours"]["1h"]["mae_pct"]<3.
    bars=bars.drop(index=t+5*STEP)
    assert research_path("A_USDT",t,bars)[1]=="MISSING_15M_BAR_IN_8H_PATH"

def main():
    check_path()
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)/"study"
        archive=Path(td)/"execution"
        p=create_plan(ALL_SYMBOLS,{"synthetic":True},now=NOW,days=14,shards=1,
                      study_id=planner.STUDY_ID,root=root)
        base=root/planner.STUDY_ID
        market=base/"merged"
        market.mkdir(parents=True)
        dump(market/"research_manifest.json",{
            "status":"FULL_FROZEN_COHORT_MERGED",
            "plan_sha256":p["plan_sha256"],
        })
        boundary=pd.Timestamp(p["holdout_reserved_start_utc"])
        origin=pd.Timestamp(p["first_bar_open_utc"])
        rows=[]
        # Fixed one family event on each of six as-of calendar days.
        # No lookahead selection of which event is profitable.
        for i,eid in enumerate(planner.EVENTS):
            for day in range(1,7):
                t=origin+pd.Timedelta(days=day,hours=2)
                assert t+pd.Timedelta(hours=9)<boundary
                rows.append({"event_id":eid,"symbol":"A_USDT",
                             "control_symbols":["B_USDT","C_USDT"],
                             "last_closed_bar_open_utc":t.isoformat(),
                             "asof_close":100.})
        rows.sort(key=lambda x:x["last_closed_bar_open_utc"])
        gz=market/"market_events.jsonl.gz"
        with gzip.open(gz,"wt",encoding="utf-8") as fd:
            for row in rows:
                fd.write(json.dumps(row)+"\n")
        import hashlib
        hashed=hashlib.sha256(gz.read_bytes()).hexdigest()
        d=base/"discovery"
        d.mkdir(exist_ok=True)
        dump(d/"v031_daily_stability.json",{
            "study_plan_sha256":p["plan_sha256"],
            "status":"EXPANDED_DISCOVERY_ONLY_UNCONFIRMED",
            "source_merged_event_sha256":hashed,
        })
        frozen=planner.make_plan(root=root,output_root=archive)
        assert frozen["selected_family_counts"]=={e:6 for e in planner.EVENTS}
        assert len(frozen["events"])==48
        assert frozen["symbols"]==["A_USDT","B_USDT","C_USDT"]
        assert planner.read_plan(archive,root)["plan_sha256"]==frozen["plan_sha256"]
        old=runner.read_plan
        runner.read_plan=lambda path=archive:planner.read_plan(path,root)
        try:
            progress=runner.collect(max_new=2,output_root=archive,fetch_fn=mock_ohlc)
            assert progress["pending_count"]==1,progress
            complete=runner.collect(max_new=2,output_root=archive,fetch_fn=mock_ohlc)
            assert complete["status"]=="OHLC_COLLECTION_COMPLETE",complete
            repeated=runner.collect(max_new=2,output_root=archive,fetch_fn=mock_ohlc)
            assert repeated["attempted_this_run"]==0
            report=runner.summarize(output_root=archive)
            assert report["selected_event_total"]==48
            assert report["complete_matched_event_total"]==48,report["attrition"]
            assert report["ohlc_archived_count"]==3
            assert report["holdout_performance_read"] is False
            assert report["fees_spread_slippage_funding_unmeasured"]
            assert all(report["families"][e]["complete_case_with_asof_control"]==6
                       for e in planner.EVENTS)
            assert report["families"]["E01"]["horizon_metrics"]["4h"]["mfe_pct"]["mean"]>=0
            try:
                runner.summarize(output_root=archive)
                raise AssertionError("Refiling a sealed path report succeeded")
            except RuntimeError as exc:
                assert "already sealed" in str(exc)
        finally:
            runner.read_plan=old
        # Confirm file source SHA change is detected in plan validation.
        plan_file=archive/planner.EXECUTION_ID/"plan.json"
        tampered=json.loads(plan_file.read_text())
        tampered["max_events_per_family"]=30
        dump(plan_file,tampered)
        try:
            planner.read_plan(archive,root)
            raise AssertionError("Tampered freeze was accepted")
        except RuntimeError as exc:
            assert "fingerprint mismatch" in str(exc),str(exc)
    print("M5 V0.4 SELFTEST PASS: frozen 8-family as-of sample, close-bar entry firewall, 15m SL-first OHLC, resumable cache")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
