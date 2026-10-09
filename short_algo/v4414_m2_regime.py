"""Decompose the completed V4.4.14 360D final artifact by time regime."""
import json
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd


def _num(v):
    try:
        x = float(v)
        return x if np.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _pf(vals):
    vals = [x for x in (_num(v) for v in vals) if x is not None]
    gain = sum(x for x in vals if x > 0)
    loss = -sum(x for x in vals if x < 0)
    if loss <= 0:
        return 999.0 if gain > 0 else None
    return round(gain / loss, 4)


def _pct(n, d):
    return round(100.0 * n / d, 2) if d else None


def _metrics(rows):
    fills = [r for r in rows if _num(r.get("v4414_m2_exec_net_r")) is not None]
    net = [float(r["v4414_m2_exec_net_r"]) for r in fills]
    return {
        "fills": len(fills),
        "positive": sum(x > 0 for x in net),
        "positive_pct": _pct(sum(x > 0 for x in net), len(net)),
        "net_expectancy_r": round(float(np.mean(net)), 5) if net else None,
        "profit_factor": _pf(net),
        "total_net_r": round(float(sum(net)), 5),
        "tp1_hit_pct": _pct(
            sum(int(r.get("v4414_m2_exec_tp1_hit") or 0) for r in fills),
            len(fills),
        ),
        "tp2_hit_pct": _pct(
            sum(int(r.get("v4414_m2_exec_tp2_hit") or 0) for r in fills),
            len(fills),
        ),
    }


def _entry_rows(report):
    rows = []
    for r in report.get("trades") or []:
        if r.get("v4414_m2_entry_time") is None:
            continue
        if _num(r.get("v4414_m2_exec_net_r")) is None:
            continue
        x = dict(r)
        x["_entry_ts"] = pd.Timestamp(r["v4414_m2_entry_time"])
        rows.append(x)
    rows.sort(key=lambda r: r["_entry_ts"])
    return rows


def _fixed_blocks(rows, start, days, block_days):
    out = []
    block = pd.Timedelta(days=block_days)
    end = start + pd.Timedelta(days=days)
    i = 0
    cur = start
    while cur < end:
        nxt = min(cur + block, end)
        sub = [r for r in rows if cur <= r["_entry_ts"] < nxt]
        out.append({
            "index": i + 1,
            "start": cur.isoformat(),
            "end": nxt.isoformat(),
            **_metrics(sub),
        })
        i += 1
        cur = nxt
    return out


def _monthly(rows):
    groups = defaultdict(list)
    for r in rows:
        key = r["_entry_ts"].strftime("%Y-%m")
        groups[key].append(r)
    return [
        {"month": key, **_metrics(groups[key])}
        for key in sorted(groups)
    ]


def _quarterly(rows):
    groups = defaultdict(list)
    for r in rows:
        ts = r["_entry_ts"]
        q = (ts.month - 1) // 3 + 1
        key = f"{ts.year}-Q{q}"
        groups[key].append(r)
    return [
        {"quarter": key, **_metrics(groups[key])}
        for key in sorted(groups)
    ]


def _stability(blocks):
    valid = [b for b in blocks if b["fills"] > 0]
    pos_exp = [b for b in valid if (b["net_expectancy_r"] or 0) > 0]
    pf1 = [b for b in valid if b["profit_factor"] is not None and b["profit_factor"] > 1]
    return {
        "periods": len(valid),
        "positive_expectancy_periods": len(pos_exp),
        "positive_expectancy_pct": _pct(len(pos_exp), len(valid)),
        "pf_gt_1_periods": len(pf1),
        "pf_gt_1_pct": _pct(len(pf1), len(valid)),
        "worst_expectancy_r": min(
            (b["net_expectancy_r"] for b in valid if b["net_expectancy_r"] is not None),
            default=None,
        ),
        "best_expectancy_r": max(
            (b["net_expectancy_r"] for b in valid if b["net_expectancy_r"] is not None),
            default=None,
        ),
        "worst_pf": min(
            (b["profit_factor"] for b in valid if b["profit_factor"] is not None),
            default=None,
        ),
        "best_pf": max(
            (b["profit_factor"] for b in valid if b["profit_factor"] is not None),
            default=None,
        ),
    }


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "artifact/v4414_m2_backtest.json"
    outdir = sys.argv[2] if len(sys.argv) > 2 else "output"
    with open(src, "r", encoding="utf-8") as f:
        report = json.load(f)

    rows = _entry_rows(report)
    start = pd.Timestamp(report["period_start"])
    if start.tzinfo is None:
        start = start.tz_localize("UTC")
    days = int(report.get("days") or 360)

    blocks60 = _fixed_blocks(rows, start, days, 60)
    blocks90 = _fixed_blocks(rows, start, days, 90)
    months = _monthly(rows)
    quarters = _quarterly(rows)

    analysis = {
        "overall": _metrics(rows),
        "blocks_60d": blocks60,
        "blocks_90d": blocks90,
        "quarters": quarters,
        "months": months,
        "stability_60d": _stability(blocks60),
        "stability_90d": _stability(blocks90),
        "period_start": report.get("period_start"),
        "period_end": report.get("period_end"),
        "days": days,
        "rule": (report.get("analysis") or {}).get("rule"),
    }

    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "v4414_m2_360d_regime.json"), "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)

    lines = [
        "# V4.4.14 M2 — 360D Regime Decomposition",
        "",
        f"Overall: {analysis['overall']}",
        "",
        "## 60-day blocks",
    ]
    lines += [f"- {x}" for x in blocks60]
    lines += ["", "## 90-day blocks"]
    lines += [f"- {x}" for x in blocks90]
    lines += ["", "## Quarters"]
    lines += [f"- {x}" for x in quarters]
    lines += ["", "## Months"]
    lines += [f"- {x}" for x in months]
    lines += ["", f"60D stability: {analysis['stability_60d']}"]
    lines += [f"90D stability: {analysis['stability_90d']}"]

    summary = "\n".join(lines)
    with open(os.path.join(outdir, "v4414_m2_360d_regime.md"), "w", encoding="utf-8") as f:
        f.write(summary)

    print(json.dumps(analysis, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
