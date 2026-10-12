"""M4 V0.2 descriptive event study with as-of matched controls.

This is EXPLORATORY, not an OOS backtest or a tradable strategy.
Controls are selected solely by signal-time features, never by outcomes.
"""
import csv,hashlib,json,math,os,random,statistics,sys
from collections import Counter,defaultdict
from glob import glob
from .config import OUT_DIR,HORIZONS_HOURS,MATCHED_CONTROLS_PER_EVENT

def _mean(xs):
    vals=[float(x) for x in xs if x is not None and math.isfinite(float(x))]
    return round(sum(vals)/len(vals),6) if vals else None

def _median(xs):
    vals=[float(x) for x in xs if x is not None and math.isfinite(float(x))]
    return round(statistics.median(vals),6) if vals else None

def _summarize(rows):
    d={"n":len(rows)}
    for h in HORIZONS_HOURS:
        for key in ("short","mfe","mae"):
            name=f"{key}_{h}h_pct"
            d[f"avg_{name}"]=_mean([r.get(name) for r in rows])
            d[f"median_{name}"]=_median([r.get(name) for r in rows])
    d["short_24h_gt_3pct_rate"]=_mean([float(r["short_24h_pct"]>=3.0) for r in rows if r.get("short_24h_pct") is not None])
    return d

def _distance(event,control):
    """Distance features are all AS-OF; no forward outcomes enter matching."""
    er=float(event["return_24h_asof_pct"]);cr=float(control["return_24h_asof_pct"])
    ev=float(event["volatility_24h_asof_pct"]);cv=float(control["volatility_24h_asof_pct"])
    et=float(event["quote_turnover_24h_asof"]);ct=float(control["quote_turnover_24h_asof"])
    if abs(er-cr)>12.0:return None
    if abs(ev-cv)>12.0:return None
    if et<=0 or ct<=0:return None
    return abs(er-cr)/6.0+abs(ev-cv)/6.0+0.35*abs(math.log(et/ct))

def match_controls(events,controls):
    by_time=defaultdict(list)
    for c in controls:
        if not c.get("raw_h1_event"):
            by_time[c["signal_time_utc"]].append(c)
    pairs=[];unmatched=[];reused_controls=Counter()
    for e in sorted(events,key=lambda x:(x["signal_time_utc"],x["symbol"])):
        matches=[]
        for c in by_time.get(e["signal_time_utc"],[]):
            if c["symbol"]==e["symbol"]:continue
            dist=_distance(e,c)
            if dist is not None:matches.append((dist,c["symbol"],c))
        matches.sort(key=lambda x:(x[0],x[1]))
        chosen=[x[2] for x in matches[:MATCHED_CONTROLS_PER_EVENT]]
        if not chosen:
            unmatched.append({"symbol":e["symbol"],"signal_time_utc":e["signal_time_utc"]})
            continue
        for c in chosen:reused_controls[(c["symbol"],c["signal_time_utc"])]+=1
        paired={
            "symbol":e["symbol"],"signal_time_utc":e["signal_time_utc"],
            "n_controls":len(chosen),
            "control_symbols":";".join(x["symbol"] for x in chosen),
            "event_return24_asof_pct":e["return_24h_asof_pct"],
            "event_volatility24_asof_pct":e["volatility_24h_asof_pct"],
            "event_quote_turnover24_asof":e["quote_turnover_24h_asof"],
        }
        for h in HORIZONS_HOURS:
            key=f"short_{h}h_pct"
            ctrl=_mean([c[key] for c in chosen])
            paired[f"event_{key}"]=e[key]
            paired[f"control_{key}"]=ctrl
            paired[f"paired_edge_{h}h_pct"]=round(float(e[key])-float(ctrl),6)
        pairs.append(paired)
    return pairs,unmatched,reused_controls

