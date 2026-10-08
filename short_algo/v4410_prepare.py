"""Freeze a 60d V4.4.10 signal cohort with a 15d future buffer."""
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

from .config import BACKTEST_SYMBOL_LIMIT, OUTPUT_DIR
from .mexc import get_all_tickers, get_contract_universe
from .v4410_m2_config import V4410_DAYS, V4410_FUTURE_BUFFER_DAYS


def build_manifest(days=None, symbol_limit=None):
    days = int(days or V4410_DAYS)
    symbol_limit = int(
        BACKTEST_SYMBOL_LIMIT if symbol_limit is None else symbol_limit
    )

    period_end = datetime.now(timezone.utc).replace(
        minute=0, second=0, microsecond=0
    ) - timedelta(days=int(V4410_FUTURE_BUFFER_DAYS))
    period_start = period_end - timedelta(days=days)
    future_end = period_end + timedelta(days=int(V4410_FUTURE_BUFFER_DAYS))

    universe, audit = get_contract_universe(return_audit=True)
    tickers = get_all_tickers()
    ranked = sorted(
        [s for s in universe if s in tickers],
        key=lambda s: -float((tickers.get(s) or {}).get("turnover_24h") or 0.0),
    )
    if symbol_limit > 0:
        ranked = ranked[:symbol_limit]

    identity = {
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "future_end": future_end.isoformat(),
        "days": days,
        "symbols": ranked,
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]

    return {
        "manifest_version": 4410,
        "manifest_id": f"v4410-{digest}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "future_end": future_end.isoformat(),
        "days": days,
        "future_buffer_days": int(V4410_FUTURE_BUFFER_DAYS),
        "symbol_limit": symbol_limit,
        "symbols": ranked,
        "symbol_count": len(ranked),
        "selection": "frozen_current_turnover_rank_crypto_only",
        "universe_audit": audit,
        "bias_note": (
            "Current tradability and turnover rank define the frozen cohort. "
            "The signal window is lagged by 15 days so each M2 event can use "
            "up to 7d support-flip watch, 12h entry confirmation and 7d "
            "post-entry path observation without end-of-sample censoring."
        ),
    }


def main():
    manifest = build_manifest()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, "v4410_manifest.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
    print(json.dumps({
        "manifest_id": manifest["manifest_id"],
        "period_start": manifest["period_start"],
        "period_end": manifest["period_end"],
        "future_end": manifest["future_end"],
        "days": manifest["days"],
        "future_buffer_days": manifest["future_buffer_days"],
        "symbols": manifest["symbol_count"],
    }, ensure_ascii=False, indent=2))
    return 0 if manifest["symbol_count"] > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
