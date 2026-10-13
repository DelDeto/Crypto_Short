"""Zero-network tests: freeze, causal H3 features, control matching and late outcomes."""
import math
import pandas as pd
from .protocol import PROTOCOL_HASH,FREEZE_START_UTC
from .features import read_features,match_asof
from .capture import scan
from .settle import settle_batch,future_outcomes
from .first_look import evaluation
from .health import inventory
import json
from .lock import lock_protocol
from pathlib import Path
import tempfile

def make_frame(symbol,closed):
    ts=pd.date_range(closed-pd.Timedelta(hours=30),periods=31,freq="h",tz="UTC")
    end=ts[-1]; assert end==closed
    vals=[100.0]*31
    for i in range(6,25):vals[i]=100+12*(i-6)/18
    is_h3=symbol=="ALT_USDT"
    for i in range(25,31):
        vals[i]=112+( (-4 if is_h3 else -2)*(i-24)/6)
    if symbol=="BTC_USDT":vals=[100.0]*31
    op=[vals[0]]+vals[:-1]
    data={"open":op,
          "close":vals,
          "high":[max(o,c)+.5 for o,c in zip(op,vals)],
          "low":[min(o,c)-.5 for o,c in zip(op,vals)],
          "volume":[100]*31,"amount":[25000]*31}
    return pd.DataFrame(data,index=ts)

def outcome_frame(symbol,entry,end):
    ts=pd.date_range(entry,end,freq="h",tz="UTC")
    vals=[108-0.14*i if symbol=="ALT_USDT" else 110+0.05*i for i in range(len(ts))]
    return pd.DataFrame({
       "open":vals,"close":[x-0.04 if symbol=="ALT_USDT" else x+0.04 for x in vals],
       "high":[x+0.3 for x in vals],"low":[x-0.3 for x in vals],
       "volume":[100]*len(ts),"amount":[25000]*len(ts)
    },index=ts)

def main():
    assert len(PROTOCOL_HASH)==64
    # Reliability-only checks use synthetic immutable snapshots and never
    # access genuine outcome values or trigger a market-data request.
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        prereg={
            "hypothesis_id":"M4_H3_RELATIVE_WEAKNESS_MOMENTUM_EXHAUSTION_V1",
            "protocol_sha256":PROTOCOL_HASH,
            "freeze_start_utc":FREEZE_START_UTC,
            "locked_at_utc":"2026-10-12T10:00:00+00:00",
        }
        (root/"H3_protocol_lock.json").write_text(json.dumps(prereg),encoding="utf-8")
        check=pd.Timestamp("2026-10-13T04:10:00Z")
        early_health=inventory(check,root)
        assert early_health["missing_slots_after_grace"]==1
        assert early_health["status"]=="NO_VALID_SNAPSHOTS"
        sn_dir=root/"snapshots"
        sn_dir.mkdir()
        demo={
            "batch_id":"20261013T00Z",
            "hypothesis_id":prereg["hypothesis_id"],
            "protocol_hash":PROTOCOL_HASH,
            "signal_time_utc":"2026-10-13T00:00:00+00:00",
            "virtual_entry_reference_utc":"2026-10-13T01:00:00+00:00",
            "run_finished_at_utc":"2026-10-13T00:25:00+00:00",
            "capture_before_virtual_entry":True,
            "status":"REGISTERED",
            "outcome_data_present":False,
            "output_filename":"m4-h3-20261013T00Z.json",
        }
        (sn_dir/demo["output_filename"]).write_text(json.dumps(demo),encoding="utf-8")
        fixed_health=inventory(check,root)
        assert fixed_health["missing_slots_after_grace"]==0
        assert fixed_health["valid_captures"]==1
        assert fixed_health["performance_visible"] is False

    with tempfile.TemporaryDirectory() as td:
        p=Path(td)/"lock.json"
        obj=lock_protocol(p,pd.Timestamp("2026-10-12T10:00:00Z").to_pydatetime())
        assert obj["protocol_sha256"]==PROTOCOL_HASH
        assert lock_protocol(p,pd.Timestamp("2026-10-15T00:00:00Z").to_pydatetime())==obj
        late=Path(td)/"late.json"
        try:lock_protocol(late,pd.Timestamp("2026-10-13T00:00:00Z").to_pydatetime())
        except RuntimeError:pass
        else:raise AssertionError("Late preregistration incorrectly allowed")
    now=pd.Timestamp("2026-10-13T04:17:00+00:00")
    closed=pd.Timestamp("2026-10-13T03:00:00+00:00")
    symbols=["BTC_USDT","ALT_USDT"]+[f"CTRL{i}_USDT" for i in range(51)]
    def fake_fetch(symbol,start,end):
        return make_frame(symbol,closed).loc[start:end],1
    before=scan(pd.Timestamp("2026-10-12T20:17:00+00:00"),
                lambda:(symbols,{}),fake_fetch)
    assert before["status"]=="PRE_FREEZE_NO_COLLECTION"
    event,why=read_features("ALT_USDT",make_frame("ALT_USDT",closed),
       make_frame("BTC_USDT",closed),closed)
    assert why is None and event["h3_event"] is True,event
    normal,why=read_features("CTRL0_USDT",make_frame("CTRL0_USDT",closed),
       make_frame("BTC_USDT",closed),closed)
    assert normal["comparison_eligible"] and not normal["h3_event"]
    controls=match_asof([event],[normal])
    assert controls[0]["control_symbols"]==["CTRL0_USDT"]

    s=scan(now,lambda:(symbols,{"synthetic":True}),fake_fetch)
    assert s["status"]=="REGISTERED"
    assert s["candidate_count"]==1 and s["matched_h3_cases"]==1
    assert s["outcome_data_present"] is False
    assert len(s["h3_cases"][0]["control_symbols"])==3
    assert s["capture_before_virtual_entry"]
    entry=pd.Timestamp(s["virtual_entry_reference_utc"])
    def fetch_out(sym,start,end):
        return outcome_frame(sym,start,end),1
    assert settle_batch(s,now+pd.Timedelta(hours=50),fetch_out) is None
    settled=settle_batch(s,now+pd.Timedelta(hours=70),fetch_out)
    assert settled["outcome_count"]==1
    assert settled["outcome_rows"][0]["status"]=="OK"
    assert settled["outcome_rows"][0]["short_48h_pct"]>0
    assert settled["outcome_rows"][0]["paired_edge_48h_pp"]>0
    assert settled["capture_finished_before_entry"]
    assert s["outcome_data_present"] is False
    assert future_outcomes(outcome_frame("ALT_USDT",entry,entry+pd.Timedelta(hours=47)),entry) is not None

    corrupt={**s,"protocol_hash":"0"*64}
    try:settle_batch(corrupt,now+pd.Timedelta(hours=70),fetch_out)
    except RuntimeError:pass
    else:raise AssertionError("Tampered protocol accepted")
    early=evaluation(now)
    assert early["status"]=="ACCUMULATING_NO_PERFORMANCE_EVALUATION"
    assert "statistics" not in early
    print("M4 H3 forward selftest PASS: prefreeze, no-lookahead, controls, sealed future outcomes, freeze hash, no early peeking")
    return 0

if __name__=="__main__":raise SystemExit(main())
