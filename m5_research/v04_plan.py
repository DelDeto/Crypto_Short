"""M5 V0.4 exploratory OHLC path STUDY PLAN. No orders.

Selection uses ONLY previously frozen as-of 14-day event registry; never
uses next-bar prices/returns to decide which events get simulated.
2026-10-13 cohort was previously explored, so no claim of OOS confirmation.
"""
import argparse
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path

import pandas as pd

from .config import EVENTS
from .data import STEP, _utc
from .v02 import ROOT, checked_id, digest, dump, load, validate_plan

STUDY_ID = "m5-full-20261013-14d"
EXECUTION_ID = "m5-v04-20261013-14d"
SELECTION_SALT = "M5_V04_EXECUTION_PATH_EXPLORATORY_FIXED_V1"
EVENTS_PER_FAMILY = 6
MAX_CONTROLS_PER_CASE = 2
MAX_HOURS = 8
OUTPUT_ROOT = Path("state/m5_research/execution")
VERSION = "M5_V04_FROZEN_EXPLORATORY_EXECUTION_PLAN_V1"

def _archive_paths(study_id=STUDY_ID, root=ROOT):
    base = Path(root) / checked_id(study_id)
    plan = load(base / "plan.json")
    validate_plan(plan)
    merged = load(base / "merged" / "research_manifest.json")
    discovery = load(base / "discovery" / "v031_daily_stability.json")
    if (plan.get("pilot") or plan.get("historical_days", 0) != 14 or
        merged.get("status") != "FULL_FROZEN_COHORT_MERGED" or
        plan["plan_sha256"] != merged.get("plan_sha256") or
        discovery.get("study_plan_sha256") != plan["plan_sha256"] or
        discovery.get("status") != "EXPANDED_DISCOVERY_ONLY_UNCONFIRMED"):
        raise RuntimeError("M5 immutable 14d study integrity gate failed")
    source = base / "merged" / "market_events.jsonl.gz"
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    if discovery.get("source_merged_event_sha256") != source_sha:
        raise RuntimeError("As-of merged registry changed since V0.3.1 filing")
    return plan, discovery, source, source_sha

