"""Merge M3 V3.2 shards and compare entry-timing cohorts."""
import json
import os
import sys
from collections import Counter
from glob import glob

import numpy as np

from .config import OUTPUT_DIR


def _num(x):
    try:
        y = float(x)
        return y if np.isfinite(y) else None
    except (TypeError, ValueError):
        return None


def _pct(n, d):
    return round(100.0 * n / d, 2) if d else None


def _q(vals, q=0.5):
    arr = [_num(x) for x in vals]
    arr = [x for x in arr if x is not None]
    return round(float(np.quantile(arr, q)), 5) if arr else None


def _metrics(rows, days):
    n = len(rows)
    hits = [r for r in rows if int(r.get("m3v32_hit_3pct_24h") or 0)]
    return {
        "entries": n,
        "entries_per_day": round(n / max(float(days), 1.0), 3),
        "hit_3pct_24h_pct": _pct(len(hits), n),
        "clean3_before_0_5_pct": _pct(sum(int(r.get("m3v32_clean3_adverse_0_5") or 0) for r in rows), n),
        "clean3_before_0_75_pct": _pct(sum(int(r.get("m3v32_clean3_adverse_0_75") or 0) for r in rows), n),
        "clean3_before_1_0_pct": _pct(sum(int(r.get("m3v32_clean3_adverse_1_0") or 0) for r in rows), n),
        "median_pre3pct_mae_pct": _q([r.get("m3v32_pre3pct_mae_pct") for r in rows]),
        "p75_pre3pct_mae_pct": _q([r.get("m3v32_pre3pct_mae_pct") for r in rows], 0.75),
        "median_minutes_to_3pct_hits": _q([r.get("m3v32_minutes_to_3pct") for r in hits]),
        "median_trigger_wait_bars": _q([r.get("m3v32_trigger_wait_bars") for r in rows]),
        "median_trigger_chase_atr15": _q([r.get("m3v32_trigger_chase_atr15") for r in rows]),
        "market_states": dict(sorted(Counter(str(r.get("m3v32_market_state") or "UNKNOWN") for r in rows).items())),
    }


def main(root="m3v32_shards"):
    reports = []
    for path in sorted(glob(os.path.join(root, "**", "m3_v32_backtest.json"), recursive=True)):
        with open(path, encoding="utf-8") as f:
            reports.append(json.load(f))
    if not reports:
        raise RuntimeError("No M3 V3.2 reports")

    expected = max(int(r["shard_count"]) for r in reports)
    found = {int(r["shard_index"]) for r in reports}
    if found != set(range(expected)):
        raise RuntimeError(f"Incomplete shards {sorted(found)}")

    manifest_ids = {r["manifest_id"] for r in reports}
    if len(manifest_ids) != 1:
        raise RuntimeError("Manifest mismatch")

    rows, errors, symbols = [], [], []
    for report in reports:
        rows += report.get("rows", [])
        errors += report.get("errors", [])
        symbols += report.get("selected_symbols", [])

    dedup = {}
    for row in rows:
        key = (row.get("symbol"), row.get("signal_time"))
        dedup.setdefault(key, row)
    rows = list(dedup.values())
    days = int(reports[0]["days"])

    core_all = rows
    triggered = [r for r in rows if r.get("m3v32_trigger_state") == "TRIGGER_ENTRY"]
    tight_triggered = [r for r in triggered if int(r.get("m3v32_tight_gate_pass") or 0)]
    neutral_triggered = [r for r in triggered if r.get("m3v32_market_state") == "NEUTRAL"]
    riskoff_triggered = [r for r in triggered if r.get("m3v32_market_state") == "RISK_OFF"]
    riskon_triggered = [r for r in triggered if r.get("m3v32_market_state") == "RISK_ON_STRONG"]

    analysis = {
        "core_candidates_before_trigger": {
            "candidates": len(core_all),
            "candidates_per_day": round(len(core_all) / max(float(days), 1.0), 3),
            "trigger_fill_pct": _pct(len(triggered), len(core_all)),
        },
        "v32_triggered": _metrics(triggered, days),
        "v32_tight_triggered": _metrics(tight_triggered, days),
        "v32_triggered_neutral": _metrics(neutral_triggered, days),
        "v32_triggered_riskoff": _metrics(riskoff_triggered, days),
        "v32_triggered_riskon_strong": _metrics(riskon_triggered, days),
    }

    out = {
        "engine": "M3 V3.2 Post-Retest Trigger Refinement",
        "manifest_id": next(iter(manifest_ids)),
        "days": days,
        "symbols": len(set(symbols)),
        "errors": errors,
        "analysis": analysis,
        "rows": rows,
        "research_status": "SAME_PERIOD_DEVELOPMENT_NOT_INDEPENDENT_OOS",
        "note": "V3.2 freezes V2.1 core setup gates and tests only post-retest entry timing.",
    }

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, "m3_v32_analysis.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    with open(os.path.join(OUTPUT_DIR, "m3_v32_summary.md"), "w", encoding="utf-8") as f:
        f.write("# M3 V3.2 — Post-Retest Trigger Refinement\n\n")
        f.write("Goal: retain M3 frequency while improving entry quality / adverse excursion.\n\n")
        for key, value in analysis.items():
            f.write(f"## {key}\n{value}\n\n")
        f.write("Same-period development study; no live-rule promotion without validation.\n")

    print(json.dumps(analysis, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "m3v32_shards"))
