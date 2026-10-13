"""M4 H3 all-market AS-OF snapshot; capture predictors BEFORE outcome candles.

This script NEVER computes labels, placing buy/sell orders is impossible here.
Each snapshot is an immutable timestamped research observation.
"""
from concurrent.futures import ThreadPoolExecutor,as_completed
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
import hashlib,json,os
import pandas as pd
from m4_research.market import snapshot_universe
from .provider import fetch_hourly_paced
from .features import read_features,match_asof,H
from .lock import lock_protocol
from .protocol import PROTOCOL_HASH,FREEZE_START_UTC,HYPOTHESIS_ID,rules,prospective_started

def _utc(ts):
    t=pd.Timestamp(ts)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")

def scan(now=None,symbol_fn=snapshot_universe,fetch_fn=fetch_hourly_paced):
    started=_utc(now or datetime.now(timezone.utc))
    last_closed=started.floor("h")-H
    signal_time=last_closed+H
    batch=signal_time.strftime("%Y%m%dT%HZ")
    filename=f"m4-h3-{batch}.json"
    result={
        "batch_id":batch,"protocol_hash":PROTOCOL_HASH,"hypothesis_id":HYPOTHESIS_ID,
        "rules":rules(),"freeze_start_utc":FREEZE_START_UTC,
        "run_started_at_utc":started.isoformat(),
        "signal_time_utc":signal_time.isoformat(),
        "last_closed_bar_open_utc":last_closed.isoformat(),
        "virtual_entry_reference_utc":(signal_time+H).isoformat(),
        "output_filename":filename,
        "collection_policy":"Every 4h latest completed 1h; no retroactive signal backfill",
        "universe_policy":"LIVE_UNIVERSE_SNAPSHOT_NO_HISTORICAL_SURVIVORSHIP_RECONSTRUCTION",
        "outcome_data_present":False,"research_only":True,"allow_live_short":False,
    }
    if signal_time<_utc(FREEZE_START_UTC):
        return {**result,"status":"PRE_FREEZE_NO_COLLECTION","catalogue_count":0,
                "eligible_count":0,"h3_cases":[],"controls":[],
                "audit":{"skipped_before_freeze":True}}
    symbols,audit=symbol_fn()
    symbols=sorted(set(symbols))
    if len(symbols)<50:raise RuntimeError("Unexpectedly small MEXC futures universe")
    if "BTC_USDT" not in symbols:raise RuntimeError("BTC futures missing from universe")
    begin=last_closed-25*H
    btc,btc_requests=fetch_fn("BTC_USDT",begin,last_closed)
    if last_closed not in btc.index:raise RuntimeError("BTC context missing latest closed hour")
    features=[];reasons=Counter();errors={};query_count=btc_requests
    def job(symbol):
        if symbol=="BTC_USDT":return read_features(symbol,btc,btc,last_closed),0
        frame,n=fetch_fn(symbol,begin,last_closed)
        return read_features(symbol,frame,btc,last_closed),n
    with ThreadPoolExecutor(max_workers=5) as pool:
        futuremap={pool.submit(job,s):s for s in symbols}
        for future in as_completed(futuremap):
            symbol=futuremap[future]
            try:
                (rec,reason),n=future.result()
                query_count+=n
                if rec:features.append(rec)
                else:reasons[reason]+=1
            except Exception as exc:
                reasons["FETCH_ERROR"]+=1
                errors[symbol]=str(exc)[:220]
    features.sort(key=lambda x:x["symbol"])
    h3=[f for f in features if f["h3_event"]]
    matched=match_asof(h3,features)
    finished=pd.Timestamp.now(tz="UTC") if now is None else started+pd.Timedelta(minutes=5)
    capture_before_virtual_entry=finished<_utc(result["virtual_entry_reference_utc"])
    coverage_ratio=len(features)/len(symbols)
    valid=(coverage_ratio>=0.70 and len(errors)<=max(5,int(.20*len(symbols)))
           and capture_before_virtual_entry)
    # Cohort is fixed at collection time; no current-day universe is applied to historical test.
    result.update({
        "status":"REGISTERED" if valid else "INVALID_CAPTURE_EXCLUDED_FROM_PRIMARY",
        "run_finished_at_utc":finished.isoformat(),
        "capture_before_virtual_entry":capture_before_virtual_entry,
        "catalogue_count":len(symbols),"catalogue_audit":audit,
        "catalogue_symbols":symbols,
        "catalogue_sha256":hashlib.sha256("\n".join(symbols).encode()).hexdigest(),
        "eligible_count":len(features),"coverage_ratio":round(coverage_ratio,6),
        "comparison_eligible_count":sum(f["comparison_eligible"] for f in features),
        "h3_cases":matched,"candidate_count":len(matched),
        "matched_h3_cases":sum(x["control_count"]>0 for x in matched),
        "fetch_queries":query_count,
        "audit":{"rejections":dict(reasons),"fetch_errors_sample":dict(list(sorted(errors.items()))[:40]),
                 "asof_feature_records":features,
                 "closed_candle_validation":"All symbols evaluated at identical completed 1h UTC open"},
        "outcome_data_present":False,
    })
    return result