def make_plan(study_id=STUDY_ID, root=ROOT, output_root=OUTPUT_ROOT):
    plan, discovery, source, source_sha = _archive_paths(study_id, root)
    boundary = _utc(plan["holdout_reserved_start_utc"])
    discovery_start = _utc(plan["first_bar_open_utc"])
    # Exactly six distinct UTC days per family where possible. For each day,
    # choose the lowest independent fixed hash; then sort those candidates by
    # the same fixed hash to choose six days. NOT scored on future performance.
    by_day = {key: {} for key in EVENTS}
    eligible = {key: 0 for key in EVENTS}
    with gzip.open(source, "rt", encoding="utf-8") as stream:
        for line in stream:
            event = json.loads(line)
            t = _utc(event["last_closed_bar_open_utc"])
            if t >= boundary:
                break  # event stream chronologically sorted: never inspect holdout
            if t < discovery_start or t + STEP + pd.Timedelta(hours=MAX_HOURS) >= boundary:
                continue
            eid = event["event_id"]
            if eid not in EVENTS:
                raise RuntimeError("Unexpected event family")
            controls = list(dict.fromkeys(event.get("control_symbols") or []))
            controls = [s for s in controls if s != event["symbol"]][:MAX_CONTROLS_PER_CASE]
            if not controls:
                continue
            eligible[eid] += 1
            day = t.strftime("%Y-%m-%d")
            key = f"{SELECTION_SALT}|{eid}|{event['symbol']}|{t.isoformat()}"
            priority = hashlib.sha256(key.encode()).hexdigest()
            # Only as-of properties retained; no future returns or OHLC.
            candidate = {
                "event_id": eid, "symbol": event["symbol"],
                "bar_open_utc": t.isoformat(),
                "observed_at_utc": (t + STEP).isoformat(),
                "asof_close": float(event["asof_close"]),
                "controls": controls,
                "event_day_utc": day,
                "selection_hash": priority,
            }
            if day not in by_day[eid] or priority < by_day[eid][day]["selection_hash"]:
                by_day[eid][day] = candidate
    chosen = []
    per_event = {}
    for eid in EVENTS:
        picks = sorted(by_day[eid].values(), key=lambda e: e["selection_hash"])[:EVENTS_PER_FAMILY]
        if not picks:
            raise RuntimeError(f"No eligible discovery events for {eid}")
        per_event[eid] = len(picks)
        chosen.extend(picks)
    chosen.sort(key=lambda e: (e["event_id"], e["selection_hash"]))
    instruments = sorted({symbol for e in chosen for symbol in [e["symbol"], *e["controls"]]})
    if len(chosen) > 8 * EVENTS_PER_FAMILY or len(instruments) > 8 * EVENTS_PER_FAMILY * 3:
        raise RuntimeError("M5 V0.4 research API budget exceeded")
    obj = {
        "version": VERSION, "execution_id": EXECUTION_ID,
        "source_study_id": study_id,
        "source_plan_sha256": plan["plan_sha256"],
        "source_merged_event_sha256": source_sha,
        "holdout_exclusive_utc": boundary.isoformat(),
        "historical_study_first_utc": discovery_start.isoformat(),
        "selection_rule": SELECTION_SALT,
        "event_sample": "deterministic_hash_one_event_per_day_per_family",
        "max_events_per_family": EVENTS_PER_FAMILY,
        "max_controls_per_event": MAX_CONTROLS_PER_CASE,
        "families": list(EVENTS),
        "eligible_discovery_event_counts": eligible,
        "selected_family_counts": per_event,
        "events": chosen,
        "symbols": instruments,
        "symbol_count": len(instruments),
        "ohlc_fetch_policy": "DISCRETE_CLOSED_15M_CANDLES_THROUGH_DISCOVERY_ONLY",
        "entry_proxy": "NEXT_15M_BAR_OPEN_NO_LATENCY_FILLS_NOT_VERIFIED",
        "horizon_hours": [1, 2, 4, 8],
        "fixed_sl_tp_configs_pct": [
            {"sl": 1.0, "tp": 2.0},
            {"sl": 1.5, "tp": 3.0},
            {"sl": 2.0, "tp": 4.0},
        ],
        "round_trip_cost_stress_bps": [20, 40],
        "same_bar_sl_tp_resolution": "SL_FIRST_CONSERVATIVE",
        "research_only": True,
        "historical_exploration_NOT_independent_OOS": True,
        "trades_not_executed": True,
        "funding_spread_market_impact_unmeasured": True,
    }
    obj["plan_sha256"] = digest(obj)
    dest = Path(output_root) / EXECUTION_ID / "plan.json"
    if dest.exists():
        if load(dest) != obj:
            raise RuntimeError("Execution plan already sealed: cannot overwrite")
    else:
        dump(dest, obj)
    return obj

def read_plan(output_root=OUTPUT_ROOT, root=ROOT):
    dst = Path(output_root) / EXECUTION_ID / "plan.json"
    obj = load(dst)
    h = obj.get("plan_sha256")
    if obj.get("version") != VERSION or digest({k: v for k,v in obj.items() if k != "plan_sha256"}) != h:
        raise RuntimeError("M5 V0.4 plan fingerprint mismatch")
    parent, _, _, source_sha = _archive_paths(obj["source_study_id"], root)
    if (obj["source_plan_sha256"] != parent["plan_sha256"] or
        obj["source_merged_event_sha256"] != source_sha):
        raise RuntimeError("Underlying frozen historical cohort changed")
    if obj["historical_exploration_NOT_independent_OOS"] is not True:
        raise RuntimeError("Risk of false OOS assertion")
    return obj

def main():
    p = argparse.ArgumentParser("M5 V0.4 as-of frozen deterministic sample plan")
    p.add_argument("--source-study", default=STUDY_ID)
    args = p.parse_args()
    out = make_plan(args.source_study)
    print(json.dumps({k: v for k,v in out.items() if k not in ("events", "symbols")}, indent=2))
    print(f"Selected {len(out['events'])} events across {out['symbol_count']} OHLC symbol histories")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
