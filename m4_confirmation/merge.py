"""M4 V0.2.2 frozen H2 delayed-confirmation event study. Exploratory only."""
import csv,json,math,random,statistics,sys
from collections import Counter,defaultdict
from glob import glob
from pathlib import Path
from m4_audit.audit import load,validate
from .config import SHARD_COUNT,SOURCE_MANIFEST,MIN_MATCHED_EVENTS_DESCRIPTIVE

def _mean(xs):
    xs=[float(x) for x in xs if x is not None and math.isfinite(float(x))]
    return round(statistics.fmean(xs),6) if xs else None

def _median(xs):
    xs=[float(x) for x in xs if x is not None and math.isfinite(float(x))]
    return round(statistics.median(xs),6) if xs else None

def _ci_day(pairs,reps=2000):
    groups=defaultdict(list)
    for p in pairs:groups[p["event_signal_utc"][:10]].append(float(p["paired_edge_24h_pct"]))
    days=sorted(groups)
    if len(days)<5:return [None,None]
    rng=random.Random(422);vals=[]
    for _ in range(reps):
        draws=[days[rng.randrange(len(days))] for _ in days]
        v=[x for d in draws for x in groups[d]]
        vals.append(statistics.fmean(v))
    vals.sort()
    return [round(vals[int(.025*(reps-1))],6),round(vals[int(.975*(reps-1))],6)]

