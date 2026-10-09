"""V4.4.15 M2 — pre-entry regime study on completed V4.4.14 360D artifact.

Research-only diagnostic. Uses only signal-time-safe fields already frozen in the
V4.4.14 artifact and the same exact-event + 96h symbol cooldown dedupe.
No new trading rule is promoted here.
"""
import json
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

COOLDOWN_HOURS = 96

NUMERIC_FEATURES = [
    "market_r4_pct",
    "market_r24_pct",
    "relative_4h_pct",
    "relative_24h_pct",
    "atr_pct_1h",
    "volume_ratio_1h",
    "candidate_context_points",
    "ema20_distance_atr",
    "range_position_24h",
    "continuation_quality",
    "anti_bottom_total",
    "squeeze_risk",
]

CATEGORICAL_FEATURES = [
    "market_risk_on",
    "market_risk_off",
    "market_bull",
    "market_bear",
    "s1_ema_bear",
    "s1_lower_high",
    "s1_lower_low",
    "s4_ema_bear",
    "s4_lower_high",
    "s4_lower_low",
    "s4_macro_bear",
    "continuation_ready",
]

# Predeclared causal hypotheses; these are diagnostics, not promoted rules.
HYPOTHESES = {
    "MARKET_R24_NEG": lambda r: _num(r.get("market_r24_pct")) is not None and float(r["market_r24_pct"]) < 0,
    "MARKET_R4_NEG": lambda r: _num(r.get("market_r4_pct")) is not None and float(r["market_r4_pct"]) < 0,
    "MARKET_BEAR": lambda r: int(r.get("market_bear") or 0) == 1,
    "RISK_OFF": lambda r: int(r.get("market_risk_off") or 0) == 1,
    "COIN_REL24_NEG": lambda r: _num(r.get("relative_24h_pct")) is not None and float(r["relative_24h_pct"]) < 0,
    "COIN_REL4_NEG": lambda r: _num(r.get("relative_4h_pct")) is not None and float(r["relative_4h_pct"]) < 0,
    "S4_MACRO_BEAR": lambda r: int(r.get("s4_macro_bear") or 0) == 1,
    "S4_EMA_BEAR": lambda r: int(r.get("s4_ema_bear") or 0) == 1,
    "MARKET_BEAR_AND_REL24_NEG": lambda r: (
        int(r.get("market_bear") or 0) == 1
        and _num(r.get("relative_24h_pct")) is not None
        and float(r["relative_24h_pct"]) < 0
    ),
    "RISK_OFF_AND_S4_MACRO_BEAR": lambda r: (
        int(r.get("market_risk_off") or 0) == 1
        and int(r.get("s4_macro_bear") or 0) == 1
    ),
}


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
        "tp1_hit_pct": _pct(sum(int(r.get("v4414_m2_exec_tp1_hit") or 0) for r in fills), len(fills)),
        "tp2_hit_pct": _pct(sum(int(r.get("v4414_m2_exec_tp2_hit") or 0) for r in fills), len(fills)),
    }


def _exact_events(rows):
    d = {}
    for r in sorted(rows, key=lambda x: (str(x.get("signal_time")), str(x.get("symbol")))):
        bt = r.get("v4414_m2_break_time")
        if not bt:
            continue
        key = (str(r.get("symbol")), str(bt), str(r.get("v4414_m2_support_level")))
        d.setdefault(key, r)
    return list(d.values())


def _unique96h(events):
    last = {}
    out = []
    for r in sorted(events, key=lambda x: (str(x.get("v4414_m2_break_time")), str(x.get("symbol")))):
        s = str(r.get("symbol"))
        t = pd.Timestamp(r.get("v4414_m2_break_time"))
        p = last.get(s)
        if p is not None and (t - p) < pd.Timedelta(hours=COOLDOWN_HOURS):
            continue
        last[s] = t
        out.append(r)
    return out


def _entries(report):
    rows = []
    for r in _unique96h(_exact_events(report.get("trades") or [])):
        if r.get("v4414_m2_entry_time") is None:
            continue
        if _num(r.get("v4414_m2_exec_net_r")) is None:
            continue
        rows.append(r)
    return rows


