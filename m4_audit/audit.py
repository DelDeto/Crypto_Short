"""M4 V0.2.1: frozen-sample tail-risk and robustness audit; research only.

Do not change H1, discard extreme outcomes, infer real PnL or promote live.
Input is the immutable M4 V0.2 artifact from GitHub run #38206513291.
"""
import argparse,csv,hashlib,json,math,random,statistics
from collections import Counter,defaultdict
from datetime import datetime
from pathlib import Path

SOURCE_RUN=38206513291
SOURCE_MANIFEST="m4event-ed877792e8b4f42b"
HORIZONS=(4,12,24,48)

def load(path):
    with open(path,encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))

def num(row,key):
    x=row.get(key)
    return float(x) if x not in (None,"") else None

def avg(xs):
    vals=[float(x) for x in xs if x is not None and math.isfinite(float(x))]
    return round(statistics.fmean(vals),6) if vals else None

def median(xs):
    vals=[float(x) for x in xs if x is not None and math.isfinite(float(x))]
    return round(statistics.median(vals),6) if vals else None

def quantile(xs,q):
    vals=sorted(float(x) for x in xs if x is not None and math.isfinite(float(x)))
    if not vals:return None
    p=(len(vals)-1)*q;lo=int(p);hi=math.ceil(p)
    return round(vals[lo]*(hi-p)+vals[hi]*(p-lo),6) if lo!=hi else round(vals[lo],6)

def trim(xs,fraction):
    vals=sorted(float(x) for x in xs)
    n=int(len(vals)*fraction)
    return avg(vals[n:len(vals)-n]) if len(vals)>2*n else None

def winsor(xs,fraction):
    low=quantile(xs,fraction);high=quantile(xs,1-fraction)
    return avg([max(low,min(high,float(x))) for x in xs]) if low is not None else None

def validate(events,pairs,study,manifest):
    if manifest["manifest_id"]!=SOURCE_MANIFEST or study["manifest_id"]!=SOURCE_MANIFEST:
        raise RuntimeError("Original manifest ID mismatch")
    if len(events)!=study["event_count"] or len(pairs)!=study["matched_event_count"]:
        raise RuntimeError("Original sample counts changed")
    if not study.get("research_only") or not study.get("no_live_short_signals"):
        raise RuntimeError("Not the frozen research-only sample")
    ek={(x["symbol"],x["signal_time_utc"]):x for x in events}
    pk={(x["symbol"],x["signal_time_utc"]):x for x in pairs}
    if len(ek)!=len(events) or len(pk)!=len(pairs) or not set(pk)<=set(ek):
        raise RuntimeError("Duplicate/missing signal keys")
    start=datetime.fromisoformat(manifest["signal_start"])
    end=datetime.fromisoformat(manifest["signal_end_exclusive"])
    for e in events:
        if not start<=datetime.fromisoformat(e["signal_time_utc"])<end:
            raise RuntimeError("Event outside frozen window")
        if (num(e,"reference_next_open") or 0)<=0:raise RuntimeError("Invalid reference price")
        for h in HORIZONS:
            x=num(e,f"short_{h}h_pct");f=num(e,f"mfe_{h}h_pct");a=num(e,f"mae_{h}h_pct")
            if any(v is None or not math.isfinite(v) for v in (x,f,a)):
                raise RuntimeError("Non-finite forward outcome")
            if x>100.001 or f>100.001 or f<0 or a<0 or f+.001<max(0,x) or a+.001<max(0,-x):
                raise RuntimeError("OHLC future excursions inconsistent with returns")
    for key,p in pk.items():
        if not 1<=int(p["n_controls"])<=3:raise RuntimeError("Invalid control count")
        for h in HORIZONS:
            x=num(p,f"event_short_{h}h_pct");c=num(p,f"control_short_{h}h_pct");d=num(p,f"paired_edge_{h}h_pct")
            if abs(x-num(ek[key],f"short_{h}h_pct"))>0.00003 or abs(x-c-d)>0.00003:
                raise RuntimeError("Altered paired outcomes or arithmetic")
    if abs(avg(num(p,"paired_edge_24h_pct") for p in pairs)-study["matched_pair_edge_24h_mean_pct"])>.00003:
        raise RuntimeError("Original paired edge not reproduced")

def bootstrap_by_day(pairs,reps=4000):
    days=defaultdict(list)
    for p in pairs:days[p["signal_time_utc"][:10]].append(num(p,"paired_edge_24h_pct"))
    keys=sorted(days)
    if len(keys)<5:return [None,None]
    rng=random.Random(421);means=[]
    for _ in range(reps):
        sample=[keys[rng.randrange(len(keys))] for _ in keys]
        means.append(statistics.fmean(v for key in sample for v in days[key]))
    means.sort()
    return [round(means[int(.025*(reps-1))],6),round(means[int(.975*(reps-1))],6)]

