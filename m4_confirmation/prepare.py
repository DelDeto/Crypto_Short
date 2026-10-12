"""Freeze source V0.2 event identities and matched-control universe; offline only."""
import hashlib,json
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path
from m4_audit.audit import load,validate
from .config import SOURCE_RUN,SOURCE_MANIFEST,SHARD_COUNT,CONFIRM_WITHIN_HOURS

def build(source="frozen/v02",out="output/m4_v022"):
    folder=Path(source);base=folder/"output/m4"
    study=json.loads((base/"m4_study.json").read_text(encoding="utf-8"))
    manifest=json.loads((folder/"frozen/m4/manifest.json").read_text(encoding="utf-8"))
    events=load(base/"m4_events.csv")
    pairs=load(base/"m4_matched_controls.csv")
    validate(events,pairs,study,manifest)
    if len(events)!=893 or len(pairs)!=844:raise RuntimeError("Unexpected source counts")
    by_symbol=defaultdict(lambda:{"cases":0,"controls":0})
    for e in events:by_symbol[e["symbol"]]["cases"]+=1
    for p in pairs:
        ctr=[s for s in p["control_symbols"].split(";") if s]
        if len(ctr)!=int(p["n_controls"]):raise RuntimeError("Control source schema mismatch")
        for s in set(ctr):by_symbol[s]["controls"]+=1
    audit={
        "version":"M4_V0.2.2_EXPLORATORY",
        "source_run":SOURCE_RUN,"source_manifest":SOURCE_MANIFEST,
        "source_file_sha256":{
            name:hashlib.sha256((base/name).read_bytes()).hexdigest()
            for name in ("m4_study.json","m4_events.csv","m4_matched_controls.csv","m4_coverage.csv")
        },
        "manifest_sha256":hashlib.sha256((folder/"frozen/m4/manifest.json").read_bytes()).hexdigest(),
        "source_event_count":len(events),"source_matched_event_count":len(pairs),
        "symbols":sorted(by_symbol),
        "symbol_count":len(by_symbol),
        "shard_count":SHARD_COUNT,
        "confirm_hours":CONFIRM_WITHIN_HOURS,
        "rule":"From end of H1 candle, within six 1h closed bars first close < H1 sweep-low; no preceding/intervening close >= H1 old 48h high; entry reference next bar open",
        "outcome_hours":[4,12,24,48],
        "study_created_utc":datetime.now(timezone.utc).isoformat(),
        "research_only":True,"live_promotion":False,
        "sample_scope":"SAME_H1_DISCOVERY_DATA_POST_HOC_EXPLORATION_NOT_OOS",
        "matched_control_policy":"Original V0.2 control symbols locked at H1 time; measure controls at same H2 confirmation time, no rematching on outcomes",
        "cautions":[
            "H2 developed after viewing H1 data; no untouched OOS claim.",
            "No TP, SL, fees, slippage, funding, fill model or trade execution.",
            "Data missing or not matured is reported separately from rejection.",
        ],
    }
    audit["manifest_id"]="m4v022-"+hashlib.sha256(json.dumps({k:v for k,v in audit.items() if k!="study_created_utc"},sort_keys=True).encode()).hexdigest()[:16]
    Path(out).mkdir(parents=True,exist_ok=True)
    (Path(out)/"manifest.json").write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding="utf-8")
    return audit

def main():
    m=build()
    print(json.dumps({k:m[k] for k in ("manifest_id","source_event_count","source_matched_event_count","symbol_count","rule","sample_scope")},ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__":raise SystemExit(main())