def main():
    # Fail closed on an absent/late or edited pre-registration lock.
    lock_protocol()
    now=pd.Timestamp.now(tz="UTC")
    # Only canonical four-hour slots can enter this preregistered sample.
    # GitHub workflow_dispatch outside these slots cannot invent new H3 windows.
    canonical_hour=now.floor("h")
    if canonical_hour.hour%4!=0:
        print(json.dumps({"status":"OFF_CADENCE_NO_CAPTURE",
            "utc_now":now.isoformat(),
            "next_slot_policy":"00/04/08/12/16/20 UTC only",
            "historical_backfill":False},indent=2))
        return 0
    # A backup trigger must NEVER fetch again after the first valid/invalid
    # original run has already archived this exact canonical UTC snapshot.
    batch=canonical_hour.strftime("%Y%m%dT%HZ")
    previous=Path("state/m4_forward/snapshots")/f"m4-h3-{batch}.json"
    if previous.exists():
        old=json.loads(previous.read_text(encoding="utf-8"))
        if (old.get("batch_id")!=batch or
            old.get("protocol_hash")!=PROTOCOL_HASH or
            old.get("hypothesis_id")!=HYPOTHESIS_ID or
            old.get("outcome_data_present") is not False):
            raise RuntimeError("Existing canonical H3 snapshot is corrupted")
        print(json.dumps({"status":"DUPLICATE_CANONICAL_SLOT_SKIPPED",
                          "batch_id":batch,"original_status":old.get("status"),
                          "no_second_market_fetch":True},indent=2))
        return 0
    r=scan()
    Path("output/m4_forward").mkdir(parents=True,exist_ok=True)
    if r["status"]=="PRE_FREEZE_NO_COLLECTION":
        print(json.dumps({"status":r["status"],"freeze_utc":FREEZE_START_UTC,
            "protocol_sha256":PROTOCOL_HASH,"will_archive":False},indent=2))
        return 0
    filename=Path("output/m4_forward")/r["output_filename"]
    filename.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding="utf-8")
    state_path=Path("state/m4_forward/snapshots")/r["output_filename"]
    os.makedirs(state_path.parent,exist_ok=True)
    if state_path.exists():
        with open(state_path,encoding="utf-8") as f:prior=json.load(f)
        if prior["protocol_hash"]!=r["protocol_hash"] or prior["batch_id"]!=r["batch_id"]:
            raise RuntimeError("A conflicting snapshot already exists. No overwrite.")
        print("Snapshot already registered, leaving immutable original:",state_path)
    else:
        state_path.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({
        "status":r["status"],"batch_id":r["batch_id"],
        "catalogue":r["catalogue_count"],"eligible":r["eligible_count"],
        "h3_cases":len(r["h3_cases"]),"with_controls":r["matched_h3_cases"],
        "snapshot_file":str(state_path),"freeze_utc":FREEZE_START_UTC
    },ensure_ascii=False,indent=2))
    return 0  # Archive INVALID snapshots explicitly; do not pretend they are valid evidence.

if __name__=="__main__":raise SystemExit(main())