def tail_risk(events):
    shorts=[num(e,"short_24h_pct") for e in events]
    maes=[num(e,"mae_24h_pct") for e in events]
    worst=sorted(shorts)[:max(1,math.ceil(.05*len(shorts)))]
    flags=[]
    for e in events:
        reasons=[]
        if num(e,"mae_24h_pct")>=100:reasons.append("MAE_GE_100PCT")
        if abs(num(e,"short_24h_pct"))>=100:reasons.append("ABS_FORWARD_RETURN_GE_100PCT")
        if num(e,"mfe_24h_pct")>=75:reasons.append("MFE_GE_75PCT")
        if reasons:
            flags.append({
                "symbol":e["symbol"],"signal_time_utc":e["signal_time_utc"],
                "reference_next_open":num(e,"reference_next_open"),
                "short_24h_pct":num(e,"short_24h_pct"),
                "mae_24h_pct":num(e,"mae_24h_pct"),
                "mfe_24h_pct":num(e,"mfe_24h_pct"),
                "reason":";".join(reasons),
                "handling":"FLAG_ONLY_KEEP_IN_PRIMARY_SAMPLE"
            })
    stats={
        "events":len(events),"mean_short_24h_pct":avg(shorts),
        "median_short_24h_pct":median(shorts),
        "short_24h_p01_pct":quantile(shorts,.01),
        "short_24h_p05_pct":quantile(shorts,.05),
        "short_24h_p95_pct":quantile(shorts,.95),
        "worst_5pct_average_short_return_pct":avg(worst),
        "mae_24h_median_pct":median(maes),
        "mae_24h_p95_pct":quantile(maes,.95),
        "mae_24h_p99_pct":quantile(maes,.99),
        "mae_24h_max_pct":max(maes),
        "count_mae_ge_5pct":sum(x>=5 for x in maes),
        "count_mae_ge_10pct":sum(x>=10 for x in maes),
        "count_mae_ge_20pct":sum(x>=20 for x in maes),
        "count_mae_ge_50pct":sum(x>=50 for x in maes),
        "count_mae_ge_100pct":sum(x>=100 for x in maes),
        "flagged_extreme_events":len(flags),
    }
    return stats,sorted(flags,key=lambda x:-x["mae_24h_pct"])

def weekly_id(ts):
    d=datetime.fromisoformat(ts).date()
    return f"{d.isocalendar().year}-W{d.isocalendar().week:02d}"

def robustness(pairs,events):
    by_day=defaultdict(list);by_week=defaultdict(list);by_symbol=defaultdict(list)
    for p in pairs:
        val=num(p,"paired_edge_24h_pct")
        by_day[p["signal_time_utc"][:10]].append(val)
        by_week[weekly_id(p["signal_time_utc"])].append(val)
        by_symbol[p["symbol"]].append(val)
    xs=[num(p,"paired_edge_24h_pct") for p in pairs]
    event_lookup={(e["symbol"],e["signal_time_utc"]):e for e in events}
    clean=[]
    for p in pairs:
        e=event_lookup[p["symbol"],p["signal_time_utc"]]
        if num(e,"mae_24h_pct")<100 and abs(num(e,"short_24h_pct"))<100:
            clean.append(num(p,"paired_edge_24h_pct"))
    n=max(1,math.ceil(len(xs)*.01))
    total=sum(xs)
    days=[{"utc_day":key,"n":len(v),"mean_edge_24h_pct":avg(v)} for key,v in sorted(by_day.items())]
    weeks=[{"utc_week":key,"n":len(v),"mean_edge_24h_pct":avg(v)} for key,v in sorted(by_week.items())]
    enough=[x for x in weeks if x["n"]>=10]
    stat={
        "matched_events":len(pairs),"unique_symbols":len(by_symbol),"unique_days":len(by_day),
        "mean_paired_edge_24h_pct":avg(xs),"median_paired_edge_24h_pct":median(xs),
        "trim_1pct_mean_edge_SENSITIVITY":trim(xs,.01),
        "trim_5pct_mean_edge_SENSITIVITY":trim(xs,.05),
        "winsor_1pct_mean_edge_SENSITIVITY":winsor(xs,.01),
        "winsor_5pct_mean_edge_SENSITIVITY":winsor(xs,.05),
        "equal_day_weighted_mean_edge_SENSITIVITY":avg(avg(v) for v in by_day.values()),
        "equal_symbol_weighted_mean_edge_SENSITIVITY":avg(avg(v) for v in by_symbol.values()),
        "flagged_excluded_mean_edge_SENSITIVITY":avg(clean),
        "excluded_in_sensitivity_only":len(xs)-len(clean),
        "mean_worst_1pct_edge_pct":avg(sorted(xs)[:n]),
        "best_1pct_contribution_to_total_edge_pct":round(100*sum(sorted(xs,reverse=True)[:n])/total,4) if total else None,
        "positive_utc_days":sum(avg(v)>0 for v in by_day.values()),
        "weeks_ge_10_events":len(enough),
        "positive_weeks_ge_10_events":sum(x["mean_edge_24h_pct"]>0 for x in enough),
        "utc_day_cluster_bootstrap95_DESCRIPTIVE":bootstrap_by_day(pairs),
        "top5_days":Counter(p["signal_time_utc"][:10] for p in pairs).most_common(5),
        "top5_symbols":Counter(p["symbol"] for p in pairs).most_common(5)
    }
    return stat,days,weeks

