import json
import sys

from .live_outcomes import load_ledger, register_signals, save_ledger, update_outcomes
from .m3_outcomes import (
    load_ledger as load_m3_ledger,
    register_signals as register_m3_signals,
    save_ledger as save_m3_ledger,
    update_outcomes as update_m3_outcomes,
)
from .notifier import send_telegram
from .scanner import run_scan, save_report


def main():
    report = run_scan()

    ledger = load_ledger()
    outcome_errors = update_outcomes(ledger)
    added = register_signals(ledger, report.get("m2_live_signals") or [])
    outcome_summary = save_ledger(ledger)

    m3_ledger = load_m3_ledger()
    m3_outcome_errors = update_m3_outcomes(m3_ledger)
    m3_added = register_m3_signals(m3_ledger, report.get("m3_live_signals") or [])
    m3_outcome_summary = save_m3_ledger(m3_ledger)

    report["new_m2_signals"] = added
    report["outcome_summary"] = outcome_summary
    report["outcome_errors"] = outcome_errors
    report["new_m3_signals"] = m3_added
    report["m3_outcome_summary"] = m3_outcome_summary
    report["m3_outcome_errors"] = m3_outcome_errors

    paths = save_report(report)

    summary = {
        "scanner": report.get("scanner"),
        "universe": report["universe_count"],
        "fast_success": report["fast_success"],
        "deep_success": report["deep_success"],
        "m2_live_signal_count": report.get("m2_live_signal_count", 0),
        "new_m2_signal_count": len(added),
        "m2_live_counts": report.get("m2_live_counts"),
        "outcome_summary": outcome_summary,
        "outcome_error_count": len(outcome_errors),
        "m3_live_signal_count": report.get("m3_live_signal_count", 0),
        "new_m3_signal_count": len(m3_added),
        "m3_live_counts": report.get("m3_live_counts"),
        "m3_outcome_summary": m3_outcome_summary,
        "m3_outcome_error_count": len(m3_outcome_errors),
        "files": paths,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))

    telegram_sent = send_telegram(report)
    print(f"telegram_sent={telegram_sent}")

    if report["fast_success"] == 0 or report["deep_success"] == 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
