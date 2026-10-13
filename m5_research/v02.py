"""M5 V0.2 reproducible historical market-wide research registry.

Plan freezes current MEXC universe and historical clock window. Chunked
checkpoint collection persists as-of features only (not raw OHLCV). Merge
waits for all symbol outcomes and then assigns cross-shard controls using
same-UTC features. No PnL, labels, signals, trades, or future data.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np
import pandas as pd

from .config import EVENTS, MIN_CANDLE_COVERAGE, WARMUP_BARS
from .data import STEP, _utc, coverage, record_catalogue, request_candles, select_universe
from .events import features_asof

ROOT = Path("state/m5_research/studies")
PILOT_ROOT = Path("output/m5_research/v02_pilot")
MAX_GITHUB_ARCHIVE_DAYS = 21
FEATURE_FIELDS = (
    "bar_open_utc", "symbol", "close", "return_1h_pct", "return_4h_pct",
    "volatility_24h_pct", "turnover_24h_usdt", "quality_ready",
    *tuple(EVENTS),
)
PLAN_SCHEMA = "M5_V02_FROZEN_HISTORICAL_COHORT_V1"

def dump(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def checked_id(value):
    if not re.fullmatch(r"m5-[a-z0-9][a-z0-9-]{2,75}", value):
        raise ValueError("Study id must be lowercase m5-<letters-digits-hyphens>, length 6..79")
    return value

def create_plan(symbols, audit, now=None, days=7, shards=16, study_id=None, root=ROOT,
                pilot=False, symbols_limit=0):
    if not 1 <= days <= MAX_GITHUB_ARCHIVE_DAYS:
        raise ValueError("GitHub archival is limited to 1..21 historical days; use object storage for 180 days")
    if not 1 <= shards <= 64:
        raise ValueError("Shard count must be between 1 and 64")
    full = sorted(set(symbols))
    if len(full) < 5 or "BTC_USDT" not in full:
        raise RuntimeError("Missing BTC or empty MEXC catalogue")
    now = _utc(now or pd.Timestamp.now(tz="UTC"))
    # Never include candle still forming at the time the plan is frozen.
    end = now.floor("15min") - STEP
    start = end - pd.Timedelta(days=days)
    chosen = full[:symbols_limit] if symbols_limit else full
    study_id = checked_id(study_id or f"m5-{end.strftime('%Y%m%d-%H%M')}-{days}d-{shards}s" +
                           ("-pilot" if pilot else ""))
    obj = {
        "schema": PLAN_SCHEMA, "study_id": study_id, "created_utc": now.isoformat(),
        "first_bar_open_utc": start.isoformat(), "last_closed_bar_open_utc": end.isoformat(),
        "holdout_reserved_start_utc": (start + (end-start)*.75).floor("15min").isoformat(),
        "historical_days": days, "shards": shards, "pilot": bool(pilot),
        "catalogue_count": len(full),
        "catalogue_sha256": hashlib.sha256("\n".join(full).encode()).hexdigest(),
        "catalogue_audit": audit,
        "symbols": chosen, "symbol_count": len(chosen),
        "universe_policy": "FROZEN_CURRENT_LISTED_MEXC_FUTURES_SURVIVORSHIP_BIAS",
        "features_policy": "CLOSED_15M_ASOF_NO_OUTCOME_LABELS",
        "data_store": "GIT_VERSIONED_COMPACT_ASOF_FEATURES_NO_DURABLE_OHLCV",
        "research_only": True,
        "no_signals": True, "no_orders": True,
    }
    obj["plan_sha256"] = digest(obj)
    dest = Path(root) / study_id / "plan.json"
    if dest.exists():
        if load(dest) != obj:
            raise RuntimeError("Plan already frozen; never overwrite a study")
    else:
        dump(dest, obj)
    return obj

def validate_plan(plan):
    d = dict(plan)
    sha = d.pop("plan_sha256", "")
    if not sha or digest(d) != sha or d.get("schema") != PLAN_SCHEMA:
        raise RuntimeError("Frozen study plan hash conflict")
    if len(set(d["symbols"])) != d["symbol_count"]:
        raise RuntimeError("Duplicate or corrupted frozen symbol catalogue")
    if not 1 <= d["historical_days"] <= MAX_GITHUB_ARCHIVE_DAYS:
        raise RuntimeError("Outside approved bounded Git archival budget")
    checked_id(d["study_id"])
    return d

def _symbol_folder(study_root, shard_index):
    return study_root / "shards" / f"shard-{shard_index:02d}"

def _files(study_root, shard_index, symbol):
    path = _symbol_folder(study_root, shard_index)
    return path / "features" / (symbol + ".csv.gz"), path / "rejected" / (symbol + ".json")

def _read_frame_csv(path):
    f = pd.read_csv(path, index_col=0, parse_dates=True)
    if f.index.tz is None:
        f.index = f.index.tz_localize("UTC")
    else:
        f.index = f.index.tz_convert("UTC")
    return f.sort_index()

def _save_features(path, features):
    payload = features.reset_index().rename(columns={"index": "bar_open_utc"})
    payload["bar_open_utc"] = payload["bar_open_utc"].map(lambda t: _utc(t).isoformat())
    payload = payload[list(FEATURE_FIELDS)].copy()
    for key in ("quality_ready", *EVENTS):
        payload[key] = payload[key].astype(int)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload.to_csv(path, index=False, compression="gzip")

def collect_chunk(study_id, shard_index, max_new=6, root=ROOT, fetch_fn=request_candles):
    if max_new < 1 or max_new > 20:
        raise ValueError("Checkpoint group size must be 1..20")
    study_root = Path(root) / checked_id(study_id)
    plan = load(study_root / "plan.json")
    validate_plan(plan)
    if not 0 <= shard_index < plan["shards"]:
        raise ValueError("Invalid shard index")
    expected = select_universe(plan["symbols"], plan["shards"], shard_index, 0)
    start = _utc(plan["first_bar_open_utc"])
    end = _utc(plan["last_closed_bar_open_utc"])
    warmup = start - WARMUP_BARS * STEP
    context = study_root / "context" / "BTC_USDT.csv.gz"
    # Re-fetch BTC if cache is missing; all sources checked against one plan.
    if context.exists():
        btc = _read_frame_csv(context)
    else:
        btc, _ = fetch_fn("BTC_USDT", warmup, end)
        if coverage(btc, start, end) < MIN_CANDLE_COVERAGE:
            raise RuntimeError("BTC 15m history insufficient; fail closed")
        context.parent.mkdir(parents=True, exist_ok=True)
        btc.to_csv(context, compression="gzip")
    if coverage(btc, start, end) < MIN_CANDLE_COVERAGE:
        raise RuntimeError("Frozen BTC context coverage invalid")
    started = 0
    accepted, rejected, temporary = [], [], {}
    requests = 0
    for symbol in expected:
        feat_path, reject_path = _files(study_root, shard_index, symbol)
        if feat_path.exists() or reject_path.exists():
            continue
        if started >= max_new:
            break
        started += 1
        try:
            if symbol == "BTC_USDT":
                frame, n = btc, 0
            else:
                frame, n = fetch_fn(symbol, warmup, end)
            requests += n
            ratio = coverage(frame, start, end)
            if ratio < MIN_CANDLE_COVERAGE:
                dump(reject_path, {"symbol": symbol, "status": "INSUFFICIENT_HISTORY",
                                   "coverage": ratio, "plan_sha256": plan["plan_sha256"]})
                rejected.append(symbol)
                continue
            f = features_asof(symbol, frame, btc, start)
            if f.empty or not f["quality_ready"].any():
                dump(reject_path, {"symbol": symbol, "status": "NO_VALID_ASOF_FEATURES",
                                   "coverage": ratio, "plan_sha256": plan["plan_sha256"]})
                rejected.append(symbol)
                continue
            _save_features(feat_path, f)
            accepted.append(symbol)
        except Exception as exc:
            # TRANSIENT API failures are NOT marked terminal; next run may retry.
            temporary[symbol] = str(exc)[:200]
        print(f"[M5/V02] shard {shard_index} {symbol}: " +
              ("ACCEPTED" if symbol in accepted else
               "REJECTED" if symbol in rejected else "RETRY_LATER"), flush=True)
    status = shard_status(study_id, shard_index, root)
    report = {
        **status, "attempted_new": started,
        "new_accepted_symbols": accepted, "new_rejected_symbols": rejected,
        "transient_failures": temporary, "requests_this_chunk": requests,
    }
    dump(Path("output/m5_research/v02") / "chunk.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report

def shard_status(study_id, shard_index, root=ROOT):
    study_root = Path(root) / checked_id(study_id)
    plan = load(study_root / "plan.json")
    validate_plan(plan)
    expected = select_universe(plan["symbols"], plan["shards"], shard_index, 0)
    valid = 0
    excluded = 0
    pending = []
    for s in expected:
        p, q = _files(study_root, shard_index, s)
        if p.exists() and q.exists():
            raise RuntimeError(f"Conflicting accepted/rejected output for {s}")
        if p.exists():
            valid += 1
        elif q.exists():
            marker = load(q)
            if marker.get("plan_sha256") != plan["plan_sha256"]:
                raise RuntimeError("Rejection marker belongs to different study")
            excluded += 1
        else:
            pending.append(s)
    return {
        "study_id": study_id, "shard_index": shard_index, "expected": len(expected),
        "accepted": valid, "excluded": excluded, "pending": len(pending),
        "pending_first": pending[:10],
        "complete": not pending,
        "research_only": True,
    }

def _read_feature(path, expected_symbol):
    f = pd.read_csv(path)
    missing = set(FEATURE_FIELDS) - set(f.columns)
    if missing:
        raise RuntimeError(f"Missing stored as-of columns {missing} in {path}")
    if not f.empty and (f["symbol"] != expected_symbol).any():
        raise RuntimeError("Feature file contains a different symbol")
    t = pd.to_datetime(f["bar_open_utc"], utc=True)
    if t.duplicated().any() or not t.is_monotonic_increasing:
        raise RuntimeError("Unsorted/duplicated stored candle timestamps")
    for key in ("quality_ready", *EVENTS):
        f[key] = f[key].astype(int)
        if not f[key].isin([0, 1]).all():
            raise RuntimeError("Invalid event flag")
    f["bar_open_utc"] = t
    return f

def merge_study(study_id, root=ROOT, *, allow_pilot=False):
    study_root = Path(root) / checked_id(study_id)
    plan = load(study_root / "plan.json")
    validate_plan(plan)
    if plan["pilot"] and not allow_pilot:
        raise RuntimeError("Pilot cannot be certified as full-market coverage")
    all_expected = set(plan["symbols"])
    seen = set()
    dataframes = []
    rejects = Counter()
    digests = {}
    for i in range(plan["shards"]):
        for s in select_universe(plan["symbols"], plan["shards"], i, 0):
            if s in seen:
                raise RuntimeError("Duplicated symbol across shards")
            seen.add(s)
            path, rejected = _files(study_root, i, s)
            if path.exists() and rejected.exists():
                raise RuntimeError("Ambiguous archived state: both success and reject")
            if not path.exists() and not rejected.exists():
                raise RuntimeError(f"Study incomplete, missing {s} from shard {i}")
            if rejected.exists():
                marker = load(rejected)
                if marker.get("plan_sha256") != plan["plan_sha256"]:
                    raise RuntimeError("Mismatched rejection marker")
                rejects[marker["status"]] += 1
                digests[s] = hashlib.sha256(rejected.read_bytes()).hexdigest()
            else:
                f = _read_feature(path, s)
                if f.empty:
                    raise RuntimeError("Empty accepted as-of record " + s)
                # Source timeframe must never exceed frozen historical cutoffs.
                if (f["bar_open_utc"].min() < _utc(plan["first_bar_open_utc"]) or
                    f["bar_open_utc"].max() > _utc(plan["last_closed_bar_open_utc"])):
                    raise RuntimeError("Out-of-study time in stored features")
                dataframes.append(f)
                digests[s] = hashlib.sha256(path.read_bytes()).hexdigest()
    if seen != all_expected:
        raise RuntimeError("Universe coverage mismatch")
    if not dataframes:
        raise RuntimeError("No usable feature history")
    joined = pd.concat(dataframes, ignore_index=True)
    if joined.duplicated(["symbol", "bar_open_utc"]).any():
        raise RuntimeError("Duplicate same-symbol timestamp in merged archive")
    unique_times = joined["bar_open_utc"].nunique()
    total_count = 0
    event_counts = Counter()
    matched = 0
    overlaps = 0
    out = study_root / "merged"
    out.mkdir(parents=True, exist_ok=True)
    event_path = out / "market_events.jsonl.gz"
    report_path = out / "research_manifest.json"
    if event_path.exists() or report_path.exists():
        raise RuntimeError("Merged registry already exists: immutable; do not overwrite")
    # Full-market matching at SAME as-of time, never future prices or event outcomes.
    with gzip.open(event_path, "wt", encoding="utf-8") as handle:
        for timestamp, frame in joined.groupby("bar_open_utc", sort=True):
            market = frame.loc[frame["quality_ready"] == 1]
            if market.empty:
                continue
            qualifying = market.loc[market[list(EVENTS)].sum(axis=1) > 0]
            if qualifying.empty:
                continue
            sym = market["symbol"].to_numpy(str)
            vol = market["volatility_24h_pct"].to_numpy(float)
            turnover = market["turnover_24h_usdt"].to_numpy(float)
            for _, row in qualifying.iterrows():
                flags = [key for key in EVENTS if row[key] == 1]
                if len(flags) > 1:
                    overlaps += 1
                for key in flags:
                    mask = (market[key].to_numpy(int) == 0) & (sym != row["symbol"])
                    mask &= np.isfinite(vol) & (np.abs(vol - float(row["volatility_24h_pct"])) <= 15)
                    q = float(row["turnover_24h_usdt"])
                    mask &= np.isfinite(turnover) & (turnover > 0)
                    if q > 0:
                        mask &= (turnover >= q / 10) & (turnover <= q * 10)
                    else:
                        mask[:] = False
                    ids = np.flatnonzero(mask)
                    ranked = sorted(
                        ((float(abs(vol[j] - row["volatility_24h_pct"]) +
                                2 * abs(math.log(turnover[j] / q))), str(sym[j])) for j in ids),
                        key=lambda t: (t[0], t[1]),
                    )
                    controls = [s for _, s in ranked[:3]]
                    result = {
                        "event_id": key, "event_name": EVENTS[key],
                        "symbol": row["symbol"],
                        "observed_at_utc": (timestamp + STEP).isoformat(),
                        "last_closed_bar_open_utc": timestamp.isoformat(),
                        "asof_close": float(row["close"]),
                        "return_1h_pct": float(row["return_1h_pct"]),
                        "return_4h_pct": float(row["return_4h_pct"]),
                        "volatility_24h_pct": float(row["volatility_24h_pct"]),
                        "turnover_24h_usdt": float(row["turnover_24h_usdt"]),
                        "control_symbols": controls, "control_count": len(controls),
                        "control_scope": "FROZEN_WHOLE_STUDY_UNIVERSE_SAME_UTC",
                        "research_only": True, "outcome_labels_present": False,
                    }
                    handle.write(json.dumps(result, ensure_ascii=False) + "\n")
                    total_count += 1
                    event_counts[key] += 1
                    matched += bool(controls)
    report = {
        "version": "M5_V0.2_HISTORICAL_RESEARCH",
        "status": "PILOT_SUBSET_COMPLETE_NOT_FULL_MARKET" if plan["pilot"] else "FULL_FROZEN_COHORT_MERGED",
        "plan_sha256": plan["plan_sha256"],
        "study_id": study_id, "pilot": plan["pilot"],
        "catalogue_count": plan["catalogue_count"],
        "frozen_symbol_count": plan["symbol_count"],
        "accepted_symbols": len(dataframes),
        "excluded_symbols": sum(rejects.values()),
        "excluded_reasons": dict(rejects),
        "asof_rows": len(joined),
        "distinct_bar_times": unique_times,
        "event_counts": {key: event_counts[key] for key in EVENTS},
        "total_event_family_occurrences": total_count,
        "event_observations_with_control": matched,
        "overlapping_coin_time_observations": overlaps,
        "all_symbol_file_hash_sha256": digest(digests),
        "archive_caveats": [
            "Study universe is based on currently listed MEXC contracts; delisted coins missing",
            "Matched control cohort excludes rejected instruments",
            "Substantial across-coin and within-coin dependence",
            "Control comparability uses as-of turnover and volatility, not proof of exchangeability",
            "Historical exploration and chronological holdout are NOT prospective forward data",
            "Raw OHLCV are not kept permanently; only compressed as-of features are Git-versioned",
        ],
        "no_outcome_study": True, "no_profit_claim": True, "no_order": True,
        "data_policy": "IMMUTABLE_GIT_STUDY_FEATURES_AND_EVENT_REGISTRY",
    }
    dump(report_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report

def main():
    parser = argparse.ArgumentParser("M5 V0.2 bounded full-market historical registration")
    sub = parser.add_subparsers(dest="mode", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--shards", type=int, default=16)
    p.add_argument("--study-id", default=None)
    p.add_argument("--pilot-limit", type=int, default=0)
    p.add_argument("--root", type=Path, default=ROOT)
    s = sub.add_parser("shard")
    s.add_argument("--study-id", required=True)
    s.add_argument("--shard-index", type=int, required=True)
    s.add_argument("--max-new", type=int, default=6)
    s.add_argument("--root", type=Path, default=ROOT)
    st = sub.add_parser("status")
    st.add_argument("--study-id", required=True)
    st.add_argument("--shard-index", type=int, required=True)
    st.add_argument("--root", type=Path, default=ROOT)
    m = sub.add_parser("merge")
    m.add_argument("--study-id", required=True)
    m.add_argument("--allow-pilot", action="store_true")
    m.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    if args.mode == "plan":
        symbols, audit = record_catalogue()
        result = create_plan(symbols, audit, days=args.days, shards=args.shards,
                             study_id=args.study_id, root=args.root,
                             pilot=bool(args.pilot_limit), symbols_limit=args.pilot_limit)
        print(json.dumps({k: v for k, v in result.items() if k != "symbols"}, indent=2))
        return 0
    if args.mode == "shard":
        r = collect_chunk(args.study_id, args.shard_index, args.max_new, args.root)
        return 0 if r["attempted_new"] == 0 or not r["transient_failures"] else 2
    if args.mode == "status":
        r = shard_status(args.study_id, args.shard_index, args.root)
        print(json.dumps(r, indent=2))
        return 0 if r["complete"] else 3
    if args.mode == "merge":
        merge_study(args.study_id, args.root, allow_pilot=args.allow_pilot)
        return 0
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