def _dist(rows, key):
    vals = [x for x in (_num(r.get(key)) for r in rows) if x is not None]
    if not vals:
        return {"n": 0}
    a = np.asarray(vals, dtype=float)
    return {
        "n": len(vals),
        "mean": round(float(a.mean()), 5),
        "median": round(float(np.median(a)), 5),
        "p25": round(float(np.percentile(a, 25)), 5),
        "p75": round(float(np.percentile(a, 75)), 5),
    }


def _numeric_quartiles(rows, key):
    vals = [(_num(r.get(key)), r) for r in rows]
    vals = [(v, r) for v, r in vals if v is not None]
    if len(vals) < 20:
        return {}
    arr = np.asarray([v for v, _ in vals], dtype=float)
    q1, q2, q3 = [float(x) for x in np.percentile(arr, [25, 50, 75])]
    buckets = {
        "Q1_LOW": [],
        "Q2": [],
        "Q3": [],
        "Q4_HIGH": [],
    }
    for v, r in vals:
        if v <= q1:
            buckets["Q1_LOW"].append(r)
        elif v <= q2:
            buckets["Q2"].append(r)
        elif v <= q3:
            buckets["Q3"].append(r)
        else:
            buckets["Q4_HIGH"].append(r)
    return {
        "cuts": {"q25": round(q1, 5), "q50": round(q2, 5), "q75": round(q3, 5)},
        "buckets": {k: _metrics(v) for k, v in buckets.items()},
    }


def _categorical(rows, key):
    groups = defaultdict(list)
    for r in rows:
        groups[str(r.get(key))].append(r)
    return {k: _metrics(v) for k, v in sorted(groups.items())}


def _hypotheses(rows):
    out = {}
    for name, fn in HYPOTHESES.items():
        yes = [r for r in rows if fn(r)]
        no = [r for r in rows if not fn(r)]
        out[name] = {
            "yes": _metrics(yes),
            "no": _metrics(no),
            "coverage_pct": _pct(len(yes), len(rows)),
        }
    return out


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "artifact/v4414_m2_backtest.json"
    outdir = sys.argv[2] if len(sys.argv) > 2 else "output"
    with open(src, "r", encoding="utf-8") as f:
        report = json.load(f)

    rows = _entries(report)
    expected = ((report.get("analysis") or {}).get("counts") or {}).get("unique_entries")
    if expected is not None and int(expected) != len(rows):
        raise RuntimeError(f"Unique-entry mismatch: study={len(rows)} merge={expected}")

    winners = [r for r in rows if float(r["v4414_m2_exec_net_r"]) > 0]
    losers = [r for r in rows if float(r["v4414_m2_exec_net_r"]) <= 0]

    numeric = {}
    for key in NUMERIC_FEATURES:
        numeric[key] = {
            "all": _dist(rows, key),
            "winners": _dist(winners, key),
            "losers": _dist(losers, key),
            "quartiles": _numeric_quartiles(rows, key),
        }

    categorical = {key: _categorical(rows, key) for key in CATEGORICAL_FEATURES}
    hypotheses = _hypotheses(rows)

    analysis = {
        "status": "RESEARCH_ONLY",
        "source": "V4.4.14 360D final artifact",
        "dedupe": "exact break event + 96h symbol cooldown",
        "lookahead_safe_features_only": True,
        "new_rule_promoted": False,
        "counts": {
            "unique_entries": len(rows),
            "winners": len(winners),
            "losers": len(losers),
        },
        "baseline": _metrics(rows),
        "numeric_features": numeric,
        "categorical_features": categorical,
        "predeclared_hypotheses": hypotheses,
    }

    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "v4415_m2_regime_study.json"), "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)

    lines = [
        "# V4.4.15 M2 — Regime Study",
        "",
        f"Baseline: {analysis['baseline']}",
        f"Counts: {analysis['counts']}",
        "",
        "## Predeclared hypotheses",
    ]
    lines += [f"- {k}: {v}" for k, v in hypotheses.items()]
    lines += ["", "## Numeric features"]
    lines += [f"- {k}: {v}" for k, v in numeric.items()]
    lines += ["", "## Categorical features"]
    lines += [f"- {k}: {v}" for k, v in categorical.items()]
    lines += ["", "- RESEARCH_ONLY. No filter promoted in V4.4.15."]

    with open(os.path.join(outdir, "v4415_m2_regime_study.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(json.dumps(analysis, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
