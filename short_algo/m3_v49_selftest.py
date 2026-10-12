"""Offline, deterministic smoke tests for M3 V4.9.1 shadow evidence safeguards."""
from datetime import datetime
from .m3_v49_prepare import build_manifest
from .m3_v49_config import M3_V49_FORWARD_START,M3_V49_FREEZE_COMMIT
from .m3_v49_merge import _readiness,_edge_checks,_trade_ledger

def main():
    early=build_manifest(datetime.fromisoformat("2026-10-13T04:00:00+00:00"))
    assert early["window_ready"] is False
    assert early["manifest_status"]=="WAITING_FOR_MATURE_FORWARD_WINDOW"
    assert early["forward_days"]==0.0
    assert early["period_start"]==M3_V49_FORWARD_START
    assert early["research_freeze_commit"]==M3_V49_FREEZE_COMMIT
    assert early["blocks"]==[]

    mature=build_manifest(datetime.fromisoformat("2026-10-15T04:00:00+00:00"))
    assert mature["window_ready"] is True
    assert mature["period_start"]==M3_V49_FORWARD_START
    assert mature["period_end"]=="2026-10-13T04:00:00+00:00"
    assert mature["forward_days"]==1.0
    assert mature["block_count"]==1
    assert mature["hypothesis"]["threshold_atr15"]==0.10

    readiness=_readiness({"entries":20,"active_blocks":2,"positive_expectancy_blocks":2},14)
    assert readiness["ready"]
    assert not _readiness({"entries":4,"active_blocks":1,"positive_expectancy_blocks":0},5.125)["ready"]
    edge=_edge_checks(
        {"expectancy_r":0.3,"max_drawdown_r_signal_order":4.0,"expectancy_bootstrap95_r":[0.1,0.5]},
        {"expectancy_r":-0.2,"max_drawdown_r_signal_order":5.0},
    )
    assert edge["pass"] and edge["nominal_bootstrap_ci_excludes_zero"]
    assert not edge["multiple_looks_adjusted"]

    row={
        "symbol":"BTC_USDT","signal_time":"2026-10-12T05:00:00+00:00",
        "m3v45_block":1,"m3v21_retest_penetration_atr15":0.08,
        "m3v45_frozen_exit":{"valid":1,"state":"TP","result_r":1.5,"minutes":180},
    }
    ledger=_trade_ledger([row],mature)
    assert len(ledger)==1 and ledger[0]["h1_shallow_retest"]==1
    assert ledger[0]["outcome_r"]==1.5
    assert ledger[0]["evidence_class"]=="PROSPECTIVE_REPLAY_NOT_REALTIME_SIGNAL_CAPTURE"

    bad=dict(row,signal_time="2026-10-11T05:00:00+00:00")
    try:_trade_ledger([bad],mature)
    except RuntimeError:pass
    else:raise AssertionError("Pre-freeze trade was incorrectly accepted")

    print("M3 V4.9.1 self-test PASS: immature window, mature window, readiness, edge, ledger, pre-freeze protection")
    return 0

if __name__=="__main__":raise SystemExit(main())