def btc_asof_regimes(pairs):
    """Post-hoc BTC 24h descriptions, last 1h candle closed before signal."""
    import pandas as pd
    from m4_research.market import fetch_hourly
    times=[pd.Timestamp(p["signal_time_utc"]) for p in pairs]
    frame,queries=fetch_hourly("BTC_USDT",min(times)-pd.Timedelta(hours=26),
                              max(times)-pd.Timedelta(hours=1))
    rows=[]
    for p in pairs:
        t=pd.Timestamp(p["signal_time_utc"])-pd.Timedelta(hours=1)
        old=t-pd.Timedelta(hours=24)
        if t not in frame.index or old not in frame.index:continue
        prev=float(frame.loc[old,"close"])
        if prev<=0:continue
        ret=100*(float(frame.loc[t,"close"])/prev-1)
        label="BTC_DOWN_LE_2PCT" if ret<=-2 else ("BTC_UP_GE_2PCT" if ret>=2 else "BTC_NEUTRAL")
        rows.append({
            "symbol":p["symbol"],"signal_time_utc":p["signal_time_utc"],
            "btc24h_asof_return_pct":round(ret,6),"btc_regime":label,
            "paired_edge_24h_pct":num(p,"paired_edge_24h_pct"),
            "event_short_24h_pct":num(p,"event_short_24h_pct")
        })
    grouped=defaultdict(list)
    for row in rows:grouped[row["btc_regime"]].append(row)
    summary={
        "status":"DESCRIPTIVE_ONLY_NOT_AN_ENTRY_FILTER",
        "covered":len(rows),"total_matched":len(pairs),"btc_requests":queries,
        "groups":{k:{"n":len(v),
                      "mean_paired_edge_24h_pct":avg(x["paired_edge_24h_pct"] for x in v),
                      "mean_event_short_24h_pct":avg(x["event_short_24h_pct"] for x in v)}
                  for k,v in sorted(grouped.items())}
    }
    return summary,rows

def recheck_ohlcv(flags):
    """MEXC repeat-query check; cannot establish tick accuracy or tradable fills."""
    import pandas as pd
    from m4_research.market import fetch_hourly
    from m4_research.events import future_labels
    rows=[]
    for flag in flags:
        out={"symbol":flag["symbol"],"signal_time_utc":flag["signal_time_utc"],
             "reason":flag["reason"],"verification":"UNAVAILABLE"}
        try:
            ts=pd.Timestamp(flag["signal_time_utc"])
            frame,requests=fetch_hourly(flag["symbol"],ts-pd.Timedelta(hours=30),
                                       ts+pd.Timedelta(hours=50))
            closed_bar_open=ts-pd.Timedelta(hours=1)
            if closed_bar_open not in frame.index:raise RuntimeError("Missing trigger candle")
            i=frame.index.get_loc(closed_bar_open)
            labels=future_labels(frame,i) # Requires 48h of future candles.
            if labels is None:raise RuntimeError("Historical 48h outcome data missing")
            deltas={k:round(float(labels[k])-float(flag[k]),7) for k in (
                "reference_next_open","short_24h_pct","mae_24h_pct","mfe_24h_pct")}
            price_tol=max(1e-7,abs(float(flag["reference_next_open"]))*1e-6)
            return_tol=max(.0001,abs(float(flag["mae_24h_pct"]))*1e-6)
            ok=(abs(deltas["reference_next_open"])<=price_tol
                and all(abs(deltas[k])<=return_tol for k in ("short_24h_pct","mae_24h_pct","mfe_24h_pct")))
            out.update({"verification":"MEXC_CANDLE_REPRODUCED" if ok else "MISMATCH",
                        "deltas":deltas,"requests":requests})
        except Exception as exc:
            out["error"]=str(exc)[:280]
        rows.append(out)
    return rows

