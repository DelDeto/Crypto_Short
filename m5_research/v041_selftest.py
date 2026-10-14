"""Offline M5 V0.4.1 regression: entry clocks, cost, outliers, sealed OHLC.

Creates synthetic V0.2 -> V0.4 histories ONLY in a temp directory.
No MEXC network calls, no orders.
"""
import gzip
import hashlib
import json
import tempfile
from pathlib import Path
import pandas as pd

from .data import STEP
from .v02 import create_plan, dump
from .v04_plan import STUDY_ID, EXECUTION_ID, EVENTS, make_plan, read_plan as source_plan
from . import v04_run
from . import v041_robustness as audit

def candles(sym,start,end):
    idx=pd.date_range(start=start,end=end,freq="15min",tz="UTC")
    f=pd.DataFrame({"open":100.0,"high":100.1,"low":99.9,"close":100.0},index=idx)
    return f,1

def pure_tests():
    t=pd.Timestamp("2026-10-10T00:00:00Z")
    bars,_=candles("A_USDT",t,t+32*STEP)
    bars.loc[t,"high"]=200.0
    bars.loc[t,"low"]=1.0
    bars.loc[t+STEP,["open","high","low","close"]]=[100.,104.,96.,100.]
    bars.loc[t+2*STEP,["open","high","low","close"]]=[99.,99.4,98.4,99.]
    case,err=audit.simulate(bars,"A_USDT",t,anchor=100.)
    assert err is None
    early=case["entry_delays"]["immediate"]["1h"]
    late=case["entry_delays"]["delayed_15m"]["1h"]
    assert early["actual_bars_held"]==4
    assert late["actual_bars_held"]==3
    assert early["entry_open"]==100. and late["entry_open"]==99.
    assert early["mfe_pct"] < 99., "Event candle's low was improperly counted"
    assert early["fixed_sl_tp"]["sl1_tp2"]["0"]["exit_reason"]=="SL_FIRST_SAME_BAR"
    assert case["entry_delays"]["delayed_15m"]["4h"]["actual_bars_held"]==15
    flat0=audit._net_short_pct(100.,100.,0)
    flat20=audit._net_short_pct(100.,100.,20)
    assert abs(flat0+0.1)<1e-6,flat0
    assert flat20<flat0<0
    assert audit._robustness([], "x")["count"]==0
    entries=[{"day_utc":str(i),"e":v} for i,v in enumerate([12.,0.,0.,0.,0.,0.])]
    o=audit._robustness(entries,"e")
    assert o["mean"]==2. and o["median"]==0.
    assert o["leave_one_event_out_min"]==0.
    assert o["trim_one_each_side_mean"]==0.
    bars=bars.drop(index=t+17*STEP)
    assert audit.simulate(bars,"A_USDT",t)[1]=="MISSING_15M_BAR_IN_8H_PATH"

def end_to_end():
    now=pd.Timestamp("2026-10-13T16:06:00Z")
    universe=["BTC_USDT","A_USDT","B_USDT","C_USDT","D_USDT"]
    with tempfile.TemporaryDirectory() as tmp:
        sr=Path(tmp)/"studies"
        ar=Path(tmp)/"execution"
        plan=create_plan(universe,{"test":True},now=now,days=14,shards=1,
                         study_id=STUDY_ID,root=sr)
        base=sr/STUDY_ID
        merged=base/"merged";merged.mkdir(parents=True)
        dump(merged/"research_manifest.json",{
            "plan_sha256":plan["plan_sha256"],
            "status":"FULL_FROZEN_COHORT_MERGED",
        })
        t0=pd.Timestamp(plan["first_bar_open_utc"])
        boundary=pd.Timestamp(plan["holdout_reserved_start_utc"])
        events=[]
        for e in EVENTS:
            for d in range(1,7):
                t=t0+pd.Timedelta(days=d,hours=2)
                assert t+pd.Timedelta(hours=9)<boundary
                events.append({"event_id":e,"symbol":"A_USDT",
                    "control_symbols":["B_USDT","C_USDT"],
                    "last_closed_bar_open_utc":t.isoformat(),"asof_close":100.})
        events.sort(key=lambda e:e["last_closed_bar_open_utc"])
        src=merged/"market_events.jsonl.gz"
        with gzip.open(src,"wt",encoding="utf-8") as f:
            for e in events: f.write(json.dumps(e)+"\n")
        disc=base/"discovery";disc.mkdir()
        dump(disc/"v031_daily_stability.json",{
            "study_plan_sha256":plan["plan_sha256"],
            "source_merged_event_sha256":hashlib.sha256(src.read_bytes()).hexdigest(),
            "status":"EXPANDED_DISCOVERY_ONLY_UNCONFIRMED",
        })
        frozen=make_plan(root=sr,output_root=ar)
        assert len(frozen["events"])==48 and frozen["symbol_count"]==3
        old_r=v04_run.read_plan
        old_a=audit.read_plan
        v04_run.read_plan=lambda output_root=ar: source_plan(output_root,root=sr)
        audit.read_plan=lambda output_root=ar: source_plan(output_root,root=sr)
        try:
            completed=v04_run.collect(max_new=3,output_root=ar,fetch_fn=candles)
            assert completed["status"]=="OHLC_COLLECTION_COMPLETE"
            old_report=v04_run.summarize(output_root=ar)
            assert old_report["complete_matched_event_total"]==48
            result=audit.run(output_root=ar)
            assert result["events_audited"]==48
            assert result["holdout_opened"] is False
            assert result["families"]["E01"]["horizons"]["4h"]["immediate"]["gross_pct"]["mean"]==0.
            assert result["families"]["E01"]["horizons"]["4h"]["immediate"]["fee_and_slippage_net_pct"]["0"]["mean"] < 0.
            assert result["entry_timing"]["delayed_15m"].startswith("T+30m")
            try:
                audit.run(output_root=ar)
                raise AssertionError("Sealed report overwritten")
            except RuntimeError as exc:
                assert "already sealed" in str(exc)
            # Tampered OHLC cannot be used in sensitivity research.
            ohlc=ar/EXECUTION_ID/"ohlc"/"A_USDT.csv.gz"
            with ohlc.open("ab") as f: f.write(b"tamper")
            try:
                audit.analyze(output_root=ar)
                raise AssertionError("Tampered OHLC accepted")
            except RuntimeError as exc:
                assert "Archived OHLC changed" in str(exc)
        finally:
            v04_run.read_plan=old_r
            audit.read_plan=old_a

def main():
    pure_tests()
    end_to_end()
    print("M5 V0.4.1 SELFTEST PASS: delayed entry fixed exit clock, fee+slippage, SL-first, LOO, OHLC hashes, immutable report")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