def _write(path,rows):
    if not rows:return
    keys=list(dict.fromkeys(k for r in rows for k in r))
    with open(path,"w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=keys)
        w.writeheader();w.writerows(rows)

def main(root="m4v022_shards",source="frozen/v02",manifest_path="frozen/v022/manifest.json",
         output="output/m4_v022"):
    m=json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if m["source_manifest"]!=SOURCE_MANIFEST or m.get("research_only") is not True:
        raise RuntimeError("M4 source or research status changed")
    base=Path(source)/"output/m4"
    study=json.loads((base/"m4_study.json").read_text(encoding="utf-8"))
    om=json.loads((Path(source)/"frozen/m4/manifest.json").read_text(encoding="utf-8"))
    orig=load(base/"m4_events.csv");oldpairs=load(base/"m4_matched_controls.csv")
    validate(orig,oldpairs,study,om)
    reports=[]
    for p in sorted(glob(root+"/**/shard.json",recursive=True)):
        reports.append(json.loads(Path(p).read_text(encoding="utf-8")))
    if len(reports)!=SHARD_COUNT or {int(x["shard_index"]) for x in reports}!=set(range(SHARD_COUNT)):
        raise RuntimeError("Missing/duplicate M4 H2 shards")
    if any(x["manifest_id"]!=m["manifest_id"] for x in reports):raise RuntimeError("Mixed H2 manifests")
    got_symbols=[s for x in reports for s in x["selected_symbols"]]
    if len(got_symbols)!=len(set(got_symbols)) or sorted(got_symbols)!=m["symbols"]:
        raise RuntimeError("Frozen full symbol cohort incomplete")

    case_rows=[r for x in reports for r in x["cases"]]
    control_rows=[r for x in reports for r in x["controls"]]
    casekeys=[(c["symbol"],c["event_signal_utc"]) for c in case_rows]
    origmap={(x["symbol"],x["signal_time_utc"]):x for x in orig}
    if len(casekeys)!=len(set(casekeys)) or set(casekeys)!=set(origmap):
        raise RuntimeError("H2 did not evaluate every one of the 893 frozen H1 cases")
    controls={}
    for c in control_rows:
        k=(c["symbol"],c["event_signal_utc"],int(c["lag_hours"]))
        if k in controls:raise RuntimeError("Duplicate H2 control record")
        controls[k]=c
    cases={(c["symbol"],c["event_signal_utc"]):c for c in case_rows}
    oldpairmap={(x["symbol"],x["signal_time_utc"]):x for x in oldpairs}

    counts=Counter(c["confirmation_status"] for c in case_rows)
    confirmed=sorted((c for c in case_rows if c["confirmation_status"]=="CONFIRMED"),
                     key=lambda c:(c["event_signal_utc"],c["symbol"]))
    confirmed_keys={(c["symbol"],c["event_signal_utc"]) for c in confirmed}
    paired=[];unpaired=[]
    for c in confirmed:
        key=(c["symbol"],c["event_signal_utc"])
        p=oldpairmap.get(key)
        if p is None:
            unpaired.append({"symbol":c["symbol"],"event_signal_utc":c["event_signal_utc"],
                             "reason":"NO_ORIGINAL_H1_MATCH"});continue
        lag=int(c["confirmation_lag_hours"]);available=[]
        for sym in p["control_symbols"].split(";"):
            ct=controls.get((sym,c["event_signal_utc"],lag))
            if ct and ct["outcome_status"]=="OK":available.append(ct)
        if not available:
            unpaired.append({"symbol":c["symbol"],"event_signal_utc":c["event_signal_utc"],
                             "reason":"MATCHED_CONTROLS_NOT_MATURE_OR_MISSING"});continue
        row={
            "symbol":c["symbol"],"event_signal_utc":c["event_signal_utc"],
            "confirmation_lag_hours":lag,"confirmation_time_utc":c["confirmation_time_utc"],
            "control_symbols":";".join(x["symbol"] for x in available),
            "usable_controls":len(available),
            "h1_same_case_short_24h_pct":c["source_short_24h_pct"],
        }
        for h in (4,12,24,48):
            val=float(c[f"short_{h}h_pct"])
            ctrl=_mean(x[f"short_{h}h_pct"] for x in available)
            row[f"confirmed_short_{h}h_pct"]=val
            row[f"control_short_{h}h_pct"]=ctrl
            row[f"paired_edge_{h}h_pct"]=round(val-ctrl,6)
        paired.append(row)

    incomplete=sum(counts[k] for k in ("DATA_MISSING","DATA_GAP","DATA_INVALID",
        "SOURCE_PRICE_MISMATCH","FETCH_ERROR","NOT_MATURED"))
    valid_count=len(orig)-incomplete
    valid_fraction=valid_count/len(orig)
    paired_rate=len(paired)/len(confirmed) if confirmed else None
    data_valid=valid_fraction>=0.90 and (not confirmed or (paired_rate or 0)>=0.50)
    study_out={
        "engine":"M4 V0.2.2 H2 Confirmation Study",
        "source_h1_run":m["source_run"],"source_manifest":SOURCE_MANIFEST,
        "manifest_id":m["manifest_id"],"research_only":True,"live_promotion":False,
        "oos":False,"sample_scope":m["sample_scope"],
        "hypothesis_predeclared":m["rule"],
        "original_h1_events":len(orig),"original_h1_matched":len(oldpairs),
        "case_status_counts":dict(sorted(counts.items())),
        "h2_confirmed":len(confirmed),"h2_rejected_no_confirm_or_reclaimed":counts["NO_CONFIRMATION_6H"]+counts["RECLAIMED_BEFORE_CONFIRM"],
        "h2_confirm_rate_among_classified":round(len(confirmed)/valid_count,5) if valid_count else None,
        "h2_valid_cases_pct":round(100*valid_fraction,3),
        "h2_confirmed_with_aligned_controls":len(paired),
        "h2_confirmed_without_controls":len(unpaired),
        "control_matching_rate_on_confirmed":round(paired_rate,5) if paired_rate is not None else None,
        "h2_confirmation_lags":dict(sorted(Counter(str(c["confirmation_lag_hours"]) for c in confirmed).items())),
        "h1_original_full_24h_mean_pct":_mean(x["short_24h_pct"] for x in orig),
        "h1_original_same_confirmed_24h_mean_pct":_mean(c["source_short_24h_pct"] for c in confirmed),
        "h2_delayed_confirmed_24h_mean_pct":_mean(c["short_24h_pct"] for c in confirmed),
        "h2_delayed_confirmed_24h_median_pct":_median(c["short_24h_pct"] for c in confirmed),
        "h2_delayed_mae_24h_median_pct":_median(c["mae_24h_pct"] for c in confirmed),
        "h2_delayed_mae_24h_ge10_pct":round(100*sum(float(c["mae_24h_pct"])>=10 for c in confirmed)/len(confirmed),3) if confirmed else None,
        "aligned_matched":{
            str(h):{
                "n":len(paired),
                "mean_h2_short_pct":_mean(p[f"confirmed_short_{h}h_pct"] for p in paired),
                "mean_same_time_control_short_pct":_mean(p[f"control_short_{h}h_pct"] for p in paired),
                "mean_paired_edge_percentage_points":_mean(p[f"paired_edge_{h}h_pct"] for p in paired),
            } for h in (4,12,24,48)
        },
        "matched_edge24_day_cluster_bootstrap95_DESCRIPTIVE":_ci_day(paired),
        "daily_consistency":{
            "unique_event_days":len({c["event_signal_utc"][:10] for c in confirmed}),
            "unique_matched_days":len({p["event_signal_utc"][:10] for p in paired}),
            "positive_matched_days":sum(_mean(q["paired_edge_24h_pct"] for q in paired if q["event_signal_utc"][:10]==d)>0
                                        for d in {p["event_signal_utc"][:10] for p in paired}),
        },
        "worst_delayed_24h_short_cases":sorted(
            ({"symbol":c["symbol"],"event_signal_utc":c["event_signal_utc"],
              "lag_hours":c["confirmation_lag_hours"],"short_24h_pct":c["short_24h_pct"],
              "mae_24h_pct":c["mae_24h_pct"]} for c in confirmed),
            key=lambda r:r["short_24h_pct"])[:12],
        "data_valid":data_valid,
        "decision":("DESCRIPTIVE_H2_ONLY_NO_LIVE_DEPLOYMENT" if data_valid
                    else "DATA_INCOMPLETE_NO_H2_CONCLUSION"),
        "interpretation":{
            "min_30_matched_events_descriptive":len(paired)>=MIN_MATCHED_EVENTS_DESCRIPTIVE,
            "mean_h2_short_24h_positive":_mean(c["short_24h_pct"] for c in confirmed) is not None and _mean(c["short_24h_pct"] for c in confirmed)>0,
            "paired_edge_24h_positive":_mean(p["paired_edge_24h_pct"] for p in paired) is not None and _mean(p["paired_edge_24h_pct"] for p in paired)>0,
            "descriptive_only_no_oos":True,
            "never_trade_from_this_report":True
        },
        "limitations":[
            "H2 invented after inspecting H1 data; re-analysis of same 2026 Aug-Oct sample is NOT OOS.",
            "Confirmations use only completed 1h bars; outcome reference is next candle OPEN, not executed fills.",
            "Matched controls frozen at H1 time, rebased to identical H2 entry clock; no selection from future control outcomes.",
            "H2 vs H1 original involves different entry times/holding paths, not an experimental treatment-effect estimate.",
            "No trading costs, funding, liquidation, spread, 15m trigger precision, mark price, position sizing or orders.",
            "Today's surviving-contract universe introduces historical survivorship bias.",
            "Day bootstrap is descriptive; overlapping events and multiple hypotheses violate naive significance inference.",
            "Missing data, not-yet-mature outcomes and changed candles explicitly logged, never counted as rejection.",
        ],
    }
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    (out/"m4_v022_analysis.json").write_text(json.dumps(study_out,indent=2,ensure_ascii=False),encoding="utf-8")
    _write(out/"m4_v022_cases.csv",case_rows)
    _write(out/"m4_v022_matched_rebased.csv",paired)
    _write(out/"m4_v022_unmatched.csv",unpaired)
    _write(out/"m4_v022_control_coverage.csv",[
        {"outcome_status":k,"count":v} for k,v in sorted(Counter(x["outcome_status"] for x in control_rows).items())
    ])
    with open(out/"m4_v022_summary.md","w",encoding="utf-8") as f:
        f.write("# M4 V0.2.2 — Failed Breakout Confirmation Study\n\n")
        f.write(f"**Decision:** {study_out['decision']} (research only)\n\n")
        f.write(f"H1 source events: {len(orig)}; confirmed: **{len(confirmed)}**; matched: **{len(paired)}**.\n\n")
        f.write(f"Mean 24h short after H2 confirmation: **{study_out['h2_delayed_confirmed_24h_mean_pct']}%**.\n\n")
        f.write(f"Matched same-entry-clock edge: **{study_out['aligned_matched']['24']['mean_paired_edge_percentage_points']} percentage points**.\n\n")
        f.write(f"Clustered descriptive CI: {study_out['matched_edge24_day_cluster_bootstrap95_DESCRIPTIVE']}.\n\n")
        f.write("**Not OOS, not trading PnL, no live promotion.**\n")
    print(json.dumps({
        "decision":study_out["decision"],"data_valid":data_valid,
        "status_counts":study_out["case_status_counts"],"confirmed":len(confirmed),
        "matched":len(paired),"h2_short_24h_mean":study_out["h2_delayed_confirmed_24h_mean_pct"],
        "paired_24h":study_out["aligned_matched"]["24"],
        "day_cluster_bootstrap95":study_out["matched_edge24_day_cluster_bootstrap95_DESCRIPTIVE"]
    },indent=2,ensure_ascii=False))
    return 0 if data_valid else 2

if __name__=="__main__":
    args=sys.argv[1:]
    raise SystemExit(main(*args))