def save_csv(path,rows):
    if not rows:return
    keys=list(rows[0].keys())
    with open(path,"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=keys,extrasaction="ignore")
        w.writeheader();w.writerows(rows)

def main(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",default="frozen/v02/output/m4")
    ap.add_argument("--manifest",default="frozen/v02/frozen/m4/manifest.json")
    ap.add_argument("--output",default="output/m4_v021")
    ap.add_argument("--check-market",action="store_true")
    args=ap.parse_args(argv)
    inp=Path(args.input);out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    filenames=("m4_study.json","m4_events.csv","m4_matched_controls.csv","m4_coverage.csv")
    paths={name:inp/name for name in filenames}
    for p in [*paths.values(),Path(args.manifest)]:
        if not p.is_file():raise FileNotFoundError(p)
    study=json.loads(paths["m4_study.json"].read_text(encoding="utf-8"))
    manifest=json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    events=load(paths["m4_events.csv"]);pairs=load(paths["m4_matched_controls.csv"])
    validate(events,pairs,study,manifest)
    risk,flags=tail_risk(events)
    robust,by_day,by_week=robustness(pairs,events)
    btc_summary={"status":"NOT_REQUESTED"};btc_rows=[];rechecks=[]
    if args.check_market:
        try:btc_summary,btc_rows=btc_asof_regimes(pairs)
        except Exception as exc:btc_summary={"status":"UNAVAILABLE","error":str(exc)[:280]}
        rechecks=recheck_ohlcv(flags)
    report={
        "engine":"M4 V0.2.1 Frozen Risk and Robustness Audit",
        "source_run_id":SOURCE_RUN,"source_manifest":SOURCE_MANIFEST,
        "source_sha256":{k:hashlib.sha256(p.read_bytes()).hexdigest() for k,p in paths.items()},
        "research_only":True,"oos_validation":False,"live_trading":False,
        "risk_full_original_sample":risk,"matched_robustness":robust,
        "extreme_flags":flags,"candle_rechecks":rechecks,
        "btc_asof_exploration":btc_summary,
        "decision":"DO_NOT_PROMOTE_H1_TO_TRADEABLE_M4_V03",
        "basis":"Outright short mean negative, descriptive clustered CI spans zero, extreme adverse tails, no execution model/OOS.",
        "limitations":[
            "All original events including extremes remain in primary results.",
            "Trim/winsor/exclusion/weekly/BTC subgroups are sensitivity diagnostics, NOT optimized rules.",
            "Repeated correlated signal events invalidate naive IID significance and no multiple-testing correction is applied.",
            "Same-exchange historical candle reproduction does not guarantee valid tick data or fills.",
            "Today's listed universe omits delisted historic futures; selection has survivorship bias.",
            "No entry, stop, TP, fees, spread, slippage, funding, mark-price liquidation or real fills.",
        ],
        "next_step":"Do not design live short signals yet. Audit primary data anomalies; if pursuing M4, preregister a DISTINCT confirmation mechanism and validate forward on untouched data."
    }
    (out/"m4_v021_audit.json").write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
    save_csv(out/"m4_v021_extreme_events.csv",flags)
    save_csv(out/"m4_v021_rechecks.csv",rechecks)
    save_csv(out/"m4_v021_daily.csv",by_day)
    save_csv(out/"m4_v021_weekly.csv",by_week)
    save_csv(out/"m4_v021_btc_regime.csv",btc_rows)
    summary=(
        "# M4 V0.2.1 — frozen risk and robustness audit\n\n"
        f"**Source:** run #{SOURCE_RUN} · {SOURCE_MANIFEST}. **Research only.**\n\n"
        f"Events: {len(events)} · matched: {len(pairs)} · flagged extremes: {len(flags)}\n\n"
        f"Raw short 24h mean: **{risk['mean_short_24h_pct']}%**; median: {risk['median_short_24h_pct']}%.\n\n"
        f"24h MAE ≥10%: **{risk['count_mae_ge_10pct']}/{len(events)}**.\n\n"
        f"Raw paired 24h edge: **{robust['mean_paired_edge_24h_pct']} percentage points**.\n\n"
        f"Equal-day edge (sensitivity): **{robust['equal_day_weighted_mean_edge_SENSITIVITY']} pp**.\n\n"
        f"UTC-day cluster bootstrap 95% (descriptive): **{robust['utc_day_cluster_bootstrap95_DESCRIPTIVE']}**.\n\n"
        "**Decision: DO_NOT_PROMOTE_H1_TO_TRADEABLE_M4_V03**. All extremes retained.\n"
    )
    (out/"m4_v021_summary.md").write_text(summary,encoding="utf-8")
    print(json.dumps({
        "decision":report["decision"],"source_run":SOURCE_RUN,"n_events":len(events),
        "n_matched":len(pairs),"risk":risk,"robustness":robust,
        "btc_regimes":btc_summary,"candle_rechecks":rechecks
    },indent=2,ensure_ascii=False))
    return 0

if __name__=="__main__":raise SystemExit(main())