def _day_cluster_ci(pairs,h=24,rep=2000):
    by_day=defaultdict(list)
    for p in pairs:
        by_day[p["signal_time_utc"][:10]].append(float(p[f"paired_edge_{h}h_pct"]))
    days=sorted(by_day)
    if len(days)<5:return [None,None]
    rng=random.Random(404);samples=[]
    for _ in range(rep):
        drawn=[days[rng.randrange(len(days))] for _ in days]
        vals=[x for d in drawn for x in by_day[d]]
        samples.append(sum(vals)/len(vals))
    samples.sort()
    return [round(samples[int(.025*(rep-1))],6),round(samples[int(.975*(rep-1))],6)]

def _write_csv(path,rows):
    if not rows:return
    with open(path,"w",encoding="utf-8",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0].keys()),extrasaction="ignore")
        writer.writeheader();writer.writerows(rows)

def main(root="m4_shards",manifest_path="frozen/m4/manifest.json"):
    with open(manifest_path,encoding="utf-8") as f:manifest=json.load(f)
    reports=[]
    for path in sorted(glob(os.path.join(root,"**","shard.json"),recursive=True)):
        with open(path,encoding="utf-8") as f:reports.append(json.load(f))
    n=int(manifest["shard_count"])
    if len(reports)!=n or {r["shard_index"] for r in reports}!=set(range(n)):
        raise RuntimeError(f"Missing or duplicate shards: {len(reports)}/{n}")
    if any(r["manifest_id"]!=manifest["manifest_id"] or r["shard_count"]!=n for r in reports):
        raise RuntimeError("M4 manifest mismatch")

    covered=[];events=[];controls=[];symbols=[]
    for r in reports:
        symbols+=r["selected_symbols"]
        covered+=r["coverage_audit"]
        events+=r["events"]
        controls+=r["control_pool"]
    if len(symbols)!=len(set(symbols)) or sorted(symbols)!=sorted(manifest["symbols"]):
        raise RuntimeError("Frozen universe was not scanned exactly once")
    if len(covered)!=len(symbols):
        raise RuntimeError("Coverage report missing symbols")
    keys=[(e["symbol"],e["signal_time_utc"]) for e in events]
    if len(keys)!=len(set(keys)):raise RuntimeError("Duplicate M4 H1 events")
    pool_keys=[(e["symbol"],e["signal_time_utc"]) for e in controls]
    if len(pool_keys)!=len(set(pool_keys)):raise RuntimeError("Duplicate control observations")
    eligible=sum(bool(r["eligible"]) for r in covered)
    errors=[r for r in covered if r.get("reason")=="FETCH_OR_PARSE_ERROR"]
    no_amount=sum((r.get("audit") or {}).get("drop_missing_amount",0) for r in covered)
    eligible_points=sum((r.get("audit") or {}).get("eligible_points",0) for r in covered)

    pairs,unmatched,reused=match_controls(events,controls)
    edge24=_mean([p["paired_edge_24h_pct"] for p in pairs])
    coverage_ok=eligible>=max(10,int(0.5*len(symbols))) and len(errors)<=max(3,int(0.20*len(symbols)))
    labels_ok=eligible_points>0
    research_ready=coverage_ok and labels_ok
    decision=("EXPLORATORY_EVENT_STUDY_ONLY" if research_ready
              else "INSUFFICIENT_VALID_DATA_NO_CONCLUSION")
    out={
        "engine":"M4 V0.1/V0.2 Liquidity Sweep Failed Breakout Event Study",
        "manifest_id":manifest["manifest_id"],"snapshot_utc":manifest["snapshot_utc"],
        "research_only":True,"no_live_short_signals":True,
        "universe_snapshot_count":len(symbols),"history_eligible_symbols":eligible,
        "history_ineligible_symbols":len(symbols)-eligible,
        "fetch_errors_count":len(errors),"fetch_errors_sample":errors[:30],
        "asof_liquidity_missing_or_low_observations":no_amount,
        "candidate_observations":eligible_points,"event_count":len(events),
        "matched_event_count":len(pairs),"unmatched_event_count":len(unmatched),
        "control_reuse_max":max(reused.values()) if reused else 0,
        "event_summary":_summarize(events),
        "matched_event_summary":_summarize([e for e in events if (e["symbol"],e["signal_time_utc"]) in {(p["symbol"],p["signal_time_utc"]) for p in pairs}]),
        "matched_control_24h_short_mean_pct":_mean([p["control_short_24h_pct"] for p in pairs]),
        "matched_pair_edge_24h_mean_pct":edge24,
        "day_cluster_bootstrap_95pct_edge24_pct":_day_cluster_ci(pairs),
        "comparisons_by_horizon":{
            str(h):{
                "n_matched":len(pairs),
                "mean_event_short_return_pct":_mean([p[f"event_short_{h}h_pct"] for p in pairs]),
                "mean_control_short_return_pct":_mean([p[f"control_short_{h}h_pct"] for p in pairs]),
                "mean_paired_difference_pct":_mean([p[f"paired_edge_{h}h_pct"] for p in pairs]),
            } for h in HORIZONS_HOURS
        },
        "validation":{
            "coverage_ok":coverage_ok,"label_sample_nonempty":labels_ok,
            "matched_sample_30_plus":len(pairs)>=30,
            "five_plus_signal_days":len({e["signal_time_utc"][:10] for e in events})>=5,
            "not_out_of_sample":True,
            "no_preentry_leakage":True,
            "data_status":decision,
        },
        "caveats":[
            "Historical 60d universe is today's surviving contracts (survivorship bias).",
            "This is an exploratory event study, NOT an executable backtest: no fees, slippage, spread, TP, SL, funding or fill simulation.",
            "Outcomes are indexed from the next 1h candle OPEN, used only for labels, never event or control selection.",
            "Matched control group is based on same-time runup, volatility, 24h quote turnover; matching success/availability is reported.",
            "Day-cluster bootstrap is descriptive and not adjusted for hypothesis search, repeated looks, sector correlation, or selection bias.",
            "No AI, no trade recommendations, no portfolio exposure or live automation.",
        ],
        "next_step":"If there are >=30 matched events, audit leakage and regime robustness before designing entry/SL/TP and untouched OOS.",
    }
    os.makedirs(OUT_DIR,exist_ok=True)
    _write_csv(os.path.join(OUT_DIR,"m4_events.csv"),sorted(events,key=lambda x:(x["signal_time_utc"],x["symbol"])))
    _write_csv(os.path.join(OUT_DIR,"m4_matched_controls.csv"),pairs)
    _write_csv(os.path.join(OUT_DIR,"m4_coverage.csv"),covered)
    with open(os.path.join(OUT_DIR,"m4_study.json"),"w",encoding="utf-8") as f:json.dump(out,f,ensure_ascii=False,indent=2)
    with open(os.path.join(OUT_DIR,"m4_summary.md"),"w",encoding="utf-8") as f:
        f.write("# M4 V0.1 + V0.2 — Failed Breakout Event Study\n\n")
        f.write(f"**Status: {decision} — research only, not tradable.**\n\n")
        f.write(f"Snapshot universe: {len(symbols)} / history-eligible: {eligible}; H1 events: {len(events)}; matched: {len(pairs)}.\n\n")
        f.write(f"Mean 24h paired edge: **{edge24} percentage points** (descriptive).\n\n")
        f.write(f"Day-cluster bootstrap 95%: {out['day_cluster_bootstrap_95pct_edge24_pct']}.\n\n")
        f.write("**Historical universe survivorship bias; NO strategy performance conclusions or signals.**\n")
    print(json.dumps({k:out[k] for k in (
        "validation","universe_snapshot_count","history_eligible_symbols","fetch_errors_count",
        "event_count","matched_event_count","candidate_observations",
        "matched_pair_edge_24h_mean_pct","day_cluster_bootstrap_95pct_edge24_pct",
    )},ensure_ascii=False,indent=2))
    return 0 if research_ready else 2

if __name__=="__main__":
    root=sys.argv[1] if len(sys.argv)>1 else "m4_shards"
    manifest_path=sys.argv[2] if len(sys.argv)>2 else "frozen/m4/manifest.json"
    raise SystemExit(main(root,manifest_path))
