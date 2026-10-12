"""Offline selftest against pinned frozen V0.2 artifact; no network requests."""
import json
from pathlib import Path
from .audit import load,validate,tail_risk,robustness,bootstrap_by_day

def main():
    root=Path("frozen/v02/output/m4")
    manifest=json.loads(Path("frozen/v02/frozen/m4/manifest.json").read_text())
    study=json.loads((root/"m4_study.json").read_text())
    events=load(root/"m4_events.csv")
    pairs=load(root/"m4_matched_controls.csv")
    validate(events,pairs,study,manifest)
    assert len(events)==893 and len(pairs)==844
    risk,flags=tail_risk(events)
    robust,days,weeks=robustness(pairs,events)
    assert risk["count_mae_ge_10pct"]==319
    assert risk["flagged_extreme_events"]==9
    assert risk["mean_short_24h_pct"]==-1.491235
    assert robust["mean_paired_edge_24h_pct"]==.263021
    assert robust["unique_days"]>=50
    assert len(days)>=50 and len(weeks)>=8
    assert any(x["symbol"]=="LSK_USDT" and x["mae_24h_pct"]>1000 for x in flags)
    ci=bootstrap_by_day(pairs,reps=600)
    assert ci[0]<0<ci[1]
    modified=[dict(e) for e in events]
    modified[0]["mae_24h_pct"]="-400"
    try:validate(modified,pairs,study,manifest)
    except RuntimeError:pass
    else:raise AssertionError("Corrupted outcome must fail validation")
    print("M4 V0.2.1 SELFTEST PASS: exact frozen source, integrity, tail events, CI, tamper protection")
    return 0

if __name__=="__main__":raise SystemExit(main())
