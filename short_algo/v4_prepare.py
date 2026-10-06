"""Freeze the V4 historical cohort before parallel replay."""

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

from .config import BACKTEST_DAYS, BACKTEST_SYMBOL_LIMIT, OUTPUT_DIR
from .mexc import get_all_tickers, get_contract_universe


def build_manifest(days=None, symbol_limit=None):
    days = int(days or BACKTEST_DAYS)
    symbol_limit = int(
        BACKTEST_SYMBOL_LIMIT if symbol_limit is None else symbol_limit
    )

    period_end = datetime.now(timezone.utc).replace(
        minute=0, second=0, microsecond=0
    ) - timedelta(hours=2)
    period_start = period_end - timedelta(days=days)

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
        "days": days,
        "symbols": ranked,
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]

    return {
        "manifest_version": 1,
        "manifest_id": f"v4-{digest}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "days": days,
        "symbol_limit": symbol_limit,
        "symbols": ranked,
        "symbol_count": len(ranked),
        "selection": "frozen_current_turnover_rank_crypto_only",
        "universe_audit": audit,
        "bias_note": (
            "Current tradability and turnover rank define the frozen cohort once "
            "before sharding. All V4 shards and reruns consume this exact manifest."
        ),
    }


def main():
    manifest = build_manifest()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, "v4_manifest.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
    print(json.dumps({
        "manifest_id": manifest["manifest_id"],
        "period_start": manifest["period_start"],
        "period_end": manifest["period_end"],
        "days": manifest["days"],
        "symbols": manifest["symbol_count"],
    }, ensure_ascii=False, indent=2))
    return 0 if manifest["symbol_count"] > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
